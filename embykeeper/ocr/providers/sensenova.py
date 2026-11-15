"""SenseNova 验证码识别提供商 (OpenAI 兼容接口)."""

import base64
from typing import Optional

import httpx
from loguru import logger

from ..common import validate_captcha
from .base import AIOCRProvider

logger = logger.bind(scheme="ocr")

DEFAULT_BASE_URL = "https://api.sensenova.cn/compatible-mode/v2"
# 验证码只有几个字符, 但推理类模型会先输出思维链 (reasoning_tokens),
# 若 max_tokens 过小会被推理过程吃满导致 content 为空 (实测 32 必然失败),
# 因此保留较大余量; 验证码场景总消耗仍然很低.
MAX_TOKENS = 512
# 压缩长边, 兼顾识别率与 token 成本
MAX_SIDE = 512


def _shrink_image(image_bytes: bytes) -> bytes:
    """将图片压缩到长边不超过 MAX_SIDE, 降低 token 消耗与延迟."""
    from io import BytesIO

    from PIL import Image

    try:
        image = Image.open(BytesIO(image_bytes))
    except Exception:
        return image_bytes
    if max(image.size) <= MAX_SIDE:
        return image_bytes
    image = image.convert("RGB")
    ratio = MAX_SIDE / max(image.size)
    image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class SenseNovaProvider(AIOCRProvider):
    """商汤日日新 SenseNova 视觉模型.

    使用 OpenAI 兼容模式:
        POST {base_url}/chat/completions
        Authorization: Bearer {api_key}
    图片以 image_url + data URL (base64) 形式传入, 无需先上传文件.
    """

    name = "sensenova"

    def __init__(
        self,
        api_key: str,
        model: str = "SenseNova-V6-5-Turbo",
        base_url: str = DEFAULT_BASE_URL,
        proxy: str = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.proxy = proxy

    def _build_payload(self, image_bytes: bytes, rule: str) -> dict:
        b64 = base64.b64encode(_shrink_image(image_bytes)).decode()
        prompt = rule or "识别图片中的验证码, 只输出验证码字符本身, 不要任何解释或标点."
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": MAX_TOKENS,
            # 低温度减少随机性与幻觉
            "temperature": 0.1,
            "stream": False,
        }

    async def recognize(self, image_bytes: bytes, rule: str = None, timeout: int = 10) -> Optional[str]:
        payload = self._build_payload(image_bytes, rule)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                proxy=self.proxy, timeout=timeout, follow_redirects=True
            ) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                if resp.status_code != 200:
                    logger.warning(f"AI 识别请求失败 ({resp.status_code}): {resp.text[:200]}")
                    return None
                data = resp.json()
                message = data["choices"][0]["message"]
                content = message.get("content")
                # 部分模型把 content 返回为内容块数组
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                if not content:
                    # 推理类模型在 max_tokens 不足时 content 可能为空, 仅回退读取思维链中的候选结果,
                    # 交由上层字符集/长度校验决定是否可用
                    content = message.get("reasoning") or ""
                    if content:
                        logger.debug("AI 返回 content 为空, 回退使用 reasoning 字段内容.")
                return content
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            logger.warning(f"AI 识别失败 ({e.__class__.__name__}): {e}")
            return None
