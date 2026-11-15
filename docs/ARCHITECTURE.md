# 架构说明

本文描述 Embykeeper 的整体设计、进程模型与数据流。面向需要修改代码或排查问题的开发者。

---

## 1. 总体结构

```
                    ┌──────────────────────────────────────┐
   浏览器 ──HTTP──> │  容器 embykeeper（单容器，双进程）      │
                    │                                      │
                    │  ┌────────────────────────────────┐  │
                    │  │ 进程 B: embykeeperweb (Flask)  │  │
                    │  │  · 提供 /ui 单页应用            │  │
                    │  │  · REST API 读写 config.toml    │  │
                    │  │  · 不执行业务逻辑               │  │
                    │  └───────────┬────────────────────┘  │
                    │              │ 回环 HTTP (127.0.0.1)  │
                    │              │ + control.token 鉴权    │
                    │  ┌───────────▼────────────────────┐  │
                    │  │ 进程 A: embykeeper (asyncio)   │  │
                    │  │  · RuntimeService 编排任务      │  │
                    │  │  · pyrogram 会话 / 签到器        │  │
                    │  │  · Emby/Subsonic 保活           │  │
                    │  │  · bridge.py 提供日志与触发接口  │  │
                    │  └───────────┬────────────────────┘  │
                    └──────────────┼───────────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ /app/data（挂载卷）  │
                        │  config.toml        │
                        │  cache.json         │
                        │  *.session          │
                        │  control.token/port │
                        └─────────────────────┘
```

## 2. 进程模型

### 2.1 为什么是两个进程

| 关注点 | 业务进程 | 控制台进程 |
|---|---|---|
| I/O 模型 | asyncio 事件循环 | Werkzeug 同步 / 线程池 |
| 核心依赖 | pyrogram、httpx、watchfiles | Flask、Flask-Login |
| 失败代价 | 签到停摆（用户直接感知） | 页面打不开（可重启修复） |
| 资源占用 | 较高（长连接 + OCR 模型） | 低 |

两者的 I/O 模型互斥。早期版本用 `eventlet` 的 monkey patch 把 Flask 与 asyncio
塞进同一进程，并用 PTY + SocketIO 把业务进程挂在 Web 进程下，导致：

- eventlet 已被官方弃用，启动时刷出大量告警
- Web 进程崩溃会连带业务停摆
- 无法独立升级任一侧
- 绿色线程与 asyncio 混用，出现难以复现的阻塞

现在改为独立进程，仅通过回环 HTTP 通信。

### 2.2 为什么是一个容器

用户明确要求单容器部署。两个进程共享：

- 网络命名空间（`--net host`，因此 `127.0.0.1` 互通）
- 挂载卷 `/app/data`（因此 `control.token` 可共享）
- 生命周期（任一进程退出，容器退出并由 restart 策略重建）

启动逻辑见 `scripts/docker-entrypoint.sh`：

```bash
embykeeper --basedir /app/data &   # 业务
embykeeperweb run &                # 控制台
wait -n                            # 任一退出即整体退出
```

## 3. 数据流

### 3.1 用户修改配置

```
浏览器 → POST /api/config
        → api.save_config()
           ├─ restore_masked()  还原被掩码的密码/密钥
           ├─ Config.model_validate()  Pydantic 校验
           ├─ 写回 config.toml
           └─ 更新内存中的 runtime_config
                     ↓
        业务进程的 awatch 检测到文件变化
                     ↓
        config.reload_conf() → 重新校验 → 触发各管理器的 on_change
                     ↓
        签到/保活任务按新配置重新排期（无需重启）
```

### 3.2 查看日志

```
浏览器 → GET /api/logs
        → bridge_client.fetch_logs()
           ├─ 读 $EK_BASEDIR/control.port 得到业务侧端口
           ├─ 读 $EK_BASEDIR/control.token 得到鉴权令牌
           └─ GET http://127.0.0.1:<port>/logs
                     ↓
        业务进程的 bridge.py 从内存环形缓冲（deque, 4000 条）取出
```

日志同时由 `install_log_sink()` 写入环形缓冲。它在 `initialize()` 之后安装，
因为 `initialize()` 内部会 `logger.remove()` 清空所有 handler。

### 3.3 立即运行一次

```
浏览器 → POST /api/run {"site":"peach"}
        → bridge_client.trigger_run()
           → POST http://127.0.0.1:<port>/run
                     ↓
        bridge.py 用 asyncio.run_coroutine_threadsafe()
        把协程投递到业务主循环，然后**立即返回**
                     ↓
        业务侧异步执行，结果写入日志，前端轮询 /api/logs 查看
```

立即返回是必要的：单站点签到可能耗时数分钟，同步等待会超时。

## 4. 配置模型

### 4.1 结构

`embykeeper/schema.py` 用 Pydantic v2 定义。顶层：

```python
class Config(ConfigModel):
    emby: Optional[EmbyConfig]           # 保活全局设置 + account 列表
    subsonic: Optional[SubsonicConfig]
    telegram: Optional[TelegramConfig]   # 签到用的 TG 账号
    checkiner: Optional[CheckinerConfig] # 签到调度
    ocr: Optional[OCRConfig]             # 验证码识别
    notifier: Optional[NotifierConfig]   # 结果通知
    proxy: Optional[ProxyConfig]
    site: Optional[SiteConfig]           # 站点范围
```

`ConfigModel` 设置 `extra="forbid"`：出现未知字段会直接报错。
这意味着**前端新增表单字段时，必须先在 schema 里加对应字段**。

### 4.2 特殊值类型

部分字段在配置里是字符串表达式，但语义是结构化数据：

| 字段 | 表达式 | 解析位置 |
|---|---|---|
| `time_range` | `<8:00AM,10:00PM>` | `schedule.py::Scheduler.from_str` |
| `interval_days` | `<7,12>` 或 `3` | 同上 |
| `site.checkiner` | `["-all","templ_a<@Bot>"]` | `telegram/dynamic.py::get_cls` |
| 账号 `time` | `[300, 600]` 或 `300` | `schema.py` 的 `BeforeValidator` |

## 5. 站点体系

### 5.1 内置签到器

`embykeeper/telegram/checkiner/` 下每个 `.py` 是一个站点，类继承 `BotCheckin`。
`dynamic.py::get_names()` 扫描模块名，`get_cls()` 按名称实例化。

### 5.2 自定义站点（模板 A）

用户可把任意「面板消息 + 签到按钮」型 Bot 注册为站点：

```
配置：
  site.checkiner = [..., "templ_a<@SomeBot>"]
  checkiner."templ_a<@SomeBot>" = { name = "我的小站", bot_checkin_cmd = "/start" }
```

`_templ_a.py` 实现通用交互流程，参数模型在 `_templ_config.py`
（单独成文件是为了让控制台能在不导入 pyrogram 的情况下读取字段定义）。

### 5.3 表达式解析的关键点

`get_cls()` 的处理顺序：

```python
# 1. 先抽出模板站点，否则会被下面的 all 展开覆盖
templ_names = {n for n in names if n.startswith("templ_")}
names -= templ_names

# 2. 处理 all：展开为全部内置站点
if "all" in names:
    names = set(get_names(type, allow_ignore=True))

# 3. 应用排除，再把模板站点并回（模板站点同样尊重显式排除）
names = (names - exclude_names) | (templ_names - exclude_names)
```

历史 bug：原实现先展开 `all` 再处理模板站点，导致 `["all","templ_a<@X>"]` 里的
自定义站点被静默丢弃。

## 6. 验证码识别

```
OCRRouter.recognize(image, gif, timeout, min_confidence)
  │
  ├─ AI 提供商（SenseNova compatible-mode，OpenAI 协议 + base64 图片）
  │    ├─ 重试 ai_max_retries 次
  │    ├─ validate_captcha() 校验字符集与长度
  │    └─ 通过 → ("文本", 1.0, "ai")
  │
  └─ 本地 ddddocr（独立子进程，避免 ONNX 推理阻塞事件循环）
       ├─ build_image_variants() 生成多种预处理变体
       ├─ 置信度 ≥ min_confidence → ("文本", conf, "local")
       └─ 否则 → ("文本", conf, "local_low")，交给上层重试
```

`ocr.provider` 只有 `ai` / `local`。AI 不可用时自动降级，不会跳过签到。

## 7. 通知

两条路径，由 `notifier.method` 选择：

- **telegram**（推荐）：`telegram_notify.TelegramStream` 直接调 Bot HTTP API。
  只需 `bot_token` + `chat_id`，错误信息会翻译成可操作的提示。
- **apprise**：`AppriseStream`，支持更多渠道但需要自拼 URI。

实现上两者都伪装成 loguru sink（`write()` / `close()` / `join()`），
在 `notify.py` 中按 `filter` 决定哪些日志转发。

## 8. 前端设计

### 8.1 状态管理

`stores/config.js` 维护一份**全局配置草稿**：

- `draft`：用户正在编辑的内容
- `frozen`：服务端快照，用于计算 `dirty`
- 所有页面共享同一份 `draft`，由外壳的保存条统一提交

这样跨页面编辑不会互相覆盖，也不会出现「在 A 页改了，切到 B 页又变回去」。

### 8.2 友好值转换

`lib/friendly.js` 是**唯一**允许接触配置表达式的地方。组件只接收/输出结构化值：

```vue
<TimeRange :model-value="checkiner.time_range" @update:model-value="..." />
<!-- 内部：<11:00AM,11:00PM> ⇄ 两个 time input -->
```

### 8.3 为什么不用 Schema 驱动表单

曾尝试用 `/api/schema` 返回的 JSON Schema 自动渲染表单。结果是用户必须在输入框里
手写 `"<11:00AM,11:00PM>"` 这类表达式——等于把配置文件搬到了网页上，失去了
图形界面的意义。现在所有表单**手工定制**，字段按使用频率分为「常用」与「高级」。

## 9. 扩展点

| 需求 | 改动位置 |
|---|---|
| 新增签到站点 | `telegram/checkiner/` 下加一个类，继承 `BotCheckin` |
| 新增配置项 | `schema.py` 加字段 → 控制台对应页面加控件 |
| 新增通知渠道 | `notify.py` 加一个 stream 实现 |
| 新增 OCR 提供商 | `ocr/providers/` 加实现，在 `factory.py` 注册 |
| 新增控制台页面 | `frontend/src/views/` + `router.js` 注册 |
