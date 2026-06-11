#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  quick tunnel 상시 유지 + 주소 바뀌면 Worker KV 자동 갱신
#  사용: nohup deploy/tunnel-keeper.sh > /tmp/tunnel-keeper.log 2>&1 &
# ═══════════════════════════════════════════════════════════
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"

while true; do
  echo "[keeper] cloudflared 시작 ($(date '+%F %T'))"
  cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>&1 | while IFS= read -r line; do
    echo "$line"
    URL=$(echo "$line" | grep -o 'https://[a-z-]*\.trycloudflare\.com' | head -1)
    if [ -n "$URL" ] && [ "$URL" != "$LAST_URL" ]; then
      LAST_URL="$URL"
      echo "[keeper] 새 터널 주소 → KV 갱신: $URL"
      (cd "$ROOT/worker" && npx wrangler@latest kv key put api_origin "$URL" --binding CFG --remote) \
        && echo "[keeper] KV 갱신 완료" || echo "[keeper] ⚠ KV 갱신 실패 (wrangler login 확인)"
    fi
  done
  echo "[keeper] 터널 종료됨 — 5초 후 재시작"
  sleep 5
done
