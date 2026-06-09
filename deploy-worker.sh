#!/usr/bin/env bash
# StoryQuant Worker (백엔드 API) 배포
# 배포되는 endpoint:
#   GET /api/quote?codes=005930,000660 — Yahoo Finance 분봉 프록시
#   GET /api/news?sources=hankyung,maeil,...  — KR 신문사 RSS 크롤링 + 분류

set -e
cd "$(dirname "$0")/worker"

echo "🚀 StoryQuant Worker 배포 (storyquant-api)"
echo "   첫 실행이면 Cloudflare 로그인 필요 (브라우저 자동 열림)"
echo ""

npx wrangler@latest deploy

echo ""
echo "✅ 배포 완료"
echo "📍 Endpoint URL은 위 출력의 'Published storyquant-api ...' 줄 확인"
echo "   보통: https://storyquant-api.<your-subdomain>.workers.dev"
echo ""
echo "🔗 HTML이 이 endpoint를 사용하려면:"
echo "   브라우저에서 dashboard 열고 콘솔에 입력:"
echo "   localStorage.setItem('STORYQUANT_API', 'https://storyquant-api.<your-subdomain>.workers.dev')"
echo "   그리고 새로고침"
