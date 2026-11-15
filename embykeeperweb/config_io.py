"""配置加载工具 (Web 控制台专用).

单独成模块的原因: 原实现把 load_config_for_web 放在 app.py 中, 而 app.py 又
导入 api.py 蓝图; api.py 若反向从 app.py 取该函数, 就形成循环导入, 导入顺序
稍微变化就会 ImportError. 放在这里让依赖方向单向化:
    config_io -> (schema)            无 Web 依赖
    app.py / api.py -> config_io     单向依赖
"""

import base64
import binascii
import re
from pathlib import Path

from loguru import logger

logger = logger.bind(scheme="configio", nonotify=True)


def load_config_for_web(ek_config, basedir, raw_config=""):
    """为 Web 控制台加载配置, 用于展示与编辑.

    参数:
        ek_config: 全局配置对象 (embykeeper.config.config), 加载成功后会同步.
        basedir:   数据目录, 用于定位 config.toml.
        raw_config: base64 编码的 TOML 文本 (来自 EK_CONFIG 环境变量);
                    非空时优先使用, 否则读取 basedir/config.toml.

    加载失败不抛错, 返回 None 以便 Web 界面仍可打开供用户修正.
    """
    try:
        try:
            import tomli as tomllib
        except ImportError:
            import tomllib
    except ImportError:
        logger.error("缺少 TOML 解析库, 无法加载配置")
        return None

    data = None
    try:
        if raw_config:
            # EK_CONFIG 可能带换行, 先去掉空白再解码
            compact = re.sub(r"\s+", "", raw_config)
            data = tomllib.loads(base64.b64decode(compact.encode()).decode())
        else:
            conf_path = Path(basedir) / "config.toml"
            if conf_path.is_file():
                with open(conf_path, "rb") as f:
                    data = tomllib.load(f)
    except (binascii.Error, ValueError, OSError) as e:
        logger.error(f"配置文件解析失败: {e.__class__.__name__}: {e}")
        return None

    if data is None:
        return None

    from embykeeper.schema import Config

    try:
        conf = Config.model_validate(data)
    except Exception as e:
        logger.error(f"配置校验失败: {e}")
        return None

    # 同步到全局配置对象, 供其他接口与业务读取
    ek_config.basedir = Path(basedir)
    ek_config.set(conf)
    return conf
