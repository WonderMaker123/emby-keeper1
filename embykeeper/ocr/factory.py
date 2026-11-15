"""OCR 路由的工厂入口, 负责读取全局配置并组装本地 + AI 提供商."""

from typing import Optional, Union

from loguru import logger

from .common import CharRange, allowed_charset
from .providers import SenseNovaProvider
from .router import OCRRouter

logger = logger.bind(scheme="ocr")


def _build_ai_provider(site_name: str = None):
    """根据全局配置构建 AI 提供商; 未启用或未配置密钥时返回 None."""
    from embykeeper.config import config
    from embykeeper.utils import get_proxy_str

    conf = getattr(config, "ocr", None)
    if not conf:
        return None
    if conf.provider == "local":
        return None
    if not conf.ai_api_key:
        logger.warning("已选择 AI 优先, 但未配置 AI API Key, 将使用本地 OCR.")
        return None
    try:
        return SenseNovaProvider(
            api_key=conf.ai_api_key,
            model=conf.ai_model,
            base_url=conf.ai_base_url,
            proxy=get_proxy_str(config.proxy),
        )
    except Exception as e:
        logger.warning(f"AI 提供商初始化失败, 仅使用本地 OCR: {e}")
        return None


def _build_rule(site_name: str, char_range, expected_len) -> str:
    """构造站点级提示词: 站点自定义规则优先, 否则按字符集与长度自动生成."""
    from embykeeper.config import config

    conf = getattr(config, "ocr", None)
    rules = (conf.ai_rules if conf else None) or {}
    if site_name and site_name in rules:
        return rules[site_name]

    charset = allowed_charset(char_range)
    parts = ["识别图片中的验证码, 只输出验证码字符本身, 不要任何解释或标点."]
    if charset:
        if charset.isdigit():
            parts.append("验证码仅包含数字.")
        elif charset.isalpha():
            parts.append("验证码仅包含英文字母.")
        else:
            parts.append("验证码仅包含英文字母与数字.")
    if expected_len:
        from embykeeper.utils import to_iterable

        lengths = to_iterable(expected_len)
        if len(lengths) == 1:
            parts.append(f"验证码为 {lengths[0]} 位.")
    return " ".join(parts)


async def get_router(
    site_name: str = None,
    ocr_name: str = None,
    char_range: Optional[Union[CharRange, str]] = None,
    expected_len=None,
    min_confidence: float = 0.0,
) -> OCRRouter:
    """获取配置好的 OCR 路由实例.

    参数:
        site_name: 站点标识, 用于查找站点级 AI 提示词
        ocr_name: 自定义 ddddocr 模型名, None 表示内置模型
        char_range: 期望的字符集, 用于限定本地识别范围并校验 AI 结果
        expected_len: 期望的验证码长度
        min_confidence: 调用方要求的最低置信度
    """
    from embykeeper.config import config

    conf = getattr(config, "ocr", None)
    provider_mode = conf.provider if conf else "local"
    ai_timeout = conf.ai_timeout if conf else 15
    ai_max_retries = conf.ai_max_retries if conf else 2

    ai_provider = _build_ai_provider(site_name) if provider_mode == "ai" else None
    rule = _build_rule(site_name, char_range, expected_len) if ai_provider else None

    return await OCRRouter.get(
        ocr_name=ocr_name,
        char_range=char_range,
        ai_provider=ai_provider,
        ai_rule=rule,
        expected_len=expected_len,
        ai_max_retries=ai_max_retries,
        ai_timeout=ai_timeout,
    )
