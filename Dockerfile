# Stage 1: copy telegram-bot-api binary (musl-linked) from official image
FROM aiogram/telegram-bot-api:7.6 AS bot-api-src

# Stage 2: build frontend with locked dependencies
FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Stage 3: final runtime image — Alpine for musl compatibility with bot-api binary
FROM python:3.12-alpine

ARG BUILD_DATE=unknown

RUN apk add --no-cache \
    ffmpeg \
    supervisor \
    curl \
    ca-certificates \
    font-noto-cjk \
    bind-tools \
    proxychains-ng \
    build-base \
    && rm -rf /var/cache/apk/*

RUN mkdir -p /var/log/supervisor /var/run/supervisor

# Telegram local bot API binary (Alpine musl, compatible with Alpine base)
COPY --from=bot-api-src /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

COPY supervisord.conf /etc/supervisor/conf.d/app.conf

COPY bot-api-wrapper.sh /usr/local/bin/bot-api-wrapper.sh
RUN chmod +x /usr/local/bin/bot-api-wrapper.sh

WORKDIR /app

# Python deps (exact versions pinned; build-base required for C extensions)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    apk del build-base

# Version & build info (placed after deps to avoid cache bust)
COPY VERSION /app/VERSION
RUN echo "${BUILD_DATE}" > /app/BUILD_DATE

COPY app/ ./app/

COPY --from=frontend-builder /frontend/dist/ ./static/

RUN mkdir -p /app/config /data/output /data/thumbnails /tmp/compress_workers

# Non-root user for child processes
RUN adduser -D -u 1000 appuser \
    && chown -R appuser:appuser /app /data /tmp/compress_workers /var/log/supervisor /var/run/supervisor

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD supervisorctl -c /etc/supervisor/conf.d/app.conf status app | grep -q RUNNING || exit 1

ENTRYPOINT ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/app.conf"]
