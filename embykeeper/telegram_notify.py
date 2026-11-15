"""Telegram 机器人直推通知.

原项目的 Bot 直推已被移除, 只保留 Apprise. 但 Apprise 需要自建服务或配置
tgram:// 格式的 URI, 对普通用户门槛过高. 这里直接调用 Bot HTTP API,
用户只需从 @BotFather 拿到 Token、填上 Chat ID 即可.

接口与 AppriseStream 保持一致 (write/close/join), 因此可在 notify.py 中互换,
上层日志过滤器无需改动.
"""

import httpx
from loguru import logger
from rich.text import Text

logger = logger.bind(scheme="notifier", nonotify=True)

# Telegram 单条消息上限 4096 字符, 留出富文本余量
MAX_MESSAGE_LEN = 3800


class TelegramStream:
    """把 loguru 日志流写入 Telegram 会话.

    loguru 写入的格式为 "LEVEL#MESSAGE" (由 notify.py 的 _formatter 生成).
    """

    def __init__(self, token: str, chat_id: str, timeout: int = 15, proxy: str = None):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.proxy = proxy
        self._client = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                proxy=self.proxy,
                # Telegram API 在部分网络下需要跳过严格校验, 这里保持默认安全设置
                follow_redirects=True,
            )
        return self._client

    def _send(self, text: str, silent: bool = False) -> bool:
        """调用 sendMessage 发送一条消息, 失败仅记录日志不抛错."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "disable_notification": silent,
        }
        try:
            resp = self._get_client().post(url, json=payload)
        except Exception as e:
            logger.warning(f"Telegram 通知发送失败 (网络异常): {e.__class__.__name__}: {e}")
            return False

        if resp.status_code == 200:
            return True

        # 把 Telegram 的错误描述转成可操作提示, 避免用户面对裸 JSON 无从下手
        detail = ""
        try:
            body = resp.json()
            detail = body.get("description") or ""
        except Exception:
            detail = resp.text[:200]

        if "chat not found" in detail.lower():
            logger.error(
                "Telegram 通知失败: 找不到该 Chat ID. 请先给机器人发送任意消息, "
                "并确认 chat_id 填写正确 (群组 ID 为负数, 频道可用 @channelusername)."
            )
        elif "unauthorized" in detail.lower() or resp.status_code == 401:
            logger.error("Telegram 通知失败: Bot Token 无效, 请检查配置中的 bot_token.")
        elif "bot was blocked" in detail.lower():
            logger.error("Telegram 通知失败: 该用户已屏蔽机器人, 请先在 Telegram 中解除屏蔽.")
        else:
            logger.warning(f"Telegram 通知发送失败 (HTTP {resp.status_code}): {detail}")
        return False

    def write(self, message):
        """loguru sink 入口: 解析 "LEVEL#BODY" 后转发."""
        message = message.strip()
        if not message:
            return

        level, sep, body = message.partition("#")
        if not sep:
            # 非预期格式: 整条当作正文
            level, body = "info", message

        level = level.lower()
        body = Text.from_markup(body).plain
        if not body.strip():
            return

        prefix = {
            "error": "[错误] ",
            "critical": "[严重] ",
            "warning": "[警告] ",
            "success": "[完成] ",
        }.get(level, "")

        text = f"{prefix}{body}"
        # 超长消息分片发送, 避免 400: message is too long
        for chunk in _split(text, MAX_MESSAGE_LEN):
            # 预警/错误保留提示音, 普通信息静默
            silent = level not in ("error", "critical", "warning")
            self._send(chunk, silent=silent)

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    async def join(self):
        """与其他通知流接口保持一致, 无需等待异步任务."""
        return None


def _split(text: str, size: int):
    """按长度切分, 尽量在换行处断开."""
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text
