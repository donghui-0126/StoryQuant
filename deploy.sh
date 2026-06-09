#!/usr/bin/env bash
# Cloudflare Pages 1회 배포 스크립트
set -e
PROJECT="storyquant"
DIST="$(dirname "$0")/dist"

echo "📦 dist 폴더 빌드 (story_quant.html → index.html)"
cp story_quant.html dist/index.html

echo "🚀 Cloudflare Pages 배포 시작"
echo "   첫 실행이면 브라우저가 열려서 Cloudflare 로그인을 요청합니다."
echo "   (계정이 없다면 무료 가입: https://dash.cloudflare.com/sign-up)"
echo ""

# wrangler 설치돼있지 않으면 npx로 임시 실행
npx wrangler@latest pages deploy "$DIST" \
  --project-name "$PROJECT" \
  --branch "main" \
  --commit-dirty=true
