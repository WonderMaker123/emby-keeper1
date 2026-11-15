# 开发指南

面向需要修改本项目的开发者。架构背景见 [架构说明](../ARCHITECTURE.md)，
AI 助手约定见 [AGENTS.md](../../AGENTS.md)。

---

## 1. 环境准备

### 1.1 后端

```bash
git clone https://github.com/WonderMaker123/emby-keeper1.git
cd emby-keeper1

python -m venv venv
# Linux / macOS
. venv/bin/activate
# Windows
venv\Scripts\activate

pip install -e .
```

> **Windows 注意**：`ddddocrfix`、`pyrogram` 依赖 POSIX 模块（`termios`、`fcntl`），
> 在 Windows 上无法安装。建议 Windows 上只做代码编辑与静态检查，功能验证走 Docker。

### 1.2 前端

```bash
cd frontend
npm install
```

需要 Node 18+。

## 2. 本地运行

### 2.1 只跑控制台（改前端时最常用）

```bash
# 终端 1：控制台
EK_BASEDIR=./data EK_WEBPASS=admin123 python -m embykeeperweb.app run

# 终端 2：前端开发服务器（带热更新，API 自动代理到 1818）
cd frontend && npm run dev
```

访问 `http://127.0.0.1:5173`。改动 `.vue` 文件即时生效。

### 2.2 完整运行（控制台 + 业务）

需要 Linux/macOS 或 Docker：

```bash
# 准备一份配置
mkdir -p data
cp config.example.toml data/config.toml

# 业务进程
EK_BASEDIR=./data embykeeper --basedir ./data

# 另一个终端：控制台
EK_BASEDIR=./data EK_WEBPASS=admin123 python -m embykeeperweb.app run
```

业务进程会监听 `data/config.toml`，控制台保存后自动重载。

### 2.3 用 Docker 验证完整链路

```bash
docker build -t embykeeper:dev .
docker run --rm -it --net host \
  -e EK_WEBPASS=admin123 \
  -v $(pwd)/data:/app/data \
  embykeeper:dev
```

## 3. 代码约定

### 3.1 Python

- 行宽 110（见 `pyproject.toml` 的 `[tool.black]`）
- 注释与日志用中文，标识符用英文
- 注释解释**为什么**，而不是复述代码在做什么
- 关键决策处写清楚「曾经踩过什么坑」，避免后人改回去

### 3.2 前端

- Vue 3 `<script setup>` 语法
- 样式集中在 `src/style.css`，组件内不写 `<style scoped>`（日志页除外）
- 命名用完整单词，不用缩写：`accounts` 而非 `accs`
- 组件只接收结构化值，**配置表达式转换一律走 `lib/friendly.js`**

### 3.3 提交信息

```
<type>(<scope>): <subject>

type:  feat | fix | refactor | docs | build | chore
scope: cli | config | web | frontend | checkiner | ocr | notify | docker
```

示例：

```
fix(config): read config from basedir instead of cwd
feat(web): add friendly time range picker
refactor(app): drop legacy pty/socketio embedded mode
```

## 4. 测试

### 4.1 提交前必做

```bash
# Python 语法检查
python -m py_compile $(git ls-files '*.py')

# 前端构建（会暴露模板语法错误、未定义变量）
cd frontend && npm run build

# 启动脚本语法
bash -n scripts/docker-entrypoint.sh
```

### 4.2 友好值转换的回归测试

`lib/friendly.js` 是纯函数，最容易写测试。保存为 `frontend/test-friendly.mjs`：

```js
import {
  parseTimeRange, formatTimeRange,
  parseInterval, formatInterval,
  parseDuration, formatDuration,
  parseSiteTokens, composeSiteTokens,
} from "./src/lib/friendly.js";

let fail = 0;
const eq = (got, want, msg) => {
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    fail++;
    console.log("FAIL", msg, "\n  got ", JSON.stringify(got), "\n  want", JSON.stringify(want));
  } else {
    console.log("ok  ", msg);
  }
};

// 时间
eq(parseTimeRange("<11:00AM,11:00PM>"), { start: "11:00", end: "23:00" }, "解析 12 小时制");
eq(parseTimeRange("<11:00,23:00>"), { start: "11:00", end: "23:00" }, "解析 24 小时制");
eq(formatTimeRange("08:00", "08:00"), "08:00", "单时刻退化");

// 间隔
eq(parseInterval("<7,12>").mode, "range", "区间模式");
eq(formatInterval({ mode: "range", min: 7, max: 12 }), "<7,12>", "组装区间");
eq(formatInterval({ mode: "range", min: 5, max: 5 }), "5", "区间相等退化");

// 时长
eq(parseDuration([300, 600]), { minMinutes: 5, maxMinutes: 10 }, "时长区间");
eq(formatDuration({ minMinutes: 5, maxMinutes: 10 }), [300, 600], "组装时长");

// 站点：真实配置的往返等价
const real = ["-all", "-sgk", "templ_a<@A>", "peach"];
const model = parseSiteTokens(real);
eq(model.picked, ["peach"], "解析出手动站点");
eq(model.templates, ["templ_a<@A>"], "解析出自定义站点");
eq(composeSiteTokens(model), ["peach", "templ_a<@A>"], "组装为最简形式");

// 手动模式空选：必须写成 -all，否则会被业务当成「默认站点」
eq(
  composeSiteTokens({ mode: "manual", picked: [], templates: [], excludes: [], includes: [], excludeSgk: false }),
  ["-all"],
  "空选显式排除"
);

console.log(fail ? `\n${fail} 项失败` : "\n全部通过");
process.exit(fail ? 1 : 0);
```

运行：`node frontend/test-friendly.mjs`

### 4.3 接口冒烟测试

```bash
BASE=http://127.0.0.1:1818
curl -s -c /tmp/ck -X POST -d 'password=admin123' $BASE/login -o /dev/null -w 'login=%{http_code}\n'

for p in /api/config /api/summary /api/sites /api/logs /api/bridge/health; do
  printf '%-24s ' $p
  curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/ck $BASE$p
done

# 未登录必须被拒
curl -s -o /dev/null -w 'noauth=%{http_code}\n' $BASE/api/config   # 期望 401
```

## 5. 调试技巧

### 5.1 看业务进程在做什么

```bash
docker logs -f --tail 100 embykeeper
```

日志里有 `(Peach)` 这样的前缀标识当前站点。

### 5.2 只跑某个站点

```bash
curl -b /tmp/ck -X POST -H 'Content-Type: application/json' \
  -d '{"site":"peach"}' http://127.0.0.1:1818/api/run
```

### 5.3 验证站点表达式解析结果

```bash
docker exec embykeeper python3 -c "
import asyncio
from embykeeper.telegram.dynamic import get_cls
cs = get_cls('checkiner', names=['-all','-sgk','templ_a<@SomeBot>','peach'])
print([getattr(c,'templ_name', c.__module__.rsplit('.',1)[-1]) for c in cs])
"
```

### 5.4 配置校验失败

保存时若报 `包含未知设置项：xxx`，说明表单提交了 `schema.py` 未定义的字段。
Pydantic 模型是 `extra="forbid"`，需先补字段。

### 5.5 前端页面白屏

1. 浏览器控制台看报错
2. 确认 `npm run build` 成功
3. 检查 `find_ui_assets()` 是否找到入口（日志里有 `/ui-assets/...` 请求）

## 6. 新增一个签到站点

1. 在 `embykeeper/telegram/checkiner/` 新建 `yoursite.py`：

```python
from . import BotCheckin


class YourSiteCheckin(BotCheckin):
    name = "你的站点"           # 界面显示名
    bot_username = "xxx_bot"    # 机器人用户名
    bot_checkin_cmd = "/start"  # 签到命令

    # 若站点有验证码，补充：
    # bot_captcha_len = 4
    # bot_checkin_caption_pat = "请输入验证码"
```

2. 若交互逻辑特殊（如需要回答问题），覆写 `message_handler()`
3. 验证：`get_cls('checkiner', names=['yoursite'])` 能拿到类
4. 控制台「签到站点」页会自动出现该站点（后端扫描模块生成清单）

> 不需要注册到任何清单文件——`dynamic.py` 通过扫描目录发现签到器。

## 7. 发布

### 7.1 构建镜像

```bash
docker build -t embykeeper:$(date +%Y%m%d) .
```

镜像构建分三阶段：前端构建 → Python 依赖 → 运行镜像。前端产物在运行镜像中
位于 `/fe-dist`，由 `mount_image_dist()` 挂到 `/ui-assets`。

### 7.2 升级已部署实例

```bash
docker rm -f embykeeper
docker run -d --name embykeeper --restart unless-stopped --net=host \
  -e EK_WEBPASS=你的密码 \
  -v /path/to/data:/app/data \
  embykeeper:新版本
```

`/app/data` 挂载卷保留配置与会话，升级不丢数据。

## 8. 目录速查

| 想改什么 | 去哪 |
|---|---|
| 配置字段与默认值 | `embykeeper/schema.py` |
| 调度时间解析 | `embykeeper/schedule.py` |
| 签到流程 | `embykeeper/telegram/checkin_main.py` |
| 某个站点 | `embykeeper/telegram/checkiner/` |
| 验证码识别 | `embykeeper/ocr/` |
| 通知 | `embykeeper/notify.py`、`telegram_notify.py` |
| 控制台 API | `embykeeperweb/api.py` |
| 控制台页面 | `frontend/src/views/` |
| 配置表达式转换 | `frontend/src/lib/friendly.js` |
| 容器启动 | `scripts/docker-entrypoint.sh` |
