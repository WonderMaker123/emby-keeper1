# Docker 部署

推荐方式。镜像托管在 GitHub Packages：`ghcr.io/wondermaker123/emby-keeper1`。

::: tip 前置
服务器需已安装 Docker。若首次拉取提示无权限，请确认仓库的 Packages 已设为 Public，
或先执行 `docker login ghcr.io`。
:::

## 1. 一条命令启动

```bash
docker run -d \
  --name embykeeper \
  --restart unless-stopped \
  --net=host \
  -e EK_WEBPASS=你的控制台密码 \
  -v $(pwd)/embykeeper:/app/data \
  ghcr.io/wondermaker123/emby-keeper1:latest
```

启动后访问 **`http://服务器IP:1818/ui`**，用上面设置的密码登录控制台。

::: tip `--net=host` 的作用
让容器共享主机网络，有两个好处：一是能连接主机上运行的代理；二是控制台与业务进程
通过 `127.0.0.1` 通信，无需额外配置。若不需要代理也可省略，但需自行映射 1818 端口。
:::

## 2. 数据目录（重要）

`-v $(pwd)/embykeeper:/app/data` 把数据目录挂载到宿主机，其中包含：

| 文件 | 内容 |
|---|---|
| `config.toml` | 全部配置 |
| `cache.json` | 调度状态、Emby 设备信息 |
| `*.session` | Telegram 登录会话 |

::: warning 务必挂载
不挂载的话，容器重建后 Telegram 会话丢失，需要重新登录（需人工输入手机验证码，
而容器内无法交互输入）。此外配置也会丢失。
:::

## 3. 在控制台完成配置

登录后按「总览」页的待办提示逐项操作，通常顺序是：

1. **账号** → 添加 Telegram 账号（签到必需）
2. **账号** → 添加 Emby / Subsonic 账号（保号必需）
3. **签到站点** → 选择签到范围
4. **结果通知** → 配置 Telegram 推送（可选）

每改完一处，点击右上角「**保存配置**」。业务进程会自动热重载，**无需重启容器**。

详细操作见 [控制台使用指南](./控制台使用.md)。

::: warning 首次登录 Telegram 的风控
Telegram 对陌生 IP 登录较敏感。建议先在手机（使用与服务器相同地区的网络）登录一次
该账号，确认正常后再让服务器使用。程序会复用已有会话，不会重复登录。
:::

## 4. 验证部署

```bash
# 容器状态
docker ps --filter name=^embykeeper$

# 查看日志：应能看到"已加载配置"和"下一次签到将在..."
docker logs --tail 30 embykeeper

# 接口连通性
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:1818/healthz   # 200
```

在控制台「运行日志」页也能直接看到业务进程输出。

## 5. 常用运维操作

```bash
# 停止 / 启动
docker stop embykeeper && docker start embykeeper

# 查看实时日志
docker logs -f --tail 100 embykeeper

# 升级到新版本（数据不丢）
docker rm -f embykeeper
docker run -d --name embykeeper --restart unless-stopped --net=host \
  -e EK_WEBPASS=你的密码 \
  -v $(pwd)/embykeeper:/app/data \
  ghcr.io/wondermaker123/emby-keeper1:latest

# 备份配置
cp embykeeper/config.toml embykeeper/config.toml.bak
```

## 6. 启动模式

| 环境变量 | 行为 |
|---|---|
| 设置了 `EK_WEBPASS` | 业务进程 + 控制台（推荐） |
| 未设置 | 仅业务进程，纯命令行模式 |
| `EK_DISABLE_WEB=1` | 仅业务进程，显式关闭控制台 |

::: info 纯命令行模式
不设置 `EK_WEBPASS` 即退化为旧用法，通过 `-i` 参数启动后立刻运行一次：

```bash
docker run -v $(pwd)/embykeeper:/app/data --rm -it --net=host \
  ghcr.io/wondermaker123/emby-keeper1 -i
```
:::

## 7. 反向代理与 HTTPS

控制台默认监听 `0.0.0.0:1818`。若要放到域名下，Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name ek.example.com;

    ssl_certificate     /etc/letsencrypt/live/ek.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ek.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:1818;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

应用已启用 `ProxyFix`，能正确处理 `X-Forwarded-*` 头。

若部署在子路径下（如 `https://example.com/ek`），加环境变量：

```bash
-e EK_BASE_PREFIX=/ek
```

## 8. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面提示「前端资源尚未构建」 | 镜像异常或用了源码运行 | 用官方镜像；源码运行需先 `cd frontend && npm run build` |
| 登录后一直跳回登录页 | `SECRET_KEY` 每次重启变化导致会话失效 | 正常现象，重新登录即可 |
| 业务进程说「没有需要执行的任务」 | 读到了空配置或 basedir 不对 | 确认挂载到 `/app/data`，且该目录有 `config.toml` |
| 日志「非可交互终端」 | Telegram 会话缺失 | 先在本地登录该账号，确保 `*.session` 在挂载目录内 |
| 控制台打不开 | 端口未映射或 `--net=host` 未加 | 检查 `docker ps` 的端口，或改用 `-p 1818:1818` |

::: info 支持

<!--@include: ./_支持.md-->

:::
