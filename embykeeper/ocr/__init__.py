"""OCR 模块.

对外保持与旧版 `embykeeper.ocr` 一致的导入接口, 同时新增分层降级的 AI 识别能力.

用法 (兼容旧代码):
    from embykeeper.ocr import OCRService, CharRange
    ocr = await OCRService.get(ocr_name=None, char_range=CharRange.NUMBER)
    text = await ocr.run(image, min_confidence=0.6)
"""

from .common import (
    CharRange,
    allowed_charset,
    build_image_variants,
    clean_captcha_text,
    parse_probability_result,
    validate_captcha,
)
from .factory import get_router
from .local import OCRService
from .providers import AIOCRProvider, SenseNovaProvider
from .router import OCRRouter

__all__ = [
    "CharRange",
    "OCRService",
    "OCRRouter",
    "AIOCRProvider",
    "SenseNovaProvider",
    "get_router",
    "allowed_charset",
    "build_image_variants",
    "clean_captcha_text",
    "parse_probability_result",
    "validate_captcha",
]
