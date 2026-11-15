"""AI OCR 提供商抽象基类."""

from abc import ABC, abstractmethod
from typing import Optional


class AIOCRProvider(ABC):
    """AI 验证码识别提供商."""

    name = "base"

    @abstractmethod
    async def recognize(self, image_bytes: bytes, rule: str = None, timeout: int = 10) -> Optional[str]:
        """识别图片中的验证码, 返回原始文本; 失败时返回 None.

        参数:
            image_bytes: 图片二进制数据 (PNG/JPEG)
            rule: 站点级提示词, 用于约束输出格式
            timeout: 请求超时秒数
        """
        raise NotImplementedError
