# ---------- 前端构建 ----------
FROM node:20-slim AS frontend-builder

WORKDIR /fe
# 先拷贝依赖清单, 利用层缓存避免每次改代码都重装依赖
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
# 产物输出到 /fe/dist (通过 VITE_OUT_DIR 覆盖默认的本地输出目录)
RUN VITE_OUT_DIR=/fe/dist npm run build

# ---------- Python 依赖 ----------
FROM python:3.11 AS builder

WORKDIR /src
COPY . .

RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir .

# ---------- 运行镜像 ----------
FROM python:3.11-slim
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/scripts/docker-entrypoint.sh /entrypoint.sh
# 注入前端构建产物 (仅静态文件, 不含 node_modules)
COPY --from=frontend-builder /fe/dist /fe-dist

ENV TZ="Asia/Shanghai"
ENV EK_IN_DOCKER="1"

LABEL org.opencontainers.image.source="https://github.com/DotRacel/emby-keeper0" \
      org.opencontainers.image.description="Emby 签到保号自动化工具 (去中心化维护版)" \
      org.opencontainers.image.licenses="GPL-3.0"

WORKDIR /app
# 不再生成空的 config.toml: 空文件会被当成一份有效配置, 使程序认为「没有任何账号」
# 而不报错 (曾经的线上问题). 数据目录统一为 /app/data, 首次启动时由程序生成
# 示例配置并给出提示.
RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/data
ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["/entrypoint.sh"]
