from typing import List, Optional, Union, Dict, Any, ClassVar, Annotated
from pydantic import (
    BaseModel,
    Field,
    model_validator,
    ValidationError,
    BeforeValidator,
    PlainSerializer,
)
from pydantic.networks import HttpUrl

DEFAULT_TIME_RANGE = "<11:00AM,11:00PM>"
DEFAULT_EMBY_INTERVAL_DAYS = "<7,12>"


class ConfigModel(BaseModel):
    model_config = {"extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def validate_extra_fields(cls, values):
        if not isinstance(values, dict):
            return values
        if cls.model_config.get("extra") == "allow":
            return values
        allowed_fields = set(cls.model_fields.keys())
        extra_fields = set(values.keys()) - allowed_fields
        if extra_fields:
            raise ValueError(
                f"包含未知设置项：{', '.join(extra_fields)}, 允许的设置项: {', '.join(allowed_fields)}"
            )
        return values


def _to_str(v):
    """将数字转为字符串, 保持旧版 UseStr 的宽松语义."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return v


# 使用 Annotated 形式的 v2 校验器, 可直接生成 JSON Schema (旧式 __get_validators__ 不支持).
UseStr = Annotated[str, BeforeValidator(_to_str)]


def _to_http_url(v):
    """缺少协议头时自动补全 https://"""
    if isinstance(v, str) and not v.startswith(("http://", "https://")):
        return f"https://{v}"
    return v


UseHttpUrl = Annotated[
    HttpUrl,
    BeforeValidator(_to_http_url),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]


class ProxyConfig(ConfigModel):
    hostname: Optional[str] = Field(None, title="代理地址", description="代理服务器的主机名或 IP")
    port: Optional[int] = Field(None, gt=0, title="代理端口", description="代理服务器的端口号")
    scheme: Optional[str] = Field(
        None, pattern="^(socks5|http)$", title="代理协议", description="socks5 或 http"
    )
    username: Optional[str] = Field(None, title="代理用户名", description="代理认证用户名, 无需认证可留空")
    password: Optional[str] = Field(None, title="代理密码", description="代理认证密码, 无需认证可留空")


class CheckinerConfig(ConfigModel):
    time_range: Optional[UseStr] = Field(
        DEFAULT_TIME_RANGE,
        title="签到时间段",
        description='每日随机在此区间内执行, 例如 "<8:00AM,10:00PM>" 或 "8:00AM-10:00PM"',
    )
    interval_days: Optional[UseStr] = Field(
        "1", title="签到间隔(天)", description="每隔多少天签到一次, 支持小数如 0.5"
    )
    timeout: Optional[int] = Field(120, gt=0, title="单站超时(秒)", description="单个站点签到的超时时间")
    retries: Optional[int] = Field(4, ge=0, title="重试次数", description="签到失败后的重试次数")
    concurrency: Optional[int] = Field(1, gt=0, title="并发数", description="同时签到的站点数量")
    random_start: Optional[int] = Field(
        60, ge=0, title="启动随机延迟(秒)", description="启动后随机等待的上限, 避免同时发起请求"
    )

    model_config = {"extra": "allow"}

    def get_site_config(self, site: str) -> Dict[str, Any]:
        return getattr(self, site, {})


class NotifierConfig(ConfigModel):
    enabled: Optional[bool] = Field(False, title="启用通知", description="是否开启签到结果通知")
    account: Optional[Union[int, str]] = Field(
        None,
        title="通知账号",
        description="预留字段, 仅 Apprise 配合本地账号时可用; 使用 Telegram 机器人直推时无需填写",
        json_schema_extra={"x-deprecated": True},
    )
    immediately: Optional[bool] = Field(
        False,
        title="即时通知",
        description="预留字段, 当前版本行为固定为「产生关键日志时立即推送」, 无需调整",
        json_schema_extra={"x-deprecated": True},
    )
    once: Optional[bool] = Field(
        False,
        title="仅通知一次",
        description="预留字段, 当前版本未实现, 保持默认即可",
        json_schema_extra={"x-deprecated": True},
    )
    method: Optional[str] = Field(
        "telegram",
        title="通知方式",
        description="telegram = Telegram 机器人直推 (推荐, 只需 Token 和 Chat ID); apprise = 自建 Apprise 服务",
        pattern="^(telegram|apprise)$",
    )
    bot_token: Optional[str] = Field(
        None,
        title="Bot Token",
        description='Telegram 机器人的 Token, 从 @BotFather 获取, 形如 123456789:ABCdef...；通知方式选 telegram 时必填',
    )
    chat_id: Optional[str] = Field(
        None,
        title="Chat ID",
        description="接收通知的会话 ID。可填用户 ID、群组 ID (负数) 或 @channelusername；先给机器人发送一条消息即可收到",
    )
    apprise_uri: Optional[str] = Field(
        None,
        title="Apprise 地址",
        description="通知推送地址, 例如 tgram://bot_token/chat_id；仅当通知方式为 apprise 时使用",
    )


class SiteConfig(ConfigModel):
    checkiner: Optional[List[str]] = Field(
        None, title="启用的站点", description="要签到的站点列表, 留空表示全部启用"
    )


class OCRConfig(ConfigModel):
    """验证码识别设置.

    默认 AI 优先: 优先使用 AI 识别, AI 不可用或校验不通过时降级到本地 ddddocr.
    """

    provider: Optional[str] = Field(
        "ai",
        title="识别模式",
        description="ai = AI 优先(推荐); local = 仅用本地 ddddocr",
        pattern="^(ai|local)$",
    )
    ai_api_key: Optional[str] = Field(None, title="AI API Key", description="AI 服务的鉴权密钥")
    ai_model: Optional[str] = Field(
        "sensenova-6.8-flash-lite",
        title="AI 模型",
        description="AI 识图使用的模型 ID, 必须支持图像输入",
    )
    ai_base_url: Optional[str] = Field(
        "https://token.sensenova.cn/v1",
        title="AI 接口地址",
        description="OpenAI 兼容接口的基地址; 平台 Key 用 token.sensenova.cn/v1",
    )
    ai_timeout: Optional[int] = Field(15, gt=0, title="AI 超时(秒)", description="AI 请求超时秒数")
    ai_max_retries: Optional[int] = Field(2, ge=0, title="AI 重试次数", description="AI 识别失败后的重试次数")
    ai_rules: Optional[Dict[str, str]] = Field(
        None,
        title="站点提示词",
        description='按站点覆盖 AI 提示词, 例如 { Peach = "只输出4位英数字符" }',
    )


class MediaServerBaseConfig(ConfigModel):
    time_range: Optional[UseStr] = Field(
        DEFAULT_TIME_RANGE,
        title="保活时间段",
        description='每日随机在此区间内播放, 例如 "<8:00AM,10:00PM>"',
    )
    interval_days: Optional[UseStr] = Field(
        DEFAULT_EMBY_INTERVAL_DAYS, title="保活间隔(天)", description="每隔多少天保活一次"
    )
    concurrency: Optional[int] = Field(1, gt=0, title="并发数", description="同时保活的账号数量")
    retries: Optional[int] = Field(5, ge=0, title="重试次数", description="保活失败后的重试次数")


class EmbyAccount(ConfigModel):
    url: UseHttpUrl = Field(title="服务器地址", description="Emby 服务器地址, 可省略 https:// 前缀")
    username: str = Field(title="用户名", description="Emby 账号用户名")
    password: str = Field(title="密码", description="Emby 账号密码")
    name: Optional[str] = Field(None, title="账号备注", description="自定义备注名, 仅用于日志区分")
    time: Optional[Union[int, List[int]]] = Field(
        [300, 600], title="播放时长(秒)", description="每次保活的播放时长范围, 例如 [300, 600]"
    )
    useragent: Optional[str] = Field(None, title="User-Agent", description="自定义请求 UA, 留空使用默认值")
    client: Optional[str] = Field(None, title="客户端名称", description="模拟的客户端名称")
    client_version: Optional[str] = Field(None, title="客户端版本", description="模拟的客户端版本号")
    device: Optional[str] = Field(None, title="设备名称", description="模拟的设备名称")
    device_id: Optional[str] = Field(None, title="设备 ID", description="模拟的设备唯一标识")
    allow_multiple: Optional[bool] = Field(
        True, title="允许并发播放", description="是否允许同时进行多个播放会话"
    )
    allow_stream: Optional[bool] = Field(
        False, title="使用流式播放", description="开启后以流式方式上报播放进度"
    )
    use_proxy: Optional[bool] = Field(True, title="使用代理", description="该账号是否走全局代理")
    play_id: Optional[str] = Field(None, title="播放媒体 ID", description="指定播放的媒体项 ID")
    enabled: Optional[bool] = Field(True, title="启用账号", description="是否启用该账号")

    # 站点单独配置
    interval_days: Optional[Union[int, str]] = Field(
        None, title="单独保活间隔(天)", description="覆盖全局间隔; 填写后该账号独立调度"
    )
    time_range: Optional[str] = Field(
        None, title="单独保活时间段", description="覆盖全局时间段; 填写后该账号独立调度"
    )

    # 向后兼容字段
    interval: Optional[Union[int, str]] = Field(None, title="(兼容)间隔", description="旧版字段, 请改用 interval_days")
    watchtime: Optional[str] = Field(None, title="(兼容)观看时间段", description="旧版字段, 请改用 time_range")
    hide: Optional[bool] = Field(None, title="(兼容)隐藏", description="旧版字段")
    ua: Optional[str] = Field(None, title="(兼容)UA", description="旧版字段, 请改用 useragent")
    jellyfin: Optional[bool] = Field(None, title="(兼容)Jellyfin", description="旧版字段")
    continuous: Optional[bool] = Field(
        False, title="连续播放", description="是否循环播放直到达到时长"
    )


class EmbyConfig(MediaServerBaseConfig):
    account: Optional[List[EmbyAccount]] = Field(
        [], title="Emby 账号", description="需要保活的 Emby 账号列表"
    )


class SubsonicAccount(ConfigModel):
    url: UseHttpUrl = Field(title="服务器地址", description="Subsonic 服务器地址")
    username: str = Field(title="用户名", description="Subsonic 账号用户名")
    password: str = Field(title="密码", description="Subsonic 账号密码")
    name: Optional[str] = Field(None, title="账号备注", description="自定义备注名, 仅用于日志区分")
    time: Optional[Union[int, List[int]]] = Field(
        None, title="听歌时长(秒)", description="每次保活的听歌时长"
    )
    useragent: Optional[str] = Field(None, title="User-Agent", description="自定义请求 UA")
    client: Optional[str] = Field(None, title="客户端名称", description="模拟的客户端名称")
    client_version: Optional[str] = Field(None, title="客户端版本", description="模拟的客户端版本号")
    use_proxy: Optional[bool] = Field(True, title="使用代理", description="该账号是否走全局代理")
    enabled: Optional[bool] = Field(True, title="启用账号", description="是否启用该账号")

    # 站点单独配置
    interval_days: Optional[Union[int, str]] = Field(
        None, title="单独保活间隔(天)", description="覆盖全局间隔; 填写后该账号独立调度"
    )
    time_range: Optional[str] = Field(
        None, title="单独保活时间段", description="覆盖全局时间段; 填写后该账号独立调度"
    )

    # 向后兼容字段
    ua: Optional[str] = Field(None, title="(兼容)UA", description="旧版字段, 请改用 useragent")
    version: Optional[str] = Field(None, title="(兼容)版本", description="旧版字段, 请改用 client_version")


class SubsonicConfig(MediaServerBaseConfig):
    account: Optional[List[SubsonicAccount]] = Field(
        [], title="Subsonic 账号", description="需要保活的 Subsonic 账号列表"
    )


class TelegramAccount(ConfigModel):
    phone: str = Field(title="手机号", description="Telegram 账号手机号, 含国家码, 例如 +8613800138000")
    name: Optional[str] = Field(
        None, title="备注名称", description="便于区分多个账号, 仅用于界面展示, 可留空"
    )

    @model_validator(mode="before")
    @classmethod
    def clean_phone(cls, values):
        if isinstance(values, dict) and "phone" in values:
            values["phone"] = values["phone"].replace(" ", "")
        return values

    checkiner: Optional[bool] = Field(True, title="启用签到", description="该账号是否参与站点签到")
    api_id: Optional[str] = Field(None, title="API ID", description="Telegram API ID, 留空使用内置定义")
    api_hash: Optional[str] = Field(None, title="API Hash", description="Telegram API Hash, 留空使用内置定义")
    session: Optional[str] = Field(None, title="会话", description="Telegram 已登录会话字符串")
    enabled: Optional[bool] = Field(True, title="启用账号", description="是否启用该账号")

    # 账号单独配置
    site: Optional[SiteConfig] = Field(None, title="单独站点配置", description="覆盖全局的启用站点列表")
    checkiner_config: Optional[CheckinerConfig] = Field(
        None, title="单独签到配置", description="覆盖全局的签到时间/重试等设置"
    )

    def get_config_key(self):
        import hashlib

        unique_str = f"{self.phone}:{self.api_id or ''}:{self.api_hash or ''}"
        hash_value = hashlib.sha256(unique_str.encode()).hexdigest()[:8]
        return f"{self.phone}/{hash_value}"

    @staticmethod
    def get_phone_masked(phone: str):
        phone_len = len(phone)
        visible_part = max(1, phone_len // 3)
        return phone[:visible_part] + "*" * (phone_len - visible_part * 2) + phone[-visible_part:]


class TelegramConfig(ConfigModel):
    account: Optional[List[TelegramAccount]] = Field(
        [], title="Telegram 账号", description="用于签到的 Telegram 账号列表"
    )
    use_proxy: Optional[bool] = Field(True, title="使用代理", description="Telegram 是否走全局代理")


class BotConfig(ConfigModel):
    token: str = Field(title="Bot Token", description="调试用 Telegram Bot Token")


class Config(ConfigModel):
    alias_map: ClassVar[Dict[str, str]] = {
        "emby.time_range": "watchtime",
        "emby.concurrency": "watch_concurrent",
        "subsonic.time_range": "listentime",
        "subsonic.concurrency": "listen_concurrent",
        "checkiner.time_range": "time",
        "checkiner.timeout": "timeout",
        "checkiner.retries": "retries",
        "checkiner.concurrency": "concurrent",
        "checkiner.random_start": "random",
        "emby.interval_days": "interval",
        "subsonic.interval_days": "interval",
        "site": "service",
    }

    mongodb: Optional[str] = Field(
        None,
        title="MongoDB 连接串",
        description="集中存储账号与配置, 例如 mongodb://user:pass@host:27017",
    )
    basedir: Optional[str] = Field(
        None, title="工作目录", description="存放配置、会话、日志的目录, 留空使用默认路径"
    )
    nofail: Optional[bool] = Field(
        True, title="忽略任务异常", description="单个任务出错时是否继续运行其他任务"
    )
    noexit: Optional[bool] = Field(
        False, title="常驻等待配置", description="没有账号时也保持运行, 等待新配置"
    )
    debug_cron: Optional[bool] = Field(
        False, title="调试调度", description="用较快的时间参数模拟调度, 仅用于调试"
    )
    proxy: Optional[ProxyConfig] = Field(None, title="代理", description="全局网络代理设置")
    ocr: Optional[OCRConfig] = Field(OCRConfig(), title="验证码识别", description="本地与 AI 验证码识别设置")
    emby: Optional[EmbyConfig] = Field(EmbyConfig(), title="Emby 保活", description="Emby 服务器保活设置")
    subsonic: Optional[SubsonicConfig] = Field(
        SubsonicConfig(), title="Subsonic 保活", description="Subsonic 服务器保活设置"
    )
    checkiner: Optional[CheckinerConfig] = Field(
        CheckinerConfig(), title="站点签到", description="Telegram 站点签到设置"
    )
    telegram: Optional[TelegramConfig] = Field(
        TelegramConfig(), title="Telegram 账号", description="签到用的 Telegram 账号"
    )
    notifier: Optional[NotifierConfig] = Field(
        NotifierConfig(), title="通知", description="签到结果通知设置"
    )
    site: Optional[SiteConfig] = Field(None, title="站点范围", description="全局启用的签到站点列表")

    # 向后兼容字段
    time: Optional[str] = Field(None, title="(兼容)签到时间段", description="旧版字段, 请改用 checkiner.time_range")
    watchtime: Optional[str] = Field(None, title="(兼容)观看时间段", description="旧版字段, 请改用 emby.time_range")
    listentime: Optional[str] = Field(None, title="(兼容)听歌时间段", description="旧版字段, 请改用 subsonic.time_range")
    interval: Optional[Union[int, str]] = Field(None, title="(兼容)间隔(天)", description="旧版字段, 请改用各模块 interval_days")
    timeout: Optional[int] = Field(None, title="(兼容)超时", description="旧版字段, 请改用 checkiner.timeout")
    retries: Optional[int] = Field(None, title="(兼容)重试", description="旧版字段, 请改用 checkiner.retries")
    concurrent: Optional[int] = Field(None, title="(兼容)并发", description="旧版字段, 请改用 checkiner.concurrency")
    watch_concurrent: Optional[int] = Field(None, title="(兼容)观看并发", description="旧版字段")
    listen_concurrent: Optional[int] = Field(None, title="(兼容)听歌并发", description="旧版字段")
    random: Optional[int] = Field(None, title="(兼容)随机延迟", description="旧版字段, 请改用 checkiner.random_start")
    notify_immediately: Optional[bool] = Field(None, title="(兼容)即时通知", description="旧版字段, 请改用 notifier.immediately")
    service: Optional[SiteConfig] = Field(None, title="(兼容)站点范围", description="旧版字段, 请改用 site")

    # 调试字段
    bot: Optional[BotConfig] = Field(None, title="调试 Bot", description="调试用的 Bot 配置")

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        for service in ["emby", "subsonic", "telegram"]:
            if service in values and isinstance(values[service], list):
                if service == "telegram":
                    for account in values[service]:
                        if "checkin" in account:
                            account["checkiner"] = account.pop("checkin")
                if service == "emby":
                    # Convert emby account fields
                    for account in values[service]:
                        if "ua" in account:
                            account["useragent"] = account.pop("ua")
                if service == "subsonic":
                    # Convert subsonic account fields
                    for account in values[service]:
                        if "ua" in account:
                            account["useragent"] = account.pop("ua")
                        if "version" in account:
                            account["client_version"] = account.pop("version")
                values[service] = {"account": values[service]}

        if "notifier" in values:
            notifier_value = values["notifier"]
            if isinstance(notifier_value, str):
                values["notifier"] = {
                    "enabled": True,
                    "account": notifier_value,
                }
            elif isinstance(notifier_value, bool):
                values["notifier"] = {
                    "enabled": notifier_value,
                }
            elif isinstance(notifier_value, int):
                values["notifier"] = {
                    "enabled": notifier_value > 0,
                    "account": notifier_value,
                }

        for new_field, old_field in cls.alias_map.items():
            if old_field in values and values[old_field] is not None:
                parts = new_field.split(".")
                target = values
                for part in parts[:-1]:
                    target.setdefault(part, {})
                    target = target[part]
                target[parts[-1]] = values[old_field]

        return values


def format_errors(e: ValidationError) -> str:
    """自定义错误信息格式化"""

    error_translations = {
        "Input should be a valid boolean": "输入应为布尔值 (true/false)",
        "Input should be a valid integer": "输入应为有效的整数",
        "Input should be a valid string": "输入应为有效的字符串, 用英文双引号包裹",
        "Input should be a valid list": "输入应为有效的列表, 用[]符号包裹",
        "Input should be a valid URL": "输入应为有效的URL地址",
        "Field required": "必填字段",
        "Value error": "配置验证错误",
        "Input should match pattern": "输入格式不匹配要求",
        "Value is not a valid dict": "输入应为有效的字典格式",
    }

    reverse_aliases = {}
    for new_field, old_field in Config.alias_map.items():
        if old_field not in reverse_aliases:
            reverse_aliases[old_field] = []
        reverse_aliases[old_field].append(new_field)

    error_groups = {}
    error_messages = ["配置文件错误, 请检查配置文件:"]

    for error in e.errors():
        location = list(error["loc"])
        msg = error["msg"]

        # 翻译错误消息
        for eng, chn in error_translations.items():
            if callable(chn):
                msg = msg.replace(eng, chn(error["loc"]))
            else:
                msg = msg.replace(eng, chn)

        # 如果是根级别的错误, 直接添加错误信息
        if not location:
            error_messages.append(f"  {msg}")
            continue

        loc_str = " -> ".join(str(loc) for loc in location)

        error_key = (() if len(location) <= 1 else tuple(location[1:])) + (msg,)

        # 检查是否有相关的别名字段
        if location[0] in reverse_aliases:
            for new_field in reverse_aliases[location[0]]:
                new_loc = new_field.split(".")
                if len(location) > 1:
                    new_loc.extend(location[1:])
                new_loc_str = " -> ".join(new_loc)
                group_key = f"  {new_loc_str}\n  (旧版本为: {loc_str})"
                error_groups[error_key] = (group_key, msg)
        else:
            error_groups[error_key] = (f"  {loc_str}", msg)

    # 添加分组后的错误消息
    for _, (location, msg) in error_groups.items():
        error_messages.append(f"{location}:")
        error_messages.append(f"    {msg}")

    error_messages.append("详细说明请访问: https://dotracel.github.io/emby-keeper0/guide/配置文件")
    return "\n".join(error_messages)


if __name__ == "__main__":
    import sys
    import tomli

    if len(sys.argv) < 2:
        print("Usage: python schema.py <config.toml>")
        sys.exit(1)

    try:
        with open(sys.argv[1], "rb") as f:
            config_dict = tomli.load(f)
        config = Config(**config_dict)
        print(config.model_dump_json(indent=2))
    except FileNotFoundError:
        print(f"错误: 配置文件 '{sys.argv[1]}' 未找到")
        sys.exit(1)
    except tomli.TOMLDecodeError as e:
        print(f"错误: TOML格式无效 - {e}")
        sys.exit(1)
    except ValidationError as e:
        print(format_errors(e))
        sys.exit(1)
