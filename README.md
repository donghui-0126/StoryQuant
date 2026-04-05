# StoryQuant

**뉴스 기반 멀티에셋 Hot Topic & Price Move Attribution Dashboard**

> **"시장 가격이 왜 움직였는가?"**
> 를 정량적으로 설명하고 투자 의사결정에 활용 가능한 형태로 제공한다.

---

## 1. 프로젝트 개요

실시간 뉴스 데이터를 수집하여 **1시간 단위 Hot Topic을 추출**하고,
크립토 / 국장 / 미장 주요 자산에서 **유의미한 가격 변동 이벤트 발생 시 그 원인을 자동으로 설명하는 대시보드**를 구축한다.

단순 뉴스 요약이 아니라, **뉴스 이벤트 ↔ 가격 움직임 Attribution**을 자동화한다.

### 핵심 가치

- 현재 시장의 **핵심 Hot Topic** 실시간 추적 (topic persistence, momentum, novelty)
- 특정 가격 변동의 **원인 자동 설명** (BTC 급등 → ETF 관련 뉴스, NVDA 급등 → AI capex 발언)
- macro / sector / idiosyncratic 이슈 분리

---

## 2. 핵심 기능

### A. Hot Topic Dashboard

1시간 단위 뉴스 데이터를 집계하여 제공:

| 기능 | 상태 | 설명 |
|------|------|------|
| 실시간 topic ranking | ✅ 구현 | TF-IDF + KMeans 클러스터링, 상위 5개 토픽 |
| 키워드 클러스터링 | ✅ 구현 | 의미 기반 topic labeling |
| 시장별 topic heatmap | ✅ 구현 | crypto / us / kr 필터링 |
| topic momentum score | ✅ 구현 | 시간대별 토픽 추세 |
| topic novelty score | ✅ 구현 | 신규 토픽 감지 |
| 중복 뉴스 제거 | ⚠️ 부분 | URL 기반만 (유사 헤드라인 클러스터링 미구현) |
| 한국어 토픽 추출 | ❌ 미구현 | 형태소 분석기 없음, 영어 불용어만 적용 |

### B. Price Move Attribution

가격 변화 이벤트 발생 시 자동 원인 분석:

| 이벤트 트리거 | 상태 | 기준 |
|--------------|------|------|
| 1h return > threshold | ✅ 구현 | ±2% 또는 2σ 이탈 |
| abnormal volume | ✅ 구현 | 24시간 평균 대비 2x 초과 |
| OI spike | ✅ 구현 | 미결제약정 급변 감지 |
| realized volatility shock | ❌ 미구현 | — |

| Attribution 방법 | 상태 | 설명 |
|-----------------|------|------|
| 관련 뉴스 후보 검색 | ✅ 구현 | 이벤트 발생 2시간 이내 뉴스 |
| 룰 기반 매핑 | ✅ 구현 | 티커 언급, 섹터, 시간 근접성, 키워드 매칭 |
| confidence score | ✅ 구현 | 4개 요소 가중 합산 |
| LLM 기반 요약 | ⚠️ 부분 | 감성 분석만 (원인 설명 요약 미구현) |

### C. 추가 구현 기능 (PoC 확장)

| 기능 | 설명 |
|------|------|
| Binance WebSocket | BTC/ETH/SOL 실시간 1분봉 스트리밍 |
| 파생상품 데이터 | 미결제약정, 롱숏비율, 청산 데이터 |
| 고래 추적 | Arkham Intelligence / Whale Alert 대형 전송 모니터링 |
| 거래소 공지 | Binance 신규 상장, 상폐, 에어드랍 감지 |
| 감성 분석 | 룰 기반 (50+ 키워드) + Claude Haiku LLM |
| Paper Trading | 시그널 기반 모의 트레이딩 |
| 텔레그램 알림 | 이벤트 발생 시 실시간 알림 |

---

## 3. 추적 자산 (10개)

| 시장 | 티커 | 종목명 | 섹터 |
|------|-------|--------|------|
| Crypto | BTC-USD | Bitcoin | Digital Asset |
| Crypto | ETH-USD | Ethereum | Smart Contract |
| Crypto | SOL-USD | Solana | Smart Contract |
| US Stock | NVDA | NVIDIA | AI / Semiconductor |
| US Stock | AAPL | Apple | Big Tech |
| US Stock | TSLA | Tesla | EV / Energy |
| US Stock | SPY | S&P 500 ETF | Index |
| KR Stock | 005930.KS | 삼성전자 | Semiconductor |
| KR Stock | 000660.KS | SK하이닉스 | Semiconductor |
| KR Stock | 035420.KS | 네이버 | Platform / AI |

---

## 4. 데이터 소스 (20+)

### 뉴스 RSS 피드 (6개, 5분 주기)

| 소스 | 시장 | URL |
|------|------|-----|
| CoinDesk | Crypto | coindesk.com/arc/outboundfeeds/rss/ |
| CoinTelegraph | Crypto | cointelegraph.com/rss |
| CNBC | US | cnbc.com/id/100003114/device/rss/rss.html |
| Reuters Business | US | feeds.reuters.com/reuters/businessNews |
| Naver Finance | KR | finance.naver.com (scraping) |
| MK Economy | KR | rss.mk.co.kr/rss/40300001.xml |

### 커뮤니티 & 미디어 (6개, 10분 주기)

| 소스 | 언어 |
|------|------|
| CoinGecko News | EN |
| The Block | EN |
| Decrypt | EN |
| 블록미디어 | KR |
| 토큰포스트 | KR |
| 코인데스크코리아 | KR |

### Twitter/X (6개 계정, 10분 주기)

| 계정 | 설명 |
|------|------|
| @whale_alert | 대규모 전송 알림 |
| @WatcherGuru | 크립토 속보 |
| @CryptoQuant_com | 온체인 분석 |
| @binance | 거래소 공지 |
| @DeItaone | Walter Bloomberg (매크로) |
| @FirstSquawk | 매크로 속보 |

> Nitter / RSSHub 기반 RSS 변환으로 수집

### 거래소 & 가격 데이터

| 소스 | 데이터 | 주기 |
|------|--------|------|
| Binance WebSocket | BTC/ETH/SOL 1분봉 캔들 | 실시간 |
| Binance Futures API | 미결제약정, 롱숏비율, 청산 | 5분 |
| Binance Announcements | 신규 상장(48), 뉴스(49), 상폐(161), 에어드랍(128) | 10분 |
| yfinance | 전 종목 OHLCV (5일, 1시간봉) | 15분 |

### 온체인 & 고래 추적

| 소스 | 데이터 | 최소 금액 | 주기 |
|------|--------|-----------|------|
| Arkham Intelligence (primary) | 대형 엔티티 전송 | $1,000,000 | 15분 |
| Whale Alert (fallback) | 대규모 트랜잭션 | — | 15분 |

**추적 엔티티:** Binance, Coinbase, Kraken, Bitfinex, Jump Trading, Wintermute, Alameda Research, Grayscale, BlackRock, MicroStrategy

---

## 5. 시스템 아키텍처

```
[Data Sources]                          [Polling Schedule]
  ├── RSS Feeds (뉴스 6개)               ← 5분
  ├── Community (커뮤니티 6개)            ← 10분
  ├── Twitter/X (6개 계정)               ← 10분
  ├── Binance Announcements              ← 10분
  ├── Binance WebSocket (3 symbols)      ← 실시간
  ├── Binance Futures API                ← 5분
  ├── yfinance (10 tickers)              ← 15분
  └── Arkham / Whale Alert               ← 15분
       │
       ▼
[Background Ingester] ─── 12 threads
  ├── news-poller          (5분)
  ├── price-poller         (15분)
  ├── twitter-poller       (10분)
  ├── exchange-poller      (10분)
  ├── community-poller     (10분)
  ├── binance-ws           (실시간)
  ├── derivatives-poller   (5분)
  ├── whale-poller         (15분)
  ├── paper-trader         (5분)
  ├── alert-dispatcher     (60초)
  ├── sentiment-scorer     (5분)
  └── topic-recomputer     (30분)
       │
       ▼
[SQLite DB] ─── 10 tables
  ├── articles          (뉴스/트윗)
  ├── prices            (OHLCV)
  ├── events            (가격 이벤트)
  ├── attributions      (뉴스-이벤트 매핑)
  ├── topics            (핫 토픽)
  ├── open_interest     (OI + 롱숏비율)
  ├── liquidations      (강제 청산)
  ├── whale_transfers   (대형 전송)
  ├── trades            (모의 트레이딩)
  └── historical_patterns
       │
       ▼
[Analysis Engine]
  ├── Event Detection    ── ±2% / 2σ / volume 2x
  ├── Attribution        ── ticker + sector + time + keyword → confidence
  ├── Sentiment          ── rule-based (50+ kw) + Claude Haiku LLM
  └── Topic Extraction   ── TF-IDF + KMeans → top 5 topics
       │
       ▼
[Streamlit Dashboard] ─── http://localhost:8501
  ├── Hot Topic Ranking & Heatmap
  ├── Price Move Attribution
  ├── 실시간 뉴스 피드
  ├── 파생상품 지표
  └── Telegram 알림 연동
```

---

## 6. AI 활용 포인트

### Hot Topic 추출
- 중복 뉴스 제거 (현재: URL 기반 → 개선 필요: 유사 헤드라인 클러스터링)
- 유사 headline clustering (TF-IDF + KMeans)
- 의미 기반 topic labeling

> 예: "Fed hold concern", "Powell hawkish" → **Fed Hawkishness**

### 가격 변동 원인 설명
- LLM이 아래 형태로 정리:

> BTC +4.2%
> 주요 원인: ETF inflow acceleration 관련 뉴스
> 보조 원인: short squeeze 가능성

현재 감성 분석(bullish/bearish/neutral)까지 구현, LLM 원인 요약은 확장 예정.

---

## 7. 성공 Metric

### 시스템 Metric

| Metric | 목표 | 현재 상태 |
|--------|------|-----------|
| Hot topic precision | 높음 | TF-IDF 기반 구현 (한국어 미지원) |
| Event-news matching accuracy | 높음 | 룰 기반 4요소 매핑 구현 |
| LLM attribution relevance | — | 감성 분석만 구현, 원인 요약 미구현 |
| Dashboard latency | <5min | 30초 캐시 TTL 구현 |

### 투자 활용 Metric

| Metric | 설명 | 현재 상태 |
|--------|------|-----------|
| topic persistence vs future return | 토픽 지속성과 수익률 상관관계 | ❌ `avg_return_24h` 미구현 (placeholder) |
| event attribution continuation probability | 귀인 이후 추세 지속 확률 | ❌ 미구현 |
| false catalyst rate | 잘못된 원인 매핑 비율 | ❌ 미구현 |
| signal hit ratio | Paper Trading 승률 | ✅ 구현 (trades 테이블) |

---

## 8. 알려진 이슈 & 개선 로드맵

### Critical

| 이슈 | 설명 |
|------|------|
| SQLite 멀티스레드 | 12개 스레드가 단일 커넥션 공유, 락 밖 읽기 존재 → 스레드별 커넥션 분리 필요 |
| WebSocket gap backfill | 100개 캔들(100분)만 복구 → 장시간 끊김 시 데이터 손실 |
| API 키 관리 | `python-dotenv` 미사용, `.env` 자동 로딩 없음 |

### High Priority

| 이슈 | 설명 |
|------|------|
| 데이터 무한 증가 | TTL/정리 없음, WS 기준 연간 ~1.6M행 누적 |
| 감성 키워드 부분 매칭 | "bull" → "bulletin" 오매칭 → word boundary 필요 |
| window_start 버그 | 새벽 0~5시에 6시간 윈도우 축소 → `timedelta` 사용 필요 |
| Attribution O(E×N) | 시간 윈도우 프리필터 없이 전체 탐색 |
| avg_return_24h | NaN 하드코딩 placeholder → 실제 구현 필요 |
| 뉴스 본문 미수집 | RSS title/summary만 사용, 분석 정확도 제한 |

### Medium Priority

| 이슈 | 설명 |
|------|------|
| 한국어 토픽 추출 | 형태소 분석기 미적용 (konlpy/mecab 필요) |
| LLM 원인 요약 | PRD 요구사항이나 감성 분석만 구현 |
| realized vol shock | 이벤트 트리거 미구현 |
| 대시보드 7일 전량 쿼리 | 30초마다 리로드 → 증분 로딩 필요 |
| Dashboard XSS | `unsafe_allow_html=True` → HTML 이스케이프 필요 |

---

## 9. 실행 방법

```bash
# 가상환경 설정
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 데이터 파이프라인 1회 실행
python run.py pipeline

# 대시보드만 실행
python run.py dashboard

# 백그라운드 수집 + 대시보드 (LIVE 모드)
python run.py live

# CSV → SQLite 마이그레이션
python run.py migrate

# 파이프라인 실행 후 대시보드 시작
python run.py all
```

## 10. 환경 변수

| 변수 | 용도 | 필수 |
|------|------|------|
| `ARKHAM_API_KEY` | Arkham Intelligence 고래 추적 | 선택 |
| `WHALE_ALERT_API_KEY` | Whale Alert 대규모 전송 조회 | 선택 |
| `ANTHROPIC_API_KEY` | Claude Haiku LLM 감성 분석 | 선택 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 봇 | 선택 |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID | 선택 |

## 11. Tech Stack

| 영역 | 기술 |
|------|------|
| Language | Python 3.12 |
| Database | SQLite (WAL mode) |
| Dashboard | Streamlit + Plotly |
| ML | scikit-learn (TF-IDF, KMeans) |
| Data | pandas, numpy, yfinance |
| Streaming | websockets (Binance) |
| Crawling | feedparser, requests |
| LLM | Anthropic Claude Haiku (선택) |
| Alert | Telegram Bot API |

## 12. 프로젝트 구조

```
StoryQuant/
├── run.py                      # 진입점 (pipeline / dashboard / live / migrate)
├── requirements.txt
├── src/
│   ├── pipeline.py             # 1회성 데이터 파이프라인
│   ├── background.py           # 12 스레드 백그라운드 인제스터
│   ├── crawlers/
│   │   ├── news_crawler.py     # RSS 뉴스 크롤러 (6개 피드)
│   │   ├── twitter_crawler.py  # Twitter/X 크롤러 (6개 계정)
│   │   ├── community_crawler.py # 커뮤니티 크롤러 (6개 소스)
│   │   └── exchange_crawler.py # Binance 공지 크롤러
│   ├── prices/
│   │   ├── price_fetcher.py    # yfinance OHLCV 수집
│   │   ├── binance_ws.py       # Binance WebSocket 실시간 캔들
│   │   ├── derivatives.py      # 미결제약정, 롱숏비율, 청산
│   │   ├── event_detector.py   # 가격 이벤트 감지 (±2% / 2σ / volume)
│   │   └── whale_tracker.py    # 고래 추적 (Arkham / Whale Alert)
│   ├── analysis/
│   │   ├── sentiment.py        # 감성 분석 (룰 기반 + LLM)
│   │   ├── correlation.py      # 뉴스-가격 상관관계 분석
│   │   ├── historical.py       # 패턴 분석
│   │   ├── market_view.py      # 시장 뷰 생성
│   │   ├── paper_trader.py     # 모의 트레이딩
│   │   └── claude_hook.py      # Claude LLM 연동
│   ├── topics/
│   │   └── topic_extractor.py  # TF-IDF + KMeans 토픽 추출
│   ├── attribution/
│   │   └── mapper.py           # 뉴스-이벤트 귀인 매핑
│   ├── alerts/
│   │   ├── dispatcher.py       # 알림 디스패처
│   │   └── telegram_bot.py     # 텔레그램 봇
│   ├── dashboard/
│   │   └── app.py              # Streamlit 대시보드
│   └── db/
│       ├── schema.py           # DB 스키마 (10 테이블)
│       ├── queries.py          # CRUD 쿼리
│       └── migrate_csv.py      # CSV → SQLite 마이그레이션
└── data/
    └── storyquant.db           # SQLite 데이터베이스 (gitignore)
```
