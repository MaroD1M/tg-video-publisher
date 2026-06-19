#!/bin/sh
# Wait until the web UI has generated bot-api.env
while [ ! -f /app/config/bot-api.env ]; do
  sleep 3
done
. /app/config/bot-api.env

echo "=== Bot API Wrapper $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >&2

BOT_API_ARGS="\
  --api-id=${API_ID:-0} \
  --api-hash=${API_HASH:-} \
  --local \
  --dir=/app/config/bot-api-data \
  --http-port=8081 \
  --http-ip-address=127.0.0.1"

USE_PROXYCHAINS=0

if [ -n "${BOT_API_PROXY:-}" ]; then
  # Extract host, port, and optional auth from http://[user:pass@]host:port
  _PROXY_BODY=$(echo "${BOT_API_PROXY}" | sed 's|^[a-z]*://||')
  PROXY_AUTH=$(echo "${_PROXY_BODY}" | sed -n 's|^\([^@]*\)@.*|\1|p')
  if [ -n "$PROXY_AUTH" ]; then
    PROXY_HOST=$(echo "${_PROXY_BODY}" | sed 's|^[^@]*@||' | sed 's|:.*||')
  else
    PROXY_HOST=$(echo "${_PROXY_BODY}" | sed 's|:.*||')
  fi
  PROXY_PORT=$(echo "${_PROXY_BODY}" | sed 's|.*:||')

  cat > /tmp/proxychains.conf << PROXYEOF
strict_chain
proxy_dns
tcp_read_time_out 15000
tcp_connect_time_out 8000
[ProxyList]
http ${PROXY_HOST} ${PROXY_PORT}
PROXYEOF
  if [ -n "$PROXY_AUTH" ]; then
    echo "$PROXY_AUTH" >> /tmp/proxychains.conf
  fi

  echo "[proxychains] Routing ALL traffic through http://${PROXY_HOST}:${PROXY_PORT}" >&2
  USE_PROXYCHAINS=1
else
  echo "[fallback] Using Web UI proxy config from bot-api.env" >&2
  if [ -n "${TD_PROXY:-}" ]; then
    BOT_API_ARGS="$BOT_API_ARGS $TD_PROXY"
  fi
  if [ -n "${HTTP_PROXY:-}" ]; then
    export http_proxy="$HTTP_PROXY"
    export https_proxy="$HTTP_PROXY"
  fi
fi

echo "=== Starting ===" >&2
echo "  Args: $BOT_API_ARGS" >&2

RETRY=0
MAX_RETRIES=10

while true; do
  echo "[Bot API] Attempt $((RETRY+1))/$MAX_RETRIES" >&2

  if [ "$USE_PROXYCHAINS" = 1 ]; then
    /usr/bin/proxychains4 -q -f /tmp/proxychains.conf /usr/local/bin/telegram-bot-api $BOT_API_ARGS 2>&1 &
  else
    /usr/local/bin/telegram-bot-api $BOT_API_ARGS 2>&1 &
  fi
  BOT_PID=$!

  trap "kill $BOT_PID 2>/dev/null; exit 0" TERM INT QUIT

  wait $BOT_PID 2>/dev/null
  EXIT_CODE=$?

  trap - TERM INT QUIT

  RETRY=$((RETRY+1))
  if [ $RETRY -ge $MAX_RETRIES ]; then
    echo "[Bot API] Max retries ($MAX_RETRIES) reached, exit=$EXIT_CODE. Giving up." >&2
    exit $EXIT_CODE
  fi

  DELAY=$(( RETRY < 6 ? (1 << RETRY) : 60 ))
  echo "[Bot API] Crashed (exit=$EXIT_CODE), retrying in ${DELAY}s..." >&2
  sleep $DELAY
done
