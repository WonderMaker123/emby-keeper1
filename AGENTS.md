# AGENTS.md — 开发约定与架构指引

> 面向 AI 编程助手与人类贡献者。**动手改代码前请先读完本文档**。
> 最后更新：2026-11

---

## 1. 项目一句话概括

Embykeeper 是一个 Python 自动化工具：定时模拟 Emby/Subsonic 播放保号，并自动完成
Telegram 机器人的站点签到。附带一个 Vue 3 图形控制台，让用户不必手写配置文件。

## 2. 最重要的架构约束（违反会直接导致线上故障）

### 2.1 一个容器，两个进程

```
容器 embykeeper
├── PID A: embykeeper --basedir /app/data     ← 业务进程（asyncio + pyrogram）
└── PID B: embykeeperweb run                  ← 控制台（Flask + Werkzeug 同步模型）
```

启动脚本：`scripts/docker-entrypoint.sh`

**为什么不是单进程**：业务以 asyncio 事件循环为核心，控制台是 Werkzeug 同步模型。
早期版本用 eventlet monkey patch + PTY + SocketIO 把两者塞进一个进程，结果
eventlet 被官方弃用、启动告警刷屏、且 Web 崩溃会连带业务停摆。现在两者完全独立，
只通过回环 HTTP 通信。**不要试图把业务逻辑塞回 Web 进程。**

**为什么不是两个容器**：用户明确要求单容器部署。进程间通信走 `127.0.0.1`，
不需要跨容器网络。

### 2.2 配置文件的单一真相来源

`config.toml` 位于 `EK_BASEDIR`（默认 `/app/data`），是唯一的配置来源：

```
业务进程 ──watchfiles 监听──> config.toml <──读写── 控制台
```

- 控制台保存后，业务进程通过 `awatch` 自动热重载，**不需要重启容器**
- 业务进程的 `cache.json`（会话凭据、调度状态）也在同一目录

⚠️ **历史坑**：`config.py` 的 `reload_conf()` 原本在 Linux 下固定读 `Path("config.toml")`
（即当前工作目录），而 `cache.json` 却写在 `basedir`。两者不一致时，若工作目录存在一个
空的 `config.toml`，程序会读到空配置并认为「没有任何账号」，**且不报错**。
现已改为 basedir 优先。修改配置加载逻辑时务必保持这一致性。

### 2.3 前端不接触配置文件语法

配置文件里有一批普通用户无法理解的写法：

| 字段 | 配置中的形态 | 含义 |
|---|---|---|
| `time_range` | `"<11:00AM,11:00PM>"` | 每天在该区间内随机挑时刻执行 |
| `interval_days` | `"<7,12>"` | 每隔 7~12 天随机执行一次 |
| `time` | `[300, 600]` | 播放/收听时长区间（秒） |
| `site.checkiner` | `["-all","-sgk","templ_a<@Bot>","peach"]` | 带修饰符的站点表达式列表 |

**UI 上一律用友好控件表达**，转换逻辑集中在 `frontend/src/lib/friendly.js`：

- `parseTimeRange` / `formatTimeRange` ←→ 两个 `<input type="time">`
- `parseInterval` / `formatInterval` ←→ 「每天 / 每隔 N 天 / 区间随机」三段式
- `parseDuration` / `formatDuration` ←→ 分钟数字输入框
- `parseSiteTokens` / `composeSiteTokens` ←→ 站点卡片勾选

**禁止**在 Vue 组件里直接拼这些表达式字符串，也不要新增由 JSON Schema 驱动的通用表单
（历史教训：那会让界面退化成一个「TOML 编辑器」，正是用户抱怨的点）。

### 2.4 站点表达式语义（容易搞错）

`site.checkiner` 的解析实现在 `embykeeper/telegram/dynamic.py::get_cls`：

- `all` → 展开为全部内置站点（**会覆盖**已收集的普通站点名）
- `-xxx` → 排除
- `+xxx` → 额外包含
- `templ_a<@Bot>` → 自定义模板站点，**必须**在 `all` 展开后单独并回，否则会被覆盖丢失

写测试时注意这几种组合的等价性：

```
["-all","-sgk","templ_a<@A>","peach"]  ≡  ["peach","templ_a<@A>"]
```

（手动清单已显式指定站点时，`-all`/`-sgk` 是冗余但无害的标记。）

## 3. 代码地图

```
embykeeper/                     # 业务核心（CLI + 调度 + 签到器）
├── cli.py                      # Typer 入口；装配 RuntimeService，启动桥接服务
├── runtime.py                  # RuntimeService：编排签到/Emby/Subsonic 三类任务
├── config.py                   # 配置加载、校验、热重载（awatch）
├── schema.py                   # Pydantic 模型，定义全部配置字段与中文说明
├── bridge.py                   # 业务侧的本地控制服务（标准库 http.server）
├── notify.py                   # 通知分发（Telegram 直推 / Apprise）
├── telegram_notify.py          # Telegram Bot API 直推实现
├── schedule.py                 # 调度器：解析 time_range / interval_days
├── ocr/                        # 验证码识别
│   ├── router.py               # AI 优先 → 本地兜底 的路由
│   ├── local.py                # ddddocr 子进程封装
│   └── providers/sensenova.py  # SenseNova compatible-mode 客户端
├── telegram/                   # pyrogram 会话与签到器
│   ├── checkin_main.py         # CheckinManager：站点调度与执行
│   ├── checkiner/              # 每个站点一个模块（peach.py 等）
│   └── dynamic.py              # 动态发现签到器 + 站点表达式解析
└── emby/, subsonic/            # 保活实现

embykeeperweb/                  # 控制台（只做配置管理）
├── app.py                      # Flask 应用、认证、静态资源、启动参数
├── api.py                      # REST API（见下表）
├── bridge_client.py            # 调用业务侧 bridge 的客户端
├── config_io.py                # 配置加载（被 app 与 api 共用，避免循环导入）
└── templates/                  # ui.html / login.html / 404.html

frontend/                       # Vue 3 控制台
├── src/lib/friendly.js         # ★ 配置表达式 ⇄ 友好值 的转换层
├── src/stores/config.js        # 全局配置草稿（跨页面共享 + dirty 检测）
├── src/views/                  # Overview/Accounts/Sites/Notify/Settings/Logs
└── src/components/             # ui/（通用）+ friendly/（时间/间隔/时长控件）

scripts/docker-entrypoint.sh    # 单容器双进程启动脚本
```

## 4. API 一览

所有接口挂在 `<prefix>/api`，受 `webpass` 保护（未设置密码时放行）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/schema` | 配置模型 JSON Schema（**仅供调试，前端已不再用它渲染表单**） |
| GET | `/config` | 读取配置（敏感字段已掩码） |
| POST | `/config` | 保存配置（自动还原掩码值） |
| GET | `/summary` | 概览：账号数、站点模式、OCR 状态 |
| GET | `/sites` | 站点清单（中文名/分类/是否需验证码），带 5 分钟缓存 |
| POST | `/sites/resolve` | 把表达式列表解析为实际生效的站点 |
| GET | `/sites/template-fields` | 自定义站点的可配置参数定义 |
| GET | `/sites/custom` | 当前配置中的自定义站点 |
| POST | `/sites/validate-bot` | 校验机器人用户名格式 |
| GET | `/logs` | 业务进程日志（`since`/`level`/`keyword`/`limit`） |
| POST | `/run` | 立即运行（空 body = 全部；`{"site":"peach"}` = 单站） |
| GET | `/bridge/health` | 业务进程是否在线 |
| POST | `/notifier/test` | 发送一条测试通知 |

### 敏感字段掩码机制

`api.py` 中 `SENSITIVE_PATTERNS` 定义需要掩码的**字段名片段**（不是中文标题！）：
`password / api_key / token / api_hash / secret / apprise_uri / session`。

- 读取时：`mask_config()` 把值替换为 `abcd****wxyz`
- 保存时：`restore_masked()` 按 `IDENTITY_KEYS = (phone, username, url, name)` 匹配旧记录并还原

⚠️ 掩码匹配必须基于**字段名**。曾因按中文标题「密码」匹配英文 `password` 失败，
导致密码在页面上明文显示。

`session`（Telegram 登录凭据）等同于账号控制权，必须掩码。

## 5. 业务侧桥接服务（bridge.py）

业务进程内启动一个仅监听 `127.0.0.1` 的 HTTP 服务，供控制台查询日志与触发任务。

- **刻意只用标准库 `http.server`**：桥接是附属能力，不应因 Web 侧依赖缺失而拖垮业务进程启动
- 鉴权：启动时生成随机令牌写入 `$EK_BASEDIR/control.token`（权限 600）
- 端口：默认 8765，被占用时自动顺延，实际端口写入 `$EK_BASEDIR/control.port`
- 跨线程调度：通过 `asyncio.run_coroutine_threadsafe` 把任务投递到业务主循环
- 触发执行后**立即返回**，不阻塞 HTTP 请求（签到可能耗时数分钟）

## 6. 验证码识别（ocr/）

`OCRRouter.recognize()` 的优先级：

```
AI（SenseNova compatible-mode）
  ├─ 成功 → 校验字符集/长度 → 通过则返回 (text, 1.0, "ai")
  └─ 失败/超时/校验不通过 → 降级
本地 ddddocr（子进程，避免阻塞事件循环）
  ├─ 置信度 ≥ min_confidence → 返回 (text, conf, "local")
  └─ 否则 → (text, conf, "local_low")，由上层重试
```

配置项 `ocr.provider` 只有 `ai` / `local` 两种。**没有** `ai_fallback_confidence`
阈值（历史遗留字段已删除，若在配置里看到请清理）。

## 7. 开发流程

### 环境

```bash
python -m venv venv && . venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e .
```

⚠️ `ddddocrfix` / `pyrogram` 在 Windows 上可能装不上（依赖 `termios` 等 POSIX 模块）。
本地只做静态检查、用 Docker 验证完整功能。

### 前端

```bash
cd frontend
npm install
npm run build     # 产物输出到 embykeeperweb/templates/assets/dist
npm run dev       # 开发服务器，API 代理到 127.0.0.1:1818
```

### 验证清单（提交前必做）

```bash
# 1. Python 语法
python -m py_compile $(git ls-files '*.py')

# 2. 前端构建（会暴露模板语法错误）
cd frontend && npm run build

# 3. 启动脚本语法
bash -n scripts/docker-entrypoint.sh

# 4. 关键逻辑回归：站点表达式往返等价
node -e "/* 见 docs/DEVELOPMENT.md 的测试片段 */"
```

### 提交约定

- 提交信息用英文，格式 `<type>(<scope>): <subject>`，如 `fix(config): read config from basedir`
- 一次提交只做一件事，不要把重构和功能混在一起
- **不要提交** `config.toml`、`*.session`、`cache.json`、任何真实凭据

## 8. 常见坑（都踩过）

| 症状 | 原因 | 处理 |
|---|---|---|
| 控制台显示「前端未构建」 | 镜像里 `/fe-dist` 存在但 `find_ui_assets` 没找到 | 检查 `mount_image_dist` 是否注册了 `/ui-assets` 路由 |
| 页面加载了旧代码 | 多次构建后旧 hash 文件残留 | `find_ui_assets` 只取 mtime 最新的入口；构建前清空 `dist` |
| 保存配置后密码变成 `******` | 掩码还原失败（标识字段对不上） | 检查 `IDENTITY_KEYS` 与账号字段是否匹配 |
| 业务进程说「没有需要执行的任务」 | 读到了空的/错误的 config.toml | 检查 `EK_BASEDIR`，以及工作目录是否有空 config.toml |
| 签到报「非可交互终端」 | Telegram 会话丢失，需重新登录 | 确认 `cache.json` 与 `.session` 在挂载目录内 |
| 自定义站点加了但不签到 | 站点表达式被 `all` 覆盖 | 见 2.4，确认 `dynamic.get_cls` 的 templ 合并逻辑 |
| 保存报「包含未知设置项」 | Pydantic 模型 `extra=forbid`，表单加了模型没有的字段 | 先在 `schema.py` 补字段，再改前端 |

## 9. 改动前先问自己

1. 这个改动会影响**业务进程**还是**仅控制台**？两者的失败代价不同。
2. 配置字段是否需要在 `schema.py` 加中文 `title` / `description`？
3. 新增的配置写法，前端是否有对应的**友好控件**？若没有，用户就会被逼着写 TOML。
4. 是否会破坏**已部署实例**的兼容性（旧配置能否继续加载）？
5. 有没有把凭据写进代码、日志或提交？
