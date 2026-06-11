#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  StoryQuant 1회 배포 셋업 (wrangler login 후 실행)
#  1) KV namespace 생성 → wrangler.toml 에 id 주입
#  2) 정적 빌드 → Worker 배포
#  3) 현재 터널 주소를 KV 에 등록
# ═══════════════════════════════════════════════════════════
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/worker"

if grep -q 'REPLACE_WITH_KV_ID' wrangler.toml; then
  echo "📦 KV namespace 생성 (CFG)"
  OUT=$(npx wrangler@latest kv namespace create CFG 2>&1)
  echo "$OUT"
  KV_ID=$(echo "$OUT" | grep -o '"?id"?[: =]*"[a-f0-9]\{32\}"' | grep -o '[a-f0-9]\{32\}' | head -1)
  if [ -z "$KV_ID" ]; then
    KV_ID=$(echo "$OUT" | grep -o '[a-f0-9]\{32\}' | head -1)
  fi
  if [ -z "$KV_ID" ]; then
    echo "❌ KV id 추출 실패 — 위 출력에서 id 를 wrangler.toml 에 직접 넣어주세요"; exit 1
  fi
  sed -i "s/REPLACE_WITH_KV_ID/$KV_ID/" wrangler.toml
  echo "✅ KV id 주입: $KV_ID"
fi

echo "📦 정적 빌드"
bash "$ROOT/deploy/build-public.sh"

echo "🚀 Worker 배포"
npx wrangler@latest deploy

# 현재 떠있는 quick tunnel 이 있으면 KV 에 등록
TUN=$(grep -oh 'https://[a-z-]*\.trycloudflare\.com' /tmp/cf*.log 2>/dev/null | tail -1)
if [ -n "$TUN" ]; then
  echo "🔗 api_origin = $TUN"
  npx wrangler@latest kv key put api_origin "$TUN" --binding CFG --remote
fi

echo ""
echo "✅ 완료! 위 출력의 https://storyquant.<subdomain>.workers.dev 가 고정 주소입니다."
echo "   백엔드 상시 연결: deploy/tunnel-keeper.sh 를 백그라운드로 띄워두세요."
