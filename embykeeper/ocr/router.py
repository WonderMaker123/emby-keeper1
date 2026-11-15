"""OCR 路由层: 本地优先, 置信度不足时降级到 AI."""

import asyncio
from io import BytesIO
from typing import Optional, Union

from loguru import logger

from ..utils import get_proxy_str
from .common import CharRange, clean_captcha_text, validate_captcha
from .local import OCRService

logger = logger.bind(scheme="ocr")


class OCRRouter:
    """AI 优先的 OCR 路由.

    决策流程:
        1. 优先调用 AI 识别 (准确率高);
        2. AI 结果需通过字符集与长度校验, 否则视为幻觉丢弃;
        3. AI 不可用 (未配置/超时/异常/校验不通过) 时降级到本地 ddddocr;
        4. 两级都不可靠时返回低置信度结果, 交由上层重试机制处理.
    """

    _pool = {}
    _pool_lock = asyncio.Lock()

    @classmethod
    async def get(
        cls,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
        ai_provider=None,
        ai_rule: str = None,
        expected_len=None,
        ai_max_retries: int = 2,
        ai_timeout: int = 15,
    ):
        """获取路由器实例. 同一 (模型, 字符集) 共用本地服务, AI 配置随实例携带."""
        key = (ocr_name, char_range, ai_rule, str(expected_len))
        async with cls._pool_lock:
            if key in cls._pool:
                return cls._pool[key]
            instance = cls(
                ocr_name=ocr_name,
                char_range=char_range,
                ai_provider=ai_provider,
                ai_rule=ai_rule,
                expected_len=expected_len,
                ai_max_retries=ai_max_retries,
                ai_timeout=ai_timeout,
            )
            cls._pool[key] = instance
            return instance

    def __init__(
        self,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
        ai_provider=None,
        ai_rule: str = None,
        expected_len=None,
        ai_max_retries: int = 2,
        ai_timeout: int = 15,
    ):
        self.ocr_name = ocr_name
        self.char_range = char_range
        self.ai_provider = ai_provider
        self.ai_rule = ai_rule
        self.expected_len = expected_len
        self.ai_max_retries = ai_max_retries
        self.ai_timeout = ai_timeout
        self._local = OCRService(ocr_name, char_range)

    async def start(self):
        await self._local.start()

    async def stop(self, force: bool = False):
        await self._local.stop(force=force)

    async def recognize(
        self,
        image_bytes: BytesIO,
        gif: bool = False,
        timeout: int = 60,
        min_confidence: float = 0.0,
    ):
        """识别验证码, 返回 (文本, 置信度, 来源).

        策略为 AI 优先: 先调 AI, 失败或校验不通过时降级到本地 ddddocr.
        min_confidence: 本地结果需要达到的最低置信度, 低于该值视为不可用.
        返回来源: "ai" | "local" | "local_low".
        """
        raw = image_bytes.getvalue() if hasattr(image_bytes, "getvalue") else image_bytes

        # 1. AI 优先
        if self.ai_provider:
            for attempt in range(max(1, self.ai_max_retries)):
                try:
                    ai_text = await self.ai_provider.recognize(
                        raw, rule=self.ai_rule, timeout=self.ai_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning("AI OCR 超时, 降级到本地识别.")
                    break
                except Exception as e:
                    logger.warning(f"AI OCR 异常, 降级到本地识别: {e.__class__.__name__}: {e}")
                    break

                captcha = validate_captcha(ai_text, self.char_range, self.expected_len)
                if captcha:
                    logger.debug(f'AI OCR 识别结果 "{captcha}".')
                    return captcha, 1.0, "ai"
                logger.debug(f'AI 返回 "{ai_text}" 未通过校验 (字符集/长度), 将重试.')
        else:
            logger.debug("未启用 AI 提供商, 直接使用本地 OCR.")

        # 2. 本地兜底 (阈值同时用于触发子进程内的变体重识别)
        try:
            text, confidence = await self._local.recognize(
                raw, gif=gif, timeout=timeout, min_confidence=min_confidence
            )
        except asyncio.TimeoutError:
            logger.warning("本地 OCR 超时.")
            return "", 0.0, "local_low"

        local_text = clean_captcha_text(text)
        if local_text and confidence >= min_confidence:
            return local_text, confidence, "local"

        # 3. 本地结果也不可靠, 返回给上层重试机制处理
        return local_text, confidence, "local_low"

    async def run(
        self,
        image_data: BytesIO,
        timeout: int = 60,
        gif: bool = False,
        min_confidence: float = 0.0,
    ) -> str:
        """兼容旧接口: 返回空字符串表示需要重试."""
        text, confidence, source = await self.recognize(
            image_data, gif=gif, timeout=timeout, min_confidence=min_confidence
        )
        if not text:
            return ""
        if confidence < min_confidence:
            logger.debug(
                f'OCR 置信度不足 ({confidence:.3f} < {min_confidence:.3f}), 识别结果 "{text}" 将被丢弃.'
            )
            return ""
        logger.debug(f'OCR 识别结果 "{text}" (置信度 {confidence:.3f}, 来源 {source}).')
        return text

    def subscribe(self):
        self._local.subscribe()

    def unsubscribe(self):
        self._local.unsubscribe()

    def __enter__(self):
        self.subscribe()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unsubscribe()
        return False
