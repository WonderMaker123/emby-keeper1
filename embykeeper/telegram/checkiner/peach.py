import asyncio
import random
from pyrogram.types import Message

from . import BotCheckin
from embykeeper.ocr import CharRange


class PeachCheckin(BotCheckin):
    name = "Peach"
    bot_username = "peach_emby_bot"
    bot_checkin_cmd = "/start"
    bot_captcha_len = 4
    bot_checkin_caption_pat = "请输入验证码"
    # 验证码为 4 位数字+大小写字母, 限定字符集以启用概率模式
    bot_captcha_char_range = CharRange.NUMBER_LLETTER_ULETTER
    # 置信度不足的识别结果不发送给机器人, 直接重试以减少机器人端失败计数.
    # 实测 ddddocr 通用模型对真实验证码置信度普遍在 0.3-0.7 且常常识别错误,
    # 因此阈值设高, 以促使低置信度结果降级到 AI 识别.
    bot_captcha_min_confidence = 0.9

    async def message_handler(self, client, message: Message):
        if message.caption and "欢迎使用" in message.caption and message.reply_markup:
            keys = [k.text for r in message.reply_markup.inline_keyboard for k in r]
            for k in keys:
                if "签到" in k:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    await message.click(k)
                    return
            else:
                self.log.warning(f"签到失败: 账户错误.")
                return await self.fail()
        await super().message_handler(client, message)
