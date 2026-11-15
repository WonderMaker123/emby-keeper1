"""OCR 公共定义: 字符范围、概率解析、图像预处理."""

from enum import IntEnum


class CharRange(IntEnum):
    NUMBER = 0
    LLETTER = 1
    ULETTER = 2
    LLETTER_ULETTER = 3
    NUMBER_LLETTER = 4
    NUMBER_ULETTER = 5
    NUMBER_LLETTER_ULETTER = 6
    NOT_NUMBER_LLETTER_ULETTER = 7


_DIGITS = "0123456789"
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# CharRange 到允许字符集的反查表, 用于校验 AI 返回结果是否落在合法字符集内.
# NOT_NUMBER_LLETTER_ULETTER 为开放集合, 无法用于校验, 故不在此表内.
CHAR_RANGE_CHARSET = {
    CharRange.NUMBER: _DIGITS,
    CharRange.LLETTER: _LOWER,
    CharRange.ULETTER: _UPPER,
    CharRange.LLETTER_ULETTER: _LOWER + _UPPER,
    CharRange.NUMBER_LLETTER: _DIGITS + _LOWER,
    CharRange.NUMBER_ULETTER: _DIGITS + _UPPER,
    CharRange.NUMBER_LLETTER_ULETTER: _DIGITS + _LOWER + _UPPER,
}


def allowed_charset(char_range) -> str:
    """将 CharRange 或自定义字符集字符串转换为可校验的字符集合.

    自定义字符串范围原样返回; 未知范围返回空字符串 (表示不校验).
    """
    if isinstance(char_range, str):
        return char_range
    if char_range is None:
        return ""
    try:
        return CHAR_RANGE_CHARSET.get(CharRange(int(char_range)), "")
    except (ValueError, TypeError):
        return ""


def parse_probability_result(ocr_result) -> tuple:
    """从 ddddocr 概率结果中提取文本与置信度.

    置信度取各字符在候选字符集内相对概率的最小值, 用于筛除不可靠结果.
    注意: set_ranges 仅裁剪返回的字符列, 概率仍是全字符集 softmax 的切片,
    因此需按当前列重新归一化, 否则阈值会随字符范围变化而失真.
    """
    charsets = ocr_result["charsets"]
    text = ""
    confidence = 1.0
    for probs in ocr_result["probability"]:
        total = sum(probs)
        if total <= 0:
            return text, 0.0
        best = probs.index(max(probs))
        confidence = min(confidence, probs[best] / total)
        text += charsets[best]
    return text, confidence


def clean_captcha_text(text: str) -> str:
    """从模型输出中清洗出验证码: 去除空白与标点."""
    if not text:
        return ""
    import string

    return text.translate(str.maketrans("", "", string.punctuation)).replace(" ", "").strip()


def validate_captcha(
    text: str,
    char_range=None,
    expected_len=None,
) -> str:
    """校验 AI 返回的验证码是否可用, 返回清洗后的结果 (不可用时返回空字符串).

    这是防幻觉的最后一道关卡: 只要字符集或长度不符, 就直接弃用该结果并要求重试新图,
    绝不把可疑内容发送给机器人, 避免白白消耗机器人端的尝试次数.
    """
    from typing import Iterable

    captcha = clean_captcha_text(text)
    if not captcha:
        return ""

    charset = allowed_charset(char_range)
    if charset and any(ch not in charset for ch in captcha):
        return ""

    if expected_len:
        from embykeeper.utils import to_iterable

        if len(captcha) not in to_iterable(expected_len):
            return ""

    return captcha


def build_image_variants(image_bytes: bytes):
    """生成用于重识别的图像变体: 小图放大 / 灰度自动对比度."""
    from io import BytesIO

    from PIL import Image, ImageOps

    base = Image.open(BytesIO(image_bytes)).convert("RGB")

    def to_bytes(image):
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    # 小图放大有助于提升模型对细笔画的区分能力, 向上取整保证放大后宽度不小于 200
    if base.width < 200 or base.height < 100:
        scale = max(2, -(-200 // max(base.width, 1)))
        yield to_bytes(base.resize((base.width * scale, base.height * scale), Image.LANCZOS))
    yield to_bytes(ImageOps.autocontrast(base.convert("L")))
