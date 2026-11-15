#!/bin/bash
# 单容器启动脚本: 业务进程 + 控制台进程.
#
# 为什么是「一个容器、两个进程」而不是合并成一个进程:
#   业务以 asyncio 事件循环为核心; 控制台依赖 eventlet (monkey_patch socket/select)
#   与 Werkzeug 同步模型. eventlet 的 socket patch 会全局替换 socket 模块, 若与业务
#   asyncio/pyrogram 同进程运行, 会互相破坏对方的事件循环与连接. 因此这里在同一个
#   容器内并行运行两个进程, 共享回环网络与数据目录: 控制台通过 127.0.0.1 上的
#   控制桥接服务读取日志、触发任务.
#
# 启动模式:
#   EK_WEBPASS 为空        → 仅运行业务 (兼容纯 CLI 部署)
#   EK_DISABLE_WEB=1       → 仅运行业务 (资源受限时显式关闭控制台)
#   EK_WEBPASS 已设置       → 业务 + 控制台 (推荐)

# 数据目录: config.toml / cache.json / 会话凭据 / 控制桥接令牌都放在这里.
# 统一为 /app/data, 与 cache.py 的 basedir 约定保持一致 ——
# 业务进程读配置、写缓存、控制台读写配置都指向同一目录, 不再出现
# 「配置读一处、缓存写另一处」的错位.
BASEDIR="${EK_BASEDIR:-/app/data}"
mkdir -p "$BASEDIR"
export EK_BASEDIR="$BASEDIR"

run_cli_only() {
    exec "embykeeper" "--basedir" "$BASEDIR" "$@"
}

if [ -z "${EK_WEBPASS}" ]; then
    echo ">> 未设置控制台密码 (EK_WEBPASS), 仅启动业务进程."
    run_cli_only "$@"
fi

if [ "${EK_DISABLE_WEB}" = "1" ]; then
    echo ">> 已显式禁用控制台 (EK_DISABLE_WEB=1), 仅启动业务进程."
    run_cli_only "$@"
fi

echo ">> 正在启动业务进程与控制台 (单容器, 双进程)..."

# 业务进程: 后台运行, stdout 直连容器日志, 由 docker logs 可见
"embykeeper" "--basedir" "$BASEDIR" "$@" &
EK_PID=$!

# 控制台进程: 只做配置管理, 通过回环桥接服务与业务进程通信.
# 不传 --basedir: 上面已导出 EK_BASEDIR, serve() 会直接读取环境变量.
# 不传 --public: 保留 EK_WEBPASS 鉴权, 避免控制台裸露在公网.
"embykeeperweb" "run" &
WEB_PID=$!

_stop_all() {
    # 业务进程以 Ctrl+C 语义优雅退出: 登出 Telegram 会话、落盘任务状态.
    kill -INT "$EK_PID" 2>/dev/null || true
    kill -TERM "$WEB_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}

_handle_signal() {
    echo ">> 收到停止信号, 正在结束两个进程..."
    _stop_all
    exit 0
}
trap _handle_signal TERM INT QUIT

# 任一进程退出即整体退出, 交由 Docker 的 restart 策略重建.
# 这样可以避免「控制台在跑但业务已死」这种不易察觉的半死状态.
wait -n
STATUS=$?

if kill -0 "$EK_PID" 2>/dev/null; then
    echo ">> 控制台进程已退出 (code=$STATUS), 正在停止业务进程."
else
    echo ">> 业务进程已退出 (code=$STATUS), 正在停止控制台进程."
fi

_stop_all
exit "$STATUS"
