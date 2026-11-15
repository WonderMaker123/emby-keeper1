"""Web 配置管理 API.

设计: Web 端只负责配置的读写与站点浏览, 不运行业务逻辑.
业务由独立的 CLI 容器执行, 它监听 config.toml, 保存后自动热重载.

接口:
    - GET  /api/schema      配置模型 JSON Schema (前端据此渲染字段与校验)
    - GET  /api/config      当前配置 (敏感字段已打码)
    - POST /api/config      保存配置 (Pydantic 校验 + 原子写入)
    - GET  /api/sites       签到站点清单 (中文名/分类/是否需要验证码)
    - GET  /api/summary     配置概览
"""

import asyncio
import base64
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from loguru import logger
from pydantic import ValidationError

from embykeeper.schema import Config, format_errors

from . import bridge_client
from .bridge_client import BridgeError
from .config_io import load_config_for_web
from embykeeper.config import config as ek_config

logger = logger.bind(scheme="webapi")

api = Blueprint("api", __name__)


@api.before_request
def _require_auth():
    """保护所有 API 接口.

    控制台有登录密码时, 未登录不得读写配置或触发任务;
    未设密码 (--public 或其他免登录部署) 时保持开放, 便于内网使用.
    """
    webpass = current_app.config.get("webpass") or ""
    if not webpass:
        return None
    try:
        from flask_login import current_user

        if current_user.is_authenticated:
            return None
    except Exception:
        pass
    return jsonify({"error": "未登录或登录已过期, 请刷新页面重新登录"}), 401

# 需要在输出时打码的字段名片段 (小写匹配)
# session 是 Telegram 登录凭据, 等同于账号控制权, 不应下发到浏览器
SENSITIVE_PATTERNS = (
    "password",
    "api_key",
    "token",
    "api_hash",
    "secret",
    "apprise_uri",
    "session",
)

# 用于在配置对象中匹配同一条记录的标识字段, 顺序即优先级.
IDENTITY_KEYS = ("phone", "username", "url", "name")

# 站点清单缓存: 导入全部签到器模块较慢, 缓存结果避免每次请求都重扫
_SITES_CACHE = {"time": 0.0, "data": None}
_SITES_CACHE_TTL = 300


def mask_value(value: Any) -> Any:
    """对敏感值打码, 仅保留首尾少量字符便于用户确认是哪一条."""
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def mask_config(data: Any) -> Any:
    """递归遍历配置, 对敏感键打码."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if any(pattern in lowered for pattern in SENSITIVE_PATTERNS):
                result[key] = mask_value(value)
            else:
                result[key] = mask_config(value)
        return result
    if isinstance(data, list):
        return [mask_config(item) for item in data]
    return data


def _match_old_item(new_item: Any, old_items: list) -> Any:
    """在旧列表中按标识字段找到对应的记录.

    不能按索引匹配: 用户删除或调整账号顺序后索引会错位, 导致密码串到别的账号上.
    多个账号可能同名 (不同服器用同一用户名), 因此按命中字段数打分, 取最匹配的一条.
    """
    if not isinstance(new_item, dict):
        return None
    best = None
    best_score = 0
    for item in old_items:
        if not isinstance(item, dict):
            continue
        score = 0
        for key in IDENTITY_KEYS:
            value = new_item.get(key)
            if value and item.get(key) == value:
                score += 1
        if score > best_score:
            best, best_score = item, score

    # 兜底: 只有一个旧记录时直接复用, 避免因标识字段临时缺失而丢掉密钥/会话
    if best is None and len(old_items) == 1 and isinstance(old_items[0], dict):
        return old_items[0]
    return best


def restore_masked(new_data: Any, old_data: Any) -> Any:
    """把回传的 '*' 打码值还原为旧配置中的真实值."""
    if isinstance(new_data, dict) and isinstance(old_data, dict):
        result = {}
        for key, value in new_data.items():
            old_value = old_data.get(key)
            lowered = str(key).lower()
            if any(p in lowered for p in SENSITIVE_PATTERNS) and isinstance(value, str) and "*" in value:
                result[key] = old_value
            else:
                result[key] = restore_masked(value, old_value)
        return result
    if isinstance(new_data, list) and isinstance(old_data, list):
        return [restore_masked(item, _match_old_item(item, old_data)) for item in new_data]
    return new_data


@api.route("/schema", methods=["GET"])
def get_schema():
    """返回配置模型的 JSON Schema, 前端据此渲染字段与校验规则."""
    return jsonify(Config.model_json_schema()), 200


@api.route("/config", methods=["GET"])
def get_config():
    """读取当前配置.

    注意: 配置可能被业务进程的热重载或外部编辑改动, 而 runtime_config 只在
    Web 自己保存时刷新. 若一直用内存快照, 界面会显示过期内容.
    因此这里按文件 mtime/size 做轻量检测, 变化时重新从磁盘加载.
    """
    try:
        conf = current_app.config.get("runtime_config")
        if conf is None:
            return jsonify({"error": "配置未加载"}), 503

        if _config_file_changed():
            try:
                current_app.config["runtime_config"] = load_config_for_web(
                    ek_config, current_app.config["basedir"], ""
                )
            except Exception as e:
                logger.warning(f"配置热重载时重新加载失败, 继续使用内存快照: {e}")

        conf = current_app.config.get("runtime_config")
        if conf is None:
            return jsonify({"error": "配置未加载"}), 503
        data = conf.model_dump(mode="json") if hasattr(conf, "model_dump") else {}
        return jsonify(mask_config(data)), 200
    except Exception as e:
        logger.error(f"读取配置失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"读取配置失败: {e}"}), 500


def _config_mtime() -> tuple:
    """返回当前配置文件的 (mtime, size), 作为变更检测依据."""
    basedir = current_app.config.get("basedir")
    if not basedir:
        return (0, 0)
    path = Path(basedir) / "config.toml"
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return (0, 0)


def _config_file_changed() -> bool:
    """判断配置文件是否在 Web 上次保存后发生了变更."""
    marker = current_app.config.get("_config_mtime_marker")
    current = _config_mtime()
    if not marker:
        current_app.config["_config_mtime_marker"] = current
        return False
    current_app.config["_config_mtime_marker"] = current
    return marker != current


@api.route("/config", methods=["POST"])
def save_config():
    """校验并保存配置.

    前端回传的敏感字段可能是打码值 (含 *), 此时按标识字段匹配旧记录并保留原值.
    """
    payload = request.get_json(silent=True) or {}
    new_data = payload.get("config")
    if not isinstance(new_data, dict):
        return jsonify({"error": "请求体缺少 config 对象"}), 400

    conf = current_app.config.get("runtime_config")
    try:
        if conf is not None:
            old_data = conf.model_dump(mode="json") if hasattr(conf, "model_dump") else {}
            new_data = restore_masked(new_data, old_data)
        validated = Config.model_validate(new_data)
    except ValidationError as e:
        return jsonify({"error": format_errors(e)}), 400
    except Exception as e:
        logger.warning(f"配置处理失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"配置校验失败: {e}"}), 400

    try:
        path = save_config_to_storage(validated)
        current_app.config["runtime_config"] = validated
        # 同步重置变更标记: 保存就是本次改动的来源, 不应被下一次读取
        # 误判为「外部修改」而触发一次多余的重新加载
        current_app.config["_config_mtime_marker"] = _config_mtime()
        logger.info(f'配置已保存: "{path}", 业务容器将自动热重载.')
        return jsonify({"ok": True, "message": "配置已保存，业务容器会自动热加载（无需重启）"}), 200
    except Exception as e:
        logger.error(f"保存配置失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"保存配置失败: {e}"}), 500


def save_config_to_storage(conf: Config):
    """把配置写回 config.toml, 返回写入路径描述.

    业务容器通过 watchfiles 监听该文件, 写入后会自动热重载.
    先写临时文件再原子替换, 避免业务容器读到半截内容.
    """
    import tomlkit

    toml_str = tomlkit.dumps(conf.model_dump(mode="json", exclude_none=True))
    mongodb = current_app.config.get("mongodb")
    if mongodb:
        from embykeeper.cache import cache as ek_cache

        ek_cache.set("config", base64.b64encode(toml_str.encode()).decode())
        logger.info("配置已保存到 MongoDB 缓存.")
        return "mongodb"

    basedir = current_app.config.get("basedir")
    if not basedir:
        from embykeeper.config import config as ek_config

        basedir = ek_config.basedir
    if not basedir:
        raise RuntimeError("未设置工作目录, 无法保存配置")

    from pathlib import Path

    path = Path(basedir) / "config.toml"
    tmp = path.with_suffix(".toml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(toml_str)
    tmp.replace(path)
    logger.info(f'配置已保存到 "{path}".')
    return str(path)


def _categorize(name: str, cls) -> str:
    """按模块名与类属性归类, 便于前端分组展示."""
    if "sgk" in name:
        return "社工库"
    if "group" in name or getattr(cls, "chat_name", None):
        return "群组发言"
    if "music" in name or "navidrome" in name:
        return "音乐服"
    if "_old" in name:
        return "旧版兼容"
    return "影视 / 综合"


def _build_site_list() -> list:
    """构建站点元数据列表."""
    from embykeeper.telegram.dynamic import get_cls, get_names

    default_names = set(get_names("checkiner"))
    all_names = set(get_names("checkiner", allow_ignore=True)) | default_names

    sites = []
    for name in sorted(all_names):
        try:
            classes = get_cls("checkiner", names=[name])
        except Exception as e:
            logger.debug(f"跳过站点 {name}: {e.__class__.__name__}: {e}")
            continue
        if not classes:
            continue
        cls = classes[0]
        sites.append(
            {
                "key": name,
                "name": getattr(cls, "name", None) or name,
                "bot_username": getattr(cls, "bot_username", None),
                "chat_name": str(getattr(cls, "chat_name", "") or "") or None,
                "has_captcha": bool(getattr(cls, "bot_use_captcha", True)),
                "category": _categorize(name, cls),
                # 是否在上游默认清单中; 未列入的站点需手动指定才能启用
                "recommended": name in default_names,
            }
        )
    return sites


@api.route("/sites", methods=["GET"])
def get_sites():
    """列出所有可用签到站点, 供前端以中文名勾选."""
    try:
        refresh = request.args.get("refresh") in ("1", "true")
        now = time.time()
        if not refresh and _SITES_CACHE["data"] is not None:
            if now - _SITES_CACHE["time"] < _SITES_CACHE_TTL:
                return jsonify(_SITES_CACHE["data"]), 200

        # 导入签到器模块可能触发 asyncio 初始化, Flask 同步视图没有运行中的循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            sites = _build_site_list()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        sites.sort(key=lambda x: (x["category"], x["name"]))
        categories = []
        for site in sites:
            if site["category"] not in categories:
                categories.append(site["category"])

        payload = {
            "sites": sites,
            "count": len(sites),
            "categories": categories,
            "recommended_count": sum(1 for s in sites if s["recommended"]),
        }
        _SITES_CACHE.update({"time": now, "data": payload})
        return jsonify(payload), 200
    except Exception as e:
        logger.error(f"获取站点列表失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"获取站点列表失败: {e}"}), 500


@api.route("/logs", methods=["GET"])
def get_logs():
    """查询业务容器日志.

    日志实际存于业务容器的内存环形缓冲中, 通过桥接服务拉取.
    since 参数用于前端增量刷新, 避免每次全量传输.
    """
    try:
        data = bridge_client.fetch_logs(
            since=request.args.get("since"),
            level=request.args.get("level"),
            keyword=request.args.get("keyword"),
            limit=int(request.args.get("limit", 300)),
        )
        return jsonify(data), 200
    except BridgeError as e:
        return jsonify({"error": str(e), "logs": [], "unreachable": True}), 200
    except Exception as e:
        logger.error(f"获取日志失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"获取日志失败: {e}", "logs": []}), 200


@api.route("/run", methods=["POST"])
def run_now():
    """立即运行一次.

    无 body → 全部模块各执行一次;
    带 site → 只执行指定站点.
    """
    payload = request.get_json(silent=True) or {}
    site = payload.get("site")
    account = payload.get("account")
    try:
        result = bridge_client.trigger_run(site=site, account=account)
        return jsonify(result), 200
    except BridgeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        logger.error(f"触发运行失败: {e.__class__.__name__}: {e}")
        return jsonify({"ok": False, "error": f"触发运行失败: {e}"}), 500


@api.route("/bridge/health", methods=["GET"])
def bridge_health():
    """检查与控制桥接服务的连通性, 供前端展示业务容器是否在线."""
    return jsonify(bridge_client.bridge_health()), 200


@api.route("/notifier/test", methods=["POST"])
def notifier_test():
    """发送一条测试通知.

    直接用当前配置的 bot_token/chat_id 调 Telegram API,
    不依赖业务容器运行状态, 因此用户填完就能立刻验证是否正确.
    """
    import httpx

    conf = current_app.config.get("runtime_config")
    if conf is None or conf.notifier is None:
        return jsonify({"ok": False, "error": "配置未加载"}), 503

    notifier = conf.notifier
    if notifier.method != "telegram":
        return jsonify(
            {"ok": False, "error": "当前通知方式不是 Telegram, 请先在配置中切换到 telegram"}
        ), 400
    if not notifier.bot_token or not notifier.chat_id:
        return jsonify({"ok": False, "error": "请先填写 Bot Token 和 Chat ID"}), 400

    text = "Embykeeper 通知测试\n—— 如果你看到这条消息, 说明机器人通知配置正确。"
    url = f"https://api.telegram.org/bot{notifier.bot_token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": notifier.chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
    except Exception as e:
        return jsonify(
            {
                "ok": False,
                "error": (
                    f"网络请求失败: {e.__class__.__name__}\n"
                    "请确认容器可访问 api.telegram.org, 必要时在配置中设置代理。"
                ),
            }
        ), 200

    if resp.status_code == 200:
        return jsonify({"ok": True, "message": "测试通知已发送, 请查看 Telegram"}), 200

    try:
        detail = resp.json().get("description") or ""
    except Exception:
        detail = resp.text[:200]

    low = detail.lower()
    hint = ""
    if "chat not found" in low:
        hint = "提示: 先给机器人发一条任意消息, 并确认 chat_id 正确 (群组为负数)"
    elif "unauthorized" in low:
        hint = "提示: Bot Token 不正确, 请到 @BotFather 重新获取"
    elif "bot was blocked" in low:
        hint = "提示: 该会话已屏蔽机器人, 请先解除屏蔽"

    return jsonify(
        {"ok": False, "error": f"发送失败 (HTTP {resp.status_code}): {detail}\n{hint}".strip()}
    ), 200


@api.route("/sites/template-fields", methods=["GET"])
def get_template_fields():
    """返回自定义站点的可配置字段定义.

    自定义站点基于上游的 TemplateACheckin (模板 A) 机制实现:
    在 site.checkiner 中写入 "templ_a<@机器人用户名>", 并在 checkiner 段以同一个
    键名提供参数, 即可把任意符合模板 A 的 Bot 当作站点签到.

    字段来自 TemplateACheckinConfig, 带上中文说明供前端渲染.
    """
    try:
        from embykeeper.telegram.checkiner._templ_config import TemplateACheckinConfig

        schema = TemplateACheckinConfig.model_json_schema()
        props = schema.get("properties", {})

        # 中文标签与说明: 上游只有英文注释, 这里补充面向用户的描述
        labels = {
            "name": ("站点显示名", "签到日志中显示的站点名称, 例如「我的小站」"),
            "bot_checkin_cmd": ("签到命令", "发送给 Bot 的命令, 例如 /start 或 /checkin"),
            "bot_checkin_button": ("签到按钮文本", "面板上签到按钮的文字, 例如 签到；支持多个"),
            "bot_use_captcha": ("使用验证码识别", "Bot 返回图片验证码时是否自动识别"),
            "bot_captcha_len": ("验证码长度", "验证码字符数, 不确定可留空"),
            "bot_success_keywords": ("成功关键词", "包含这些词的回复视为签到成功"),
            "bot_fail_keywords": ("失败关键词", "包含这些词的回复视为签到失败并重试"),
            "bot_checked_keywords": ("已签到关键词", "包含这些词的回复视为今日已签到"),
            "bot_account_fail_keywords": ("账号失效关键词", "出现这些词表示账号失效, 例如 未注册"),
            "bot_text_ignore": ("忽略文本", "包含这些词的消息直接跳过"),
            "bot_text_ignore_answer": ("忽略回复", "按钮回复中包含这些词时跳过"),
            "bot_success_pat": ("成功正则", "从成功消息中提取额外信息的正则表达式"),
            "bot_checkin_caption_pat": ("验证码图片匹配", "仅当图片说明匹配该正则时才当作验证码"),
            "templ_panel_keywords": ("面板关键词", "面板消息包含这些词时才尝试点签到按钮"),
            "use_button_answer": ("读取按钮回复", "点击按钮后是否解析回复内容"),
        }

        # 展示顺序: 必填项与最常用的在前
        order = [
            "name",
            "bot_checkin_cmd",
            "bot_checkin_button",
            "bot_use_captcha",
            "bot_captcha_len",
            "bot_success_keywords",
            "bot_fail_keywords",
            "bot_checked_keywords",
            "bot_account_fail_keywords",
            "bot_text_ignore",
            "bot_text_ignore_answer",
            "templ_panel_keywords",
            "use_button_answer",
            "bot_success_pat",
            "bot_checkin_caption_pat",
        ]

        fields = []
        for key in order:
            if key not in props:
                continue
            raw = props[key]
            label, desc = labels.get(key, (key, ""))
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "description": desc,
                    "schema": raw,
                    # name 与命令是最小可用集, 标记为推荐填写
                    "recommended": key in ("name", "bot_checkin_cmd"),
                }
            )
        return jsonify({"fields": fields, "count": len(fields)}), 200
    except Exception as e:
        logger.error(f"获取模板字段失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"获取模板字段失败: {e}"}), 500


@api.route("/sites/custom", methods=["GET"])
def get_custom_sites():
    """列出当前配置中的自定义站点.

    识别依据: site.checkiner 中的 templ_a<@xxx> 条目, 以及 checkiner 段里
    与之一一对应的参数配置.
    """
    conf = current_app.config.get("runtime_config")
    if conf is None:
        return jsonify({"error": "配置未加载"}), 503

    tokens = (conf.site.checkiner if conf.site else None) or []
    custom_tokens = [t for t in tokens if str(t).startswith("templ_")]

    # checkiner 段是 extra=allow, 自定义站点的参数就存在这里
    raw = conf.checkiner.model_dump() if conf.checkiner else {}

    items = []
    for token in custom_tokens:
        # 从 templ_a<@SomeBot> 提取机器人用户名
        bot = ""
        if "<@" in token and token.endswith(">"):
            bot = token[token.index("<@") + 2 : -1]
        elif "<" in token and token.endswith(">"):
            bot = token[token.index("<") + 1 : -1]

        params = raw.get(token) or {}
        items.append(
            {
                "token": token,
                "bot_username": bot,
                "template": token.split("<")[0],
                "name": params.get("name") or (f"@{bot}" if bot else token),
                "params": params,
            }
        )

    return jsonify({"custom_sites": items, "count": len(items)}), 200


@api.route("/sites/validate-bot", methods=["POST"])
def validate_bot():
    """校验机器人用户名是否可解析.

    只做格式与重复性检查, 不去 Telegram 实际探测 (那需要已登录的会话,
    且 Web 容器不持有会话文件). 真正的可达性由业务容器首次签到确认.
    """
    payload = request.get_json(silent=True) or {}
    bot = (payload.get("bot_username") or "").strip().lstrip("@")
    if not bot:
        return jsonify({"ok": False, "error": "请填写机器人用户名"}), 400

    import re

    # Telegram 用户名规则: 5-32 字符, 字母开头, 仅含字母数字下划线
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", bot):
        return jsonify(
            {
                "ok": False,
                "error": "机器人用户名格式不正确：应以字母开头，仅含字母、数字、下划线，长度 5-32",
            }
        ), 200

    if not bot.lower().endswith("bot"):
        return jsonify(
            {
                "ok": True,
                "warning": "Telegram 机器人用户名通常以 bot 结尾，请确认没有填错",
                "token": f"templ_a<@{bot}>",
            }
        ), 200

    return jsonify({"ok": True, "token": f"templ_a<@{bot}>"}), 200


@api.route("/sites/resolve", methods=["POST"])
def resolve_sites():
    """将站点条目列表解析为实际生效的站点.

    site.checkiner 是一个带修饰符的表达式列表, 支持:
      - 模块名 (peach)
      - 排除标记 (-all / -sgk)
      - 模板站点 (templ_a<@some_bot>)
    前端用它做「实际生效」预览, 避免用户改了配置却不知道结果.
    """
    payload = request.get_json(silent=True) or {}
    tokens = payload.get("tokens")
    if tokens is None:
        tokens = []
    if not isinstance(tokens, list):
        return jsonify({"error": "tokens 必须是字符串列表"}), 400

    try:
        from embykeeper.telegram.dynamic import extract, get_cls, get_names

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 未指定清单时上游默认启用全部推荐站点
            effective_tokens = tokens if tokens else get_names("checkiner")
            classes = extract(get_cls("checkiner", names=list(effective_tokens)))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        resolved = []
        for cls in classes:
            resolved.append(
                {
                    "name": getattr(cls, "name", None) or cls.__name__,
                    "key": getattr(cls, "templ_name", None) or cls.__module__.rsplit(".", 1)[-1],
                    "bot_username": getattr(cls, "bot_username", None),
                }
            )
        resolved.sort(key=lambda x: x["name"])
        return jsonify({"resolved": resolved, "count": len(resolved), "tokens": tokens}), 200
    except Exception as e:
        logger.error(f"解析站点失败: {e.__class__.__name__}: {e}")
        return jsonify({"error": f"解析站点失败: {e}"}), 500


@api.route("/summary", methods=["GET"])
def get_summary():
    """配置概览: 账号数量、启用站点、OCR 状态等, 用于控制台首页展示."""
    conf = current_app.config.get("runtime_config")
    if conf is None:
        return jsonify({"error": "配置未加载"}), 503

    tokens = [str(t) for t in (conf.site.checkiner or [])] if conf.site else []

    # 区分「全部站点」与「指定站点」:
    #   - 空列表 / 只有排除标记 (-all, -sgk) 且无普通站点与模板站点 => 全量签到
    #   - 出现普通模块名或 templ_ 模板站点 => 指定站点
    # 早期实现只看列表是否为空, 会把 ["-all","-sgk"] 误判为「指定站点」.
    positive = [t for t in tokens if not t.startswith("-")]
    sites_mode = "selected" if positive else "all"

    ocr = conf.ocr
    basedir = current_app.config.get("basedir")
    config_path = str((basedir / "config.toml") if basedir else "config.toml")

    return (
        jsonify(
            {
                "emby_accounts": len(conf.emby.account or []),
                "subsonic_accounts": len(conf.subsonic.account or []),
                "telegram_accounts": len(conf.telegram.account or []),
                "enabled_sites": positive,
                "enabled_sites_count": len(positive),
                "excluded_sites": [t for t in tokens if t.startswith("-")],
                "sites_mode": sites_mode,
                "ocr": {
                    "provider": ocr.provider if ocr else None,
                    "model": ocr.ai_model if ocr else None,
                    "ai_configured": bool(ocr and ocr.ai_api_key),
                },
                "checkiner_schedule": {
                    "time_range": conf.checkiner.time_range if conf.checkiner else None,
                    "interval_days": conf.checkiner.interval_days if conf.checkiner else None,
                },
                "notifier_enabled": bool(conf.notifier.enabled) if conf.notifier else False,
                "config_path": config_path,
            }
        ),
        200,
    )
