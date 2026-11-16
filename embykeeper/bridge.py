"""业务容器内的控制桥接服务.

架构背景:
    Web 容器与业务容器是两个独立进程, Web 无法直接读取业务的日志或触发任务.
    两个容器都以 --net host 运行, 因此可以共享主机网络栈, 通过本机回环通信.

本模块在**业务容器**内启动一个仅监听 127.0.0.1 的轻量 HTTP 服务, 提供:
    - GET  /logs          查询最近的日志
    - GET  /status        当前运行状态
    - POST /run           立即运行一次全部任务 / 指定站点
    - GET  /healthz       存活检查

实现说明:
    刻意只使用标准库 http.server, 不引入 fastapi/uvicorn. 原因是桥接属于
    「锦上添花」的能力, 不应该因为 Web 侧依赖版本差异而拖垮业务容器的启动;
    requirements 中的 fastapi 在旧镜像里未必存在, 而业务容器是签到主进程,
    启动失败代价过高.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from loguru import logger

bridge_logger = logger.bind(scheme="bridge", nonotify=True)

# 日志环形缓冲: Web 端轮询读取, 避免每个请求都去翻磁盘
_log_buffer: Deque[Dict[str, Any]] = deque(maxlen=4000)
_log_lock = threading.Lock()

TOKEN_FILE = "control.token"
PORT_FILE = "control.port"
DEFAULT_PORT = 8765


class LogSink:
    """把 loguru 记录收集到环形缓冲, 供 Web 端查询.

    独立于终端输出: 终端照常打印, 这里只额外收集一份结构化数据.
    """

    def __init__(self, max_records: int = 4000):
        self.max_records = max_records

    def write(self, message):
        record = message.record
        try:
            entry = {
                "time": record["time"].isoformat(),
                "level": record["level"].name,
                "message": record["message"],
                "scheme": record["extra"].get("scheme"),
                "name": record["extra"].get("name"),
                "username": record["extra"].get("username"),
                "run_id": record["extra"].get("run_id"),
            }
        except Exception:
            return
        with _log_lock:
            _log_buffer.append(entry)


def install_log_sink() -> int:
    """安装日志收集 sink, 返回 handler id (便于移除)."""
    return logger.add(LogSink(), level="INFO", enqueue=True)


def get_logs(
    since: Optional[str] = None,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """按条件筛选日志.

    since 为 ISO 时间字符串, 返回该时间之后的记录, 便于前端增量拉取.
    """
    with _log_lock:
        items = list(_log_buffer)

    if since:
        items = [x for x in items if x["time"] > since]

    if level:
        levels = {l.strip().upper() for l in level.split(",") if l.strip()}
        if levels:
            items = [x for x in items if x["level"].upper() in levels]

    if keyword:
        kw = keyword.lower()
        items = [x for x in items if kw in str(x["message"]).lower()]

    return items[-limit:]


def get_or_create_token(basedir: Path) -> str:
    """读取或生成桥接令牌, 持久化到数据目录供 Web 容器读取."""
    path = Path(basedir) / TOKEN_FILE
    if path.is_file():
        try:
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            pass

    token = secrets.token_urlsafe(32)
    try:
        path.write_text(token, encoding="utf-8")
        path.chmod(0o600)
    except OSError as e:
        bridge_logger.warning(f"无法写入控制令牌文件, Web 端可能无法读取日志: {e}")
    return token


def _now_iso() -> str:
    return datetime.now().isoformat()


class _Handler(BaseHTTPRequestHandler):
    """极简 JSON 处理器, 路由在 do_GET / do_POST 中分发."""

    # 由 build_server 注入
    token: str = ""
    runtime_getter: Optional[Callable] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    server_version = "EmbykeeperBridge/1.0"

    def log_message(self, fmt, *args):
        # 默认实现会往 stderr 打访问日志, 会污染签到日志输出, 这里静默
        return

    # ---------- 工具方法 ----------

    def _send_json(self, payload: Dict[str, Any], status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorized(self, query: Dict[str, List[str]]) -> bool:
        provided = self.headers.get("x-control-token")
        if not provided:
            provided = (query.get("token") or [""])[0]
        return bool(self.token) and provided == self.token

    def _read_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) or {}
        except Exception:
            return {}

    # ---------- 路由 ----------

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path == "/healthz":
            return self._send_json({"status": "ok", "service": "embykeeper-bridge"})

        if not self._authorized(query):
            return self._send_json({"error": "无效的控制令牌"}, 401)

        if path == "/logs":
            try:
                limit = int((query.get("limit") or ["300"])[0])
            except ValueError:
                limit = 300
            limit = max(1, min(limit, 2000))
            items = get_logs(
                since=(query.get("since") or [None])[0],
                level=(query.get("level") or [None])[0],
                keyword=(query.get("keyword") or [None])[0],
                limit=limit,
            )
            return self._send_json({"logs": items, "count": len(items), "server_time": _now_iso()})

        if path == "/status":
            runtime = self.runtime_getter() if self.runtime_getter else None
            if runtime is None:
                return self._send_json({"running": False, "detail": "运行时未初始化"})
            try:
                return self._send_json(runtime.snapshot())
            except Exception as e:
                return self._send_json({"running": False, "detail": f"{e}"}, 500)

        if path == "/login/status":
            # 登录会话状态: 控制台轮询此接口, 据此弹出验证码输入框
            from embykeeper.login_session import login_manager

            session = login_manager.get()
            if session is None:
                return self._send_json({"active": False, "state": "idle"})
            payload = {"active": True}
            payload.update(session.snapshot())
            return self._send_json(payload)

        return self._send_json({"error": "未知接口"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if not self._authorized(query):
            return self._send_json({"error": "无效的控制令牌"}, 401)

        if path not in ("/run", "/login/start", "/login/submit"):
            return self._send_json({"error": "未知接口"}, 404)

        loop = self.loop
        if loop is None:
            return self._send_json({"ok": False, "error": "业务事件循环不可用"}, 503)

        body = self._read_body()

        # ---------- 登录: 发起 ----------
        if path == "/login/start":
            runtime = self.runtime_getter() if self.runtime_getter else None
            if runtime is None:
                return self._send_json({"ok": False, "error": "运行时未初始化"}, 503)
            phone = (body or {}).get("phone")
            if not phone:
                return self._send_json({"ok": False, "error": "缺少手机号"}, 400)

            # 登录会阻塞到拿到验证码并完成握手, 因此放到后台, 立即返回
            async def _login():
                try:
                    await runtime.login_account(phone)
                except Exception as e:
                    bridge_logger.error(f"登录任务失败: {e.__class__.__name__}: {e}")

            asyncio.run_coroutine_threadsafe(_login(), loop)
            return self._send_json({"ok": True, "message": "已发起登录, 请留意验证码提示"})

        # ---------- 登录: 提交验证码/密码 ----------
        if path == "/login/submit":
            from embykeeper.login_session import login_manager

            session_id = (body or {}).get("session_id", "")
            kind = (body or {}).get("kind", "code")
            value = (body or {}).get("value", "")
            if not value:
                return self._send_json({"ok": False, "error": "输入内容为空"}, 400)
            if kind not in ("code", "password"):
                return self._send_json({"ok": False, "error": "未知的提交类型"}, 400)

            if login_manager.submit(session_id, kind, value):
                return self._send_json({"ok": True, "message": "已提交"})
            return self._send_json(
                {"ok": False, "error": "登录会话已失效或与当前会话不匹配, 请重新发起登录"}, 409
            )

        # ---------- 立即运行 ----------
        runtime = self.runtime_getter() if self.runtime_getter else None
        if runtime is None:
            return self._send_json({"ok": False, "error": "运行时未初始化, 请等待业务启动"}, 503)

        site = body.get("site")
        account = body.get("account")
        scope = body.get("scope") or "all"

        try:
            if site:
                # 单站点签到需登录 Telegram 会话, 耗时可能达分钟级.
                # 因此同样后台执行并立即返回, 避免 HTTP 连接超时或前端卡死.
                async def _one():
                    try:
                        result = await runtime.trigger(site, account=account)
                        if not result.get("ok"):
                            bridge_logger.warning(
                                f"手动触发站点 {site} 未成功: {result.get('message', '')}"
                            )
                    except Exception as e:
                        bridge_logger.error(f"手动触发站点 {site} 失败: {e.__class__.__name__}: {e}")

                asyncio.run_coroutine_threadsafe(_one(), loop)
                return self._send_json({"ok": True, "message": f"已开始签到 {site}, 请查看日志"})

            # 后台启动后立即返回, 避免 HTTP 请求长时间挂起
            async def _bg():
                try:
                    await runtime.run_once(scope=scope)
                except Exception as e:
                    bridge_logger.error(f"立即执行任务失败: {e.__class__.__name__}: {e}")

            asyncio.run_coroutine_threadsafe(_bg(), loop)
            msg = "已在后台开始执行站点签到, 请查看日志" if scope == "checkin" else "已在后台开始执行, 请查看日志"
            return self._send_json({"ok": True, "message": msg})
        except Exception as e:
            return self._send_json({"ok": False, "error": f"触发失败: {e}"}, 500)


def _write_port_file(basedir: Path, port: int):
    """把实际监听端口写入共享目录, 供 Web 容器读取.

    端口可能因占用而变化, 写死会造成 Web 端连不上却无从得知原因.
    """
    try:
        (Path(basedir) / PORT_FILE).write_text(str(port), encoding="utf-8")
    except OSError as e:
        bridge_logger.warning(f"无法写入控制端口文件, Web 端将尝试默认端口: {e}")


def _claim_server(runtime_getter, basedir: Path, port: int, host: str, loop, attempts: int = 10):
    """从 port 开始尝试绑定, 跳过被占用的端口."""
    for offset in range(attempts):
        candidate = port + offset
        try:
            return build_server(
                runtime_getter, basedir, port=candidate, host=host, loop=loop
            ), candidate
        except OSError:
            continue
    return None, None


class _ReusableHTTPServer(ThreadingHTTPServer):
    """禁止地址复用.

    ThreadingHTTPServer 默认 allow_reuse_address=True, 在部分平台 (尤其 Windows)
    上允许多个进程绑定同一端口, 导致端口冲突检测失效、请求被随机分发到旧实例.
    回环调试服务不需要 TIME_WAIT 快速重用, 因此关闭该选项.
    """

    allow_reuse_address = False


def build_server(
    runtime_getter: Callable,
    basedir: Path,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> ThreadingHTTPServer:
    """构建（但不启动）桥接 HTTP 服务, 便于测试."""
    token = get_or_create_token(basedir)

    handler = type(
        "BridgeHandler",
        (_Handler,),
        {"token": token, "runtime_getter": staticmethod(runtime_getter), "loop": loop},
    )
    server = _ReusableHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def start_bridge(
    runtime_getter: Callable,
    basedir: Path,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    """在后台线程启动桥接服务, 返回 (server, thread)."""
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

    server, actual_port = _claim_server(runtime_getter, basedir, port, host, loop)
    if server is None:
        bridge_logger.warning(
            f"控制桥接服务启动失败 (端口 {port}~{port + 9} 均被占用). "
            "控制台的日志与立即运行将不可用."
        )
        # 清理陈旧的端口文件, 避免 Web 端连到已不存在的服务
        try:
            (Path(basedir) / PORT_FILE).unlink(missing_ok=True)
        except OSError:
            pass
        return None, None

    _write_port_file(basedir, actual_port)

    def _serve():
        try:
            server.serve_forever(poll_interval=0.5)
        except Exception as e:
            bridge_logger.error(f"控制桥接服务异常退出: {e.__class__.__name__}: {e}")

    thread = threading.Thread(target=_serve, name="control-bridge", daemon=True)
    thread.start()
    bridge_logger.info(f"控制桥接服务已启动: http://{host}:{actual_port}")
    return server, thread
