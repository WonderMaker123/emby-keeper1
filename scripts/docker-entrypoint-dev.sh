#!/bin/bash

set -e

if [ -d "/src" ]; then
    if [ ! "$(ls -A /src)" ]; then
        cp -rT /build /src
    fi
    echo ">> 正在根据源码配置程序, 请稍候."
    pip install --no-cache-dir -e /src
    echo ">> 已配置完成."
    echo
else
    echo ">> 请挂载目录 /src, 以释放源码."
    exit 1
fi

if [ -z "${EK_WEBPASS}" ]; then
    echo ">> 未设置控制台密码 (EK_WEBPASS), 仅启动业务进程."
    exec "embykeeper" "--basedir" "/app" "$@"
fi

echo ">> 正在启动业务进程与控制台 (单容器, 双进程)..."
"embykeeper" "--basedir" "/app" "$@" &
EK_PID=$!
"embykeeperweb" "run" &
WEB_PID=$!

_shutdown() {
    echo ">> 正在停止..."
    kill -INT "$EK_PID" 2>/dev/null || true
    kill -TERM "$WEB_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap _shutdown TERM INT QUIT

wait -n "$EK_PID" "$WEB_PID"
STATUS=$?
kill -INT "$EK_PID" 2>/dev/null || true
kill -TERM "$WEB_PID" 2>/dev/null || true
wait 2>/dev/null || true
exit "$STATUS"
