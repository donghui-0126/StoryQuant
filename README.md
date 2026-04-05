# StoryQuant

뉴스·소셜·온체인 데이터와 가격 변동을 실시간으로 연결하는 금융 내러티브 분석 플랫폼

## Overview

StoryQuant는 암호화폐·미국주식·한국주식 시장의 뉴스와 가격 데이터를 수집하고, **"어떤 뉴스가 가격 변동을 일으켰는가"** 를 자동으로 추적합니다.

- 12개 백그라운드 수집 스레드가 실시간으로 데이터를 수집
- TF-IDF 기반 토픽 추출 + 룰 기반/LLM 감성 분석
- 뉴스-이벤트 귀인(Attribution) 엔진으로 인과관계 추정
- Streamlit 대시보드에서 한눈에 확인

## 추적 자산

| 시장 | 티커 | 종목명 |
|------|-------|--------|
| Crypto | BTC-USD | Bitcoin |
| Crypto | ETH-USD | Ethereum |
| Crypto | SOL-USD | Solana |
| US Stock | NVDA | NVIDIA |
| US Stock | AAPL | Apple |
| US Stock | TSLA | Tesla |
| US Stock | SPY | S&P 500 ETF |
| KR Stock | 005930.KS | 삼성전자 |
| KR Stock | 000660.KS | SK하이닉스 |
| KR Stock | 035420.KS | 네이버 |

## 데이터 소스

### 뉴스 RSS 피드
| 소스 | 시장 | 주기 |
|------|------|------|
| CoinDesk | Crypto | 5분 |
| CoinTelegraph | Crypto | 5분 |
| CNBC | US | 5분 |
| Reuters Business | US | 5분 |
| Naver Finance | KR | 5분 |
| MK Economy | KR | 5분 |

### 커뮤니티 & 미디어
| 소스 | 유형 | 주기 |
|------|------|------|
| CoinGecko News | RSS | 10분 |
| The Block | RSS | 10분 |
| Decrypt | RSS | 10분 |
| 블록미디어 | RSS | 10분 |
| 토큰포스트 | RSS | 10분 |
| 코인데스크코리아 | RSS | 10분 |

### Twitter/X 계정
| 계정 | 설명 | 주기 |
|------|------|------|
| @whale_alert | 대규모 전송 알림 | 10분 |
| @WatcherGuru | 속보 | 10분 |
| @CryptoQuant_com | 온체인 분석 | 10분 |
| @binance | 거래소 공지 | 10분 |
| @DeItaone | Walter Bloomberg | 10분 |
| @FirstSquawk | 매크로 속보 | 10분 |

### 거래소 데이터
| 소스 | 데이터 | 주기 |
|------|--------|------|
| Binance WebSocket | BTC/ETH/SOL 실시간 캔들 (1분봉) | 실시간 |
| Binance Futures API | 미결제약정, 롱숏비율, 청산 | 5분 |
| Binance Announcements | 신규 상장, 상폐, 에어드랍 | 10분 |
| yfinance | 전 종목 OHLCV | 15분 |

### 온체인 & 고래 추적
| 소스 | 데이터 | 주기 |
|------|--------|------|
| Arkham Intelligence | 대형 엔티티 전송 ($1M+) | 15분 |
| Whale Alert (fallback) | 대규모 트랜잭션 | 15분 |

**추적 엔티티:** Binance, Coinbase, Kraken, Bitfinex, Jump Trading, Wintermute, Alameda Research, Grayscale, BlackRock, MicroStrategy

## 분석 엔진

| 모듈 | 설명 |
|------|------|
| Event Detector | 급등/급락(±2% or 2σ), 거래량 스파이크(2x 평균) 감지 |
| Attribution Mapper | 뉴스-이벤트 인과관계 추정 (티커 언급, 섹터, 시간 근접성, 키워드 매칭) |
| Sentiment Analyzer | 룰 기반(50+ 키워드) + Claude Haiku LLM 감성 분석 |
| Topic Extractor | TF-IDF + KMeans 클러스터링으로 핫 토픽 5개 추출 |
| Paper Trader | 시그널 기반 모의 트레이딩 |

## 아키텍처

```
[Data Sources]
  ├── RSS Feeds (뉴스/커뮤니티)
  ├── Twitter/X (Nitter/RSSHub)
  ├── Binance (WebSocket + REST)
  ├── yfinance (주가)
  └── Arkham/WhaleAlert (고래)
       │
       ▼
[Background Ingester] ─── 12 polling threads
       │
       ▼
[SQLite DB] ─── articles, prices, events, attributions,
       │        topics, open_interest, liquidations,
       │        whale_transfers, trades, historical_patterns
       ▼
[Analysis Engine]
  ├── Event Detection
  ├── Attribution Mapping
  ├── Sentiment Analysis
  └── Topic Extraction
       │
       ▼
[Streamlit Dashboard] ─── http://localhost:8501
```

## 실행 방법

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

## 환경 변수 (선택)

| 변수 | 용도 |
|------|------|
| `ARKHAM_API_KEY` | Arkham Intelligence 고래 추적 |
| `WHALE_ALERT_API_KEY` | Whale Alert 대규모 전송 조회 |
| `ANTHROPIC_API_KEY` | Claude LLM 감성 분석 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 봇 |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID |

## Tech Stack

- **Language:** Python 3.12
- **Database:** SQLite
- **Dashboard:** Streamlit + Plotly
- **ML:** scikit-learn (TF-IDF, KMeans)
- **Data:** pandas, numpy, yfinance
- **Streaming:** websockets (Binance)
- **Crawling:** feedparser, requests
