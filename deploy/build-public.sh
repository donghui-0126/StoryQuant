#!/usr/bin/env bash
# shorts.html → worker/public 정적 빌드 (루트 접속 시에도 앱이 뜨도록 index.html 로도 복사)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/worker/public"
cp "$ROOT/shorts.html" "$ROOT/worker/public/shorts.html"
cp "$ROOT/shorts.html" "$ROOT/worker/public/index.html"
echo "✅ worker/public 빌드 완료"
