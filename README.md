<p align="center">
  <img src="https://github.com/WonderMaker123/emby-keeper1/raw/main/images/logo.svg" alt="Embykeeper" width="120" />
</p>

<p align="center">
  <b>Emby / Subsonic 自动保号 · Telegram 机器人自动签到</b>
</p>

<p align="center">
  <a href="https://github.com/WonderMaker123/emby-keeper1/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="license" /></a>
  <img src="https://img.shields.io/badge/docker-single--container-2496ED" alt="docker" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="python" />
  <img src="https://img.shields.io/badge/console-Vue%203-42b883" alt="vue" />
</p>

---

## 这是什么

一个跑在服务器上的自动保号工具，做两件事：

1. **Emby / Subsonic 保活** —— 定时模拟登录与播放/收听，保持账号活跃。
2. **Telegram 机器人签到** —— 自动完成 100+ 站点的每日签到以获取积分。

自 v7.6.1 起提供**图形化控制台**：账号、站点、通知、验证码识别全部在网页上点选完成，
不需要手写配置文件。

## 特性

- **一个容器搞定**：业务进程与控制台跑在同一个容器内，一条命令启动
- **网页配置**：添加账号、挑选站点、配置通知都有向导式表单，不接触 TOML
- **AI 验证码识别**：默认 AI 优先，失败自动退回本地 ddkddocr，兼顾准确率与可用性
- **实时日志**：控制台内直接查看业务进程输出，无需 `docker logs`
- **一键立即运行**：不必等到计划时间，随时手动触发一次签到/保活
- **配置热重载**：网页保存后业务进程自动生效，无需重启容器

## 快速开始

```bash
docker run -d \
  --name embykeeper \
  --restart unless-stopped \
  --net=host \
  -e EK_WEBPASS=你的控制台密码 \
  -v $(pwd)/embykeeper:/app/data \
  ghcr.io/wondermaker123/emby-keeper1:latest
```

启动后访问 **`http://服务器IP:1818/ui`**，输入上面设置的密码进入控制台。

首次进入按「总览」页的待办提示逐项完成即可：添加 Telegram 账号 → 选择签到站点 →
（可选）配置通知 → 保存。保存后业务进程自动加载。

### 启动模式

| 环境变量 | 行为 |
|---|---|
| 设置了 `EK_WEBPASS` | 业务进程 + 控制台（推荐） |
| 未设置 | 仅业务进程，纯命令行模式 |
| `EK_DISABLE_WEB=1` | 仅业务进程，显式关闭控制台 |

### 数据目录

`/app/data` 存放 `config.toml`、`cache.json` 与 Telegram 登录会话。
**务必挂载到宿主机**，否则容器重建后需要重新登录 Telegram（需人工输入验证码）。

## 从源码构建

```bash
git clone https://github.com/WonderMaker123/emby-keeper1.git
cd emby-keeper1

# 镜像内会自动完成前端构建，无需本地装 Node
docker build -t embykeeper:local .
docker run -d --name embykeeper --restart unless-stopped --net=host \
  -e EK_WEBPASS=你的密码 \
  -v $(pwd)/data:/app/data \
  embykeeper:local
```

## 文档

| 文档 | 说明 |
|---|---|
| [部署指南](docs/guide/Linux-Docker-部署.md) | Docker 部署、反向代理、升级 |
| [控制台使用](docs/guide/控制台使用.md) | 账号/站点/通知的图文操作说明 |
| [配置文件](docs/guide/配置文件.md) | 手写配置时的字段说明（控制台用户可跳过） |
| [架构说明](docs/ARCHITECTURE.md) | 模块划分、进程模型、数据流 |
| [开发指南](AGENTS.md) | 面向 AI 助手与贡献者的开发约定 |

## 声明

本项目涉及的一切 Emby 服务器与开发团队无关，使用本工具造成的一切损失（包括但不限于
Emby 或 Telegram 账号被封禁）与开发团队无关。为账号安全，推荐使用小号。

本项目设计初衷是在中文 Emby 社群规则下帮助时间紧张的用户保号，不鼓励持有大量账号而不使用。
仅保留 1-2 个质量较高的 Emby 服务器即可。

安装并使用即表示您已阅读并同意上述声明，并确认自己并非出于"集邮"目的而安装。

## 许可

[GPL-3.0](LICENSE)

---

本项目基于 [DotRacel/emby-keeper0](https://github.com/DotRacel/emby-keeper0) 二次开发，
感谢原作者与上游贡献者。
