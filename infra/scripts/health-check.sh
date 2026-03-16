#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../../.env" 2>/dev/null || true
HOST="${OPENALGO_HOST:-http://127.0.0.1:5000}"
if curl -sf "$HOST/api/v1/ping" > /dev/null 2>&1; then
    echo "✅ OpenAlgo healthy"
else
    echo "❌ OpenAlgo DOWN"
    [ "${TELEGRAM_ENABLED:-false}" = "true" ] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=⚠️ FlintTrade: OpenAlgo DOWN at $(date '+%H:%M IST')" > /dev/null
    exit 1
fi
