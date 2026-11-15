"""Web 控制台.

职责边界 (重要):
    本进程**只负责配置管理** —— 读取/校验/写回 config.toml, 展示站点清单,
    以及通过本机回环地址与业务进程通信 (查看日志、触发一次运行).

    签到/保活的调度与执行由**业务进程** (`embykeeper`) 承担, 两者在同一容器内
    并行运行, 由 scripts/docker-entrypoint.sh 启动.

为什么不做进程内嵌:
    业务以 asyncio 事件循环为核心, 控制台是 Werkzeug 同步模型. 早期版本用
    eventlet 的 monkey patch 把两者挤进同一进程, 并用 PTY + SocketIO 把业务
    进程挂在 Web 进程下 —— 结果是 eventlet 被官方弃用、启动有大量告警, 且
    Web 崩了业务就停, 无法独立升级. 现在两者各自独立运行, 只通过回环 HTTP
    通信, 不再需要 monkey patch.
"""

import os
import time
from pathlib import Path

import typer
from loguru import logger
from flask import Flask, Blueprint, render_template, redirect, url_for, request, send_from_directory
from flask_login import LoginManager, login_user, login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from embykeeper.config import config as ek_config
from embykeeper.schema import Config

from . import __version__
from .api import api as api_blueprint
from .config_io import load_config_for_web

version = f"V{__version__}"

cli = typer.Typer(invoke_without_command=True)

app = Flask(__name__, static_folder="templates/assets", static_url_path=None)
# 部署在反向代理之后时, 需要信任 X-Forwarded-* 才能正确生成跳转地址
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

app.config["SECRET_KEY"] = os.urandom(24)
app.config["BASE_PREFIX"] = "/"
# 运行期状态
app.config["runtime_config"] = None
app.config["basedir"] = None
app.config["webpass"] = ""
app.config["faillog"] = []

bp = Blueprint("main", __name__)


# ===================== 认证 =====================


class DummyUser:
    """单用户模型.

    控制台只有一个密码, 没有多用户体系, 因此登录态用一个空壳对象表示,
    Flask-Login 只关心 is_authenticated / get_id.
    """

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return 0


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "main.login"


@login_manager.user_loader
def load_user(_):
    return DummyUser()


def is_authenticated():
    """未设置密码 (内网/免登录部署) 时一律放行."""
    webpass = app.config.get("webpass") or ""
    if not webpass:
        return True
    return current_user.is_authenticated


# ===================== 页面 =====================


@bp.route("/")
def index():
    return redirect(url_for("main.ui"))


@bp.route("/ui")
@login_required
def ui():
    """控制台单页应用."""
    entry = find_ui_assets()
    if entry is None:
        return (
            render_template("ui_missing.html", version=version, prefix=app.config["BASE_PREFIX"]),
            503,
        )
    return render_template(
        "ui.html",
        version=version,
        prefix=app.config["BASE_PREFIX"],
        entry_js=entry["js"],
        entry_css=entry["css"],
    )


@bp.route("/login", methods=["GET"])
def login():
    return render_template("login.html", version=version, prefix=app.config["BASE_PREFIX"])


@bp.route("/login", methods=["POST"])
def login_submit():
    password = request.form.get("password", "")
    webpass = os.environ.get("EK_WEBPASS", "")
    if not webpass:
        emsg = "后台没有设置控制台密码, 无法登录."
    elif sum(t > time.time() - 3600 for t in app.config["faillog"][-5:]) == 5:
        emsg = "一小时内有过多次失败登录, 请稍后再试."
    else:
        if password == webpass:
            login_user(DummyUser())
            return redirect(request.args.get("next") or url_for("main.ui"))
        emsg = "密码错误, 请重试."
        app.config["faillog"].append(time.time())
    return render_template("login.html", emsg=emsg, version=version, prefix=app.config["BASE_PREFIX"])


@bp.route("/healthz")
def healthz():
    """容器健康检查: 只验证 Web 进程存活, 不触碰业务进程."""
    return "200 OK"


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html", version=version, prefix=app.config["BASE_PREFIX"]), 404


# ===================== 前端产物定位 =====================


def _ui_dist_candidates():
    """前端构建产物的可能位置.

    1. 包内 templates/assets/dist: 本地 `npm run build` 的默认输出, 便于开发时
       改完直接刷新页面;
    2. /fe-dist: Docker 镜像构建阶段由 frontend-builder 生成并复制进来.
       该目录不在 Python 包内 (dist 被 .gitignore 排除, 不会进 wheel),
       因此必须作为独立位置探测, 否则用官方镜像部署时控制台永远是「未构建」.
    """
    yield Path(app.static_folder) / "dist"
    yield Path("/fe-dist")


def find_ui_assets():
    """定位前端入口文件.

    Vite 产物文件名带内容 hash, 不能写死在模板里. 每次重新构建都会产生新的
    hash 文件而旧文件不会自动消失; 若把多个 index-*.js 都返回, 浏览器会同时
    加载多份入口代码, 导致重复挂载或加载过期逻辑. 因此只取 mtime 最新的一个.
    """
    for dist in _ui_dist_candidates():
        entry = _find_entry_in(dist)
        if entry is not None:
            return entry
    return None


def _find_entry_in(dist: Path):
    assets = dist / "assets"
    if not assets.is_dir():
        return None

    def newest(pattern):
        files = sorted(assets.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    entry_js = newest("index-*.js")
    entry_css = newest("index-*.css")
    if entry_js is None:
        return None

    # 静态路径必须与实际存放位置一致, 否则浏览器 404
    if dist.name == "dist" and dist.parent.name == "assets":
        # 包内产物: Flask 以 /assets 为根, 对应 dist/assets 下的文件
        base = f"{app.config['BASE_PREFIX']}/assets/dist/assets"
    else:
        # 镜像内置产物 (/fe-dist): 结构为 /fe-dist/assets/<file>, 需带 assets 层级
        base = f"{app.config['BASE_PREFIX']}/ui-assets/assets"

    return {
        "js": [f"{base}/{entry_js.name}"],
        "css": [f"{base}/{entry_css.name}"] if entry_css else [],
    }


def set_static_url_path(app, prefix):
    app.static_url_path = f"{prefix}/assets"
    app.view_functions.pop("static", None)
    app.add_url_rule(
        f"{app.static_url_path}/<path:filename>", endpoint="static", view_func=app.send_static_file
    )


def mount_image_dist(app, prefix):
    """把镜像内置的前端产物 (/fe-dist) 挂载为静态目录.

    该目录不在 Python 包内, 无法靠 Flask 的 static_folder 提供,
    因此单独注册一条静态路由.
    """
    dist = Path("/fe-dist")
    if not dist.is_dir():
        return

    app.add_url_rule(
        f"{prefix}/ui-assets/<path:filename>",
        endpoint="ui_assets",
        view_func=lambda filename: send_from_directory(dist, filename),
    )


# ===================== 启动 =====================


def serve(port, host, debug, wait, prefix, extra_args):
    """启动配置控制台.

    只加载配置用于展示与校验, 不启动任何业务逻辑.
    保存配置后由业务进程侧的 watchfiles 监听 config.toml 自动热重载.
    """
    app.config["BASE_PREFIX"] = (prefix or "").rstrip("/")
    app.config["webpass"] = os.environ.get("EK_WEBPASS", "")

    set_static_url_path(app, app.config["BASE_PREFIX"])
    mount_image_dist(app, app.config["BASE_PREFIX"])

    app.register_blueprint(bp, url_prefix=app.config["BASE_PREFIX"])
    app.register_blueprint(api_blueprint, url_prefix=f"{app.config['BASE_PREFIX']}/api")

    # 数据目录: 与业务进程共用, config.toml / cache.json / 控制令牌都在这里
    basedir = os.environ.get("EK_BASEDIR") or "/app/data"
    app.config["basedir"] = Path(basedir)
    app.config["basedir"].mkdir(parents=True, exist_ok=True)

    loaded = load_config_for_web(
        ek_config, app.config["basedir"], os.environ.get("EK_CONFIG", "")
    )
    app.config["runtime_config"] = loaded or Config()
    if loaded is None:
        logger.warning("未找到有效配置, 请通过控制台填写并保存.")
    else:
        logger.info(f"已加载配置: {app.config['basedir'] / 'config.toml'}")

    logger.info(f"Embykeeper 配置控制台已启动: {host}:{port} (prefix={prefix or '/'})")
    app.run(port=port, host=host, debug=debug, use_reloader=False, threaded=True)


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    basedir: str = typer.Option(None, "--basedir", help="工作目录 (兼容旧版参数)"),
    public: bool = typer.Option(False, "--public", help="允许无需登录访问 (兼容旧版参数)"),
    port: int = typer.Option(1818, envvar="PORT", show_envvar=False),
    host: str = "0.0.0.0",
    debug: bool = False,
    wait: bool = False,
    prefix: str = typer.Option("", envvar="EK_BASE_PREFIX", help="Base URL prefix (e.g. /ek)"),
):
    """未指定子命令时直接启动控制台.

    兼容旧镜像 entrypoint 的调用形式:
        embykeeperweb --basedir /app --public
    同时保留 `embykeeperweb run` 的显式写法.
    """
    if ctx.invoked_subcommand is not None:
        return

    if basedir:
        os.environ["EK_BASEDIR"] = basedir
    if public:
        # 旧版 --public 表示免登录, 清空密码使校验放行
        os.environ.pop("EK_WEBPASS", None)

    serve(port, host, debug, wait, prefix, list(ctx.args))


@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def run(
    ctx: typer.Context,
    port: int = typer.Option(1818, envvar="PORT", show_envvar=False),
    host: str = "0.0.0.0",
    debug: bool = False,
    wait: bool = False,
    prefix: str = typer.Option("", envvar="EK_BASE_PREFIX", help="Base URL prefix (e.g. /ek)"),
):
    serve(port, host, debug, wait, prefix, ctx.args)


if __name__ == "__main__":
    cli()
