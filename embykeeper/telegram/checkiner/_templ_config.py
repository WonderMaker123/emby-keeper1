"""模板 A 站点的配置模型.

单独成文件的原因:
    _templ_a.py 依赖 pyrogram (客户端/消息类型), 而 Web 控制台只需要读取
    这个模型来生成表单. 若直接从 _templ_a 导入, 会连带引入整个 Telegram 栈,
    在无 pyrogram 的环境 (或 web 轻量场景) 下会直接失败.

    这里只依赖 pydantic, 两边共用同一份定义, 避免字段漂移.
"""

from typing import List, Optional, Union

from pydantic import BaseModel, Field


class TemplateACheckinConfig(BaseModel):
    """自定义模板 A 站点参数."""

    name: Optional[str] = Field(
        default=None,
        title="站点显示名",
        description="签到日志与站点列表中显示的站点名称, 例如「我的小站」; 留空则显示机器人用户名",
    )
    bot_checkin_cmd: Optional[str] = Field(
        default=None,
        title="签到命令",
        description="发送给机器人的命令, 例如 /start 或 /checkin; 留空使用默认 /start",
    )
    bot_checkin_button: Union[str, List[str]] = Field(
        default=None,
        title="签到按钮文本",
        description="面板上签到按钮包含的文字, 例如 签到; 可填多个, 任一命中即可",
    )
    bot_use_captcha: Optional[bool] = Field(
        default=None,
        title="自动识别验证码",
        description="机器人返回图片验证码时是否自动识别; 建议开启",
    )
    bot_captcha_len: Optional[int] = Field(
        default=None,
        title="验证码长度",
        description="验证码字符数; 不确定可留空, 留空时由识别器自行判断",
    )
    bot_success_keywords: Union[str, List[str]] = Field(
        default=None,
        title="成功关键词",
        description="回复中包含这些词时视为签到成功; 留空使用内置关键词表",
    )
    bot_fail_keywords: Union[str, List[str]] = Field(
        default=None,
        title="失败关键词",
        description="回复中包含这些词时视为签到失败并重试; 留空使用内置关键词表",
    )
    bot_text_ignore: Union[str, List[str]] = Field(
        default=None,
        title="忽略的文本",
        description="包含这些词的消息直接跳过, 例如广告消息; 留空不限制",
    )
    bot_text_ignore_answer: Union[str, List[str]] = Field(
        default=None,
        title="忽略的按钮回复",
        description="点击按钮后的回复中若包含这些词则跳过, 例如 Done",
    )
    bot_success_pat: Optional[str] = Field(
        default=None,
        title="成功信息正则",
        description="从成功消息中提取数字等信息的正则表达式; 一般无需填写",
    )
    bot_checkin_caption_pat: Optional[str] = Field(
        default=None,
        title="验证码图片说明正则",
        description="当机器人返回图片时, 仅当图片说明匹配该正则才当作验证码; 留空不限制",
    )
    templ_panel_keywords: Union[str, List[str]] = Field(
        default=None,
        title="面板关键词",
        description="只有面板消息包含这些词时才尝试点击签到按钮; 留空则用默认面板识别",
    )
    use_button_answer: Optional[bool] = Field(
        default=None,
        title="解析按钮回复",
        description="点击签到按钮后, 是否继续解析按钮返回的内容; 默认开启",
    )
