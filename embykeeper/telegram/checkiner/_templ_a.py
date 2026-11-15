import asyncio
import random

from loguru import logger
from pydantic import ValidationError
from pyrogram.types import Message
from pyrogram.errors import MessageIdInvalid
from pyrogram.raw.types.messages import BotCallbackAnswer

from embykeeper.utils import to_iterable

from . import BotCheckin
from ._templ_config import TemplateACheckinConfig

__ignore__ = True


class TemplateACheckin(BotCheckin):
    bot_text_ignore_answer = ["Done"]
    use_button_answer = True
    bot_checkin_cmd = "/start"
    bot_checkin_button = ["签到", "簽到"]
    templ_panel_keywords = None

    async def init(self):
        try:
            self.t_config = TemplateACheckinConfig.model_validate(self.config)
        except ValidationError as e:
            self.log.warning(f"初始化失败: 签到自定义模板 A 的配置错误:\n{e}")
            return False

        self.name = self.t_config.name or self.name
        self.use_button_answer = (
            self.t_config.use_button_answer
            if self.t_config.use_button_answer is not None
            else self.use_button_answer
        )
        self.bot_text_ignore_answer = self.t_config.bot_text_ignore_answer or self.bot_text_ignore_answer
        self.bot_fail_keywords = self.t_config.bot_fail_keywords or self.bot_fail_keywords
        self.bot_success_keywords = self.t_config.bot_success_keywords or self.bot_success_keywords
        self.bot_success_pat = self.t_config.bot_success_pat or self.bot_success_pat
        self.bot_captcha_len = self.t_config.bot_captcha_len or self.bot_captcha_len
        self.bot_text_ignore = self.t_config.bot_text_ignore or self.bot_text_ignore
        self.bot_checkin_caption_pat = self.t_config.bot_checkin_caption_pat or self.bot_checkin_caption_pat
        self.bot_checkin_cmd = self.t_config.bot_checkin_cmd or self.bot_checkin_cmd
        self.bot_checkin_button = self.t_config.bot_checkin_button or self.bot_checkin_button
        self.templ_panel_keywords = self.t_config.templ_panel_keywords or self.templ_panel_keywords
        self.bot_use_captcha = (
            self.t_config.bot_use_captcha
            if self.t_config.bot_use_captcha is not None
            else self.bot_use_captcha
        )

        self.log = logger.bind(scheme="telechecker", name=self.name, username=self.client.me.full_name)
        return True

    async def message_handler(self, client, message: Message):
        text = message.caption or message.text
        if (
            text
            and message.reply_markup
            and (
                (
                    self.templ_panel_keywords
                    and any(keyword in text for keyword in to_iterable(self.templ_panel_keywords))
                )
                or (getattr(message, "is_first_response", False) and not message.edit_date)
            )
        ):
            keys = [k.text for r in message.reply_markup.inline_keyboard for k in r]
            for k in keys:
                if any(btn in k for btn in self.bot_checkin_button):
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    try:
                        answer: BotCallbackAnswer = await message.click(k)
                    except TimeoutError:
                        self.log.debug(f"点击签到按钮无响应, 可能按钮未正确处理点击回复. 一般来说不影响签到.")
                    except MessageIdInvalid:
                        pass
                    else:
                        await self.on_button_answer(answer)
                    return
            else:
                self.log.warning(f"签到失败: 账户错误.")
                return await self.fail()

        if message.text and "请先点击下面加入我们的" in message.text:
            self.log.warning(f"签到失败: 账户错误.")
            return await self.fail()

        await super().message_handler(client, message)

    async def on_button_answer(self, answer: BotCallbackAnswer):
        if self.use_button_answer:
            if not isinstance(answer, BotCallbackAnswer):
                self.log.warning(f"签到失败: 签到按钮指向 URL, 不受支持.")
                return await self.fail()
            if answer.message and not any(ignore in answer.message for ignore in self.bot_text_ignore_answer):
                await self.on_text(Message(id=0, text=answer.message), answer.message)


def use(**kw):
    return type("TemplatedClass", (TemplateACheckin,), kw)
