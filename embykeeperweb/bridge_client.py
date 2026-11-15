"""与业务容器控制桥接服务的通信客户端.

Web 容器与业务容器均以 --net host 运行, 因此可通过 127.0.0.1 访问对方的桥接服务.
桥接服务只监听回环地址, 并用共享令牌鉴权, 令牌存放在数据目录的 control.token 中.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from loguru import logger

logger = logger.bind(scheme="webapi")

DEFAULT_BRIDGE_URL = "http://127.0.0.1:8765"
TOKEN_FILE = "control.token"
PORT_FILE = "control.port"
DEFAULT_WEB_PORT = 1818


def _basedir() -> Path:
    return Path(os.environ.get("EK_BASEDIR") or "/app")


def bridge_url() -> str:
    """推导桥接服务地址.

    优先使用显式环境变量; 否则读取业务容器写入的 control.port
    (端口可能因占用而自动偏移), 最后回退到默认端口.
    """
    explicit = os.environ.get("EK_BRIDGE_URL")
    if explicit:
        return explicit.rstrip("/")

    host = os.environ.get("EK_BRIDGE_HOST", "127.0.0.1")
    try:
        port_file = _basedir() / PORT_FILE
        if port_file.is_file():
            port = int(port_file.read_text(encoding="utf-8").strip())
            if 0 < port < 65536:
                return f"http://{host}:{port}"
    except (OSError, ValueError):
        pass
    return DEFAULT_BRIDGE_URL


def web_port() -> int:
    return int(os.environ.get("PORT", DEFAULT_WEB_PORT))


def control_token() -> Optional[str]:
    """读取业务容器写入的桥接令牌."""
    path = _basedir() / TOKEN_FILE
    try:
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            return token or None
    except OSError as e:
        logger.debug(f"读取控制令牌失败: {e}")
    return None


class BridgeError(Exception):
    """桥接服务不可用或返回错误."""


def _request(method: str, path: str, timeout: float = 20, **kwargs) -> Dict[str, Any]:
    token = control_token()
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["x-control-token"] = token
    try:
        resp = httpx.request(
            method, f"{bridge_url()}{path}", headers=headers, timeout=timeout, **kwargs
        )
    except httpx.ConnectError as e:
        raise BridgeError(
            "无法连接业务容器。请确认业务容器正在运行, 且与控制台共享主机网络 (--net host)。"
        ) from e
    except httpx.TimeoutException as e:
        raise BridgeError("业务容器响应超时, 请稍后重试。") from e
    except Exception as e:
        raise BridgeError(f"请求业务容器失败: {e.__class__.__name__}: {e}") from e

    if resp.status_code == 401:
        raise BridgeError("控制令牌无效, 请确认两个容器挂载了同一数据目录。")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail") or ""
        except Exception:
            detail = resp.text[:200]
        raise BridgeError(f"业务容器返回错误 (HTTP {resp.status_code}): {detail}")

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def bridge_health() -> Dict[str, Any]:
    """探测桥接服务是否可达."""
    try:
        return _request("GET", "/healthz", timeout=5)
    except BridgeError as e:
        return {"status": "unreachable", "detail": str(e)}


def fetch_logs(
    since: Optional[str] = None,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 300,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if since:
        params["since"] = since
    if level:
        params["level"] = level
    if keyword:
        params["keyword"] = keyword
    return _request("GET", "/logs", params=params)


def fetch_status() -> Dict[str, Any]:
    return _request("GET", "/status")


def trigger_run(site: Optional[str] = None, account: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if site:
        payload["site"] = site
    if account:
        payload["account"] = account
    return _request("POST", "/run", json=payload, timeout=60)
