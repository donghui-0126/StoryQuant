<div align="center">

# 📊 StoryQuant

### **가격이 왜 움직였는가, 뉴스는 얼마나 믿을 만한가**

뉴스 기반 KR · US 주식 모바일 분석 도구
가격 예측이 아닌 **변동의 attribution** + **뉴스 quality** 평가

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![gpt-4o-mini](https://img.shields.io/badge/LLM-gpt--4o--mini-10a37f.svg)](https://platform.openai.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)
[![Mobile-First](https://img.shields.io/badge/mobile-first-ff4858.svg)](#)

</div>

---

## 💡 한 줄 요약

> 시장이 움직였을 때 **"왜?"** 를 즉시 답할 수 있는 모바일 reels-style 인터페이스.
> 가격을 예측하지 않고, **이미 일어난 가격 변동을 뉴스로 설명**합니다.

---

## ✨ 핵심 기능

| | 설명 |
|:---:|---|
| 🎬 | **TikTok 스타일 모바일 카드** — 종목별 점수·뉴스·섹터 정보 vertical scroll |
| 🧠 | **gpt-4o-mini 헤드라인 분류** — `event_bull · event_bear · reactive · speculative · off_topic` 5단계 + scope 분리 (`stock · sector · macro`) |
| 📈 | **코스피·섹터 대비 alpha** — 절대 수익률이 아닌 **상대 수익률** 평가 |
| 📁 | **섹터 sheet** — 업종 전체 호악재 + 종목 리스트 한눈에 |
| 🔬 | **Bayesian shrinkage polarity** — 1건짜리 호재가 +100점 받지 못하게 보정 |
| 📊 | **회귀 분석 endpoint** — Logistic / Linear 모델로 forward·past 시그널 정량 검증 |
| ⚡ | **이미 반영분 자동 차감** — `priced_in` 뉴스 점수에서 빼고 모달에서도 숨김 |
| 🌐 | **Cloudflared 즉시 배포** — `serve.py 8765` + tunnel 한 줄로 외부 공유 |

---

## 🏗 아키텍처

```
                ┌──────────────────────────────────────────┐
                │           shorts.html (모바일)           │
                │   ┌────┬────┬────┬────┬────┐             │
                │   │핫  │섹터 │탐색│저장│ 나 │             │
                │   └────┴────┴────┴────┴────┘             │
                └──────────────┬───────────────────────────┘
                               │ /api/sweep, /walkforward, /stock-news
                ┌──────────────▼───────────────────────────┐
                │     serve/  —  Python stdlib HTTP        │
                │                                          │
                │   ┌──────────────┬──────────────┐        │
                │   │  markets/    │   core/      │        │
                │   │  ─ kr.py     │  ─ news      │        │
                │   │  ─ us.py     │  ─ classify  │        │
                │   │  ─ base.py   │  ─ strategy  │        │
                │   │              │  ─ llm_class │        │
                │   └──────────────┴──────────────┘        │
                └──────────────┬───────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────────┐
       ▼                       ▼                           ▼
  Yahoo Finance v8       Naver / Google News         OpenAI API
  (OHLC 차트)            (헤드라인 RSS)              (gpt-4o-mini)
```

---

## 📁 디렉토리 구조

```
storyquant/
├── shorts.html                  # 메인 모바일 UI (vertical reels)
├── index.html                   # mobile/desktop redirect entry
├── serve.py                     # entry point — python serve.py 8765
├── serve/                       # backend 패키지
│   ├── api/handler.py           #   HTTP 라우터
│   ├── core/                    #   strategy · classify · news · llm_classify · macro
│   ├── markets/                 #   KR / US 시장 어댑터 (base · kr · us)
│   └── utils/                   #   http · parsing · stats
│
├── worker/                      # Cloudflare Worker (정적 호스팅 + KV)
├── deploy/                      # 배포 스크립트
│
├── docs/                        # 문서 · 발표 · 보고서
│   ├── report.md                       # 중간보고서
│   ├── consulting-questions.md         # UX 컨설팅 질문
│   ├── presentation.html               # 발표 슬라이드
│   ├── ux-mocks.html                   # UX 목업
│   ├── supabase-setup.md               # Supabase + Google OAuth 가이드
│   └── pdfs/                           # PDF 산출물
│
├── scripts/                     # 빌드 · 캡쳐 · TTS 유틸
│   ├── capture-*.mjs                   # playwright 캡쳐
│   ├── tts-generate.py                 # OpenAI TTS 나레이션
│   └── html-to-pptx.py                 # HTML → PowerPoint
│
└── legacy/                      # v1 (Streamlit · amure-db) · v2 (단일 HTML) 보존
    ├── src/                            # v1 pipeline
    ├── run.py / seed_*.py
    ├── serve.legacy.py                 # v2 단일 파일 backend
    └── story_quant.html                # v2 desktop SPA
```

---

## ⚡ 빠른 시작

```bash
# 1. 환경 준비
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. OpenAI API 키 설정 (LLM 분류용)
echo "OPENAI_API_KEY=sk-..." > .env

# 3. 서버 실행
python serve.py 8765

# 4. 모바일에서 열기 (LAN)
open http://<your-ip>:8765/shorts.html
```

### 외부 공유 (cloudflared)

```bash
cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate
# → https://<random>.trycloudflare.com 발급
```

---

## 🔌 API

| Endpoint | 설명 |
|:---|:---|
| `GET /api/sweep?top_n=120&market=kr` | 현재 시점 종목별 점수 + 섹터 신호 |
| `GET /api/walkforward?...&market=kr` | 1년 backtest + 회귀 분석 (Logistic/Linear) |
| `GET /api/stock-news?code=...&market=kr` | 종목 뉴스 (LLM 분류 적용) |
| `GET /api/stock-chart?code=...&range=1mo` | OHLC 차트 |
| `GET /api/recent-picks?lookbacks=5,10,20` | 과거 시점 픽 forward test |

---

## 🧬 점수 계산 — 무엇을 측정하나

```
news_rating  =  (bull - bear) / (bull + bear + 5)  ×  100      ← Bayesian shrinkage
             ×  (0.5 + 0.5 × sub_ratio)                          ← 실질 뉴스 가중

news_score   =  0.40 × news_rating
              + 0.25 × density
              + 0.15 × sub_ratio
              + 0.10 × source_reliability
              + 0.10 × specificity
              − priced_in_penalty
```

가격은 **점수에 포함하지 않음**. 가격은 점수와 매칭(verdict)에만 쓰임:

- **일치**: 좋은 뉴스 + 종목이 코스피 이김 → 신호 강함
- **불일치**: 좋은 뉴스 + 종목이 코스피 못 이김 → 이미 반영 / 분류 오류 의심
- **원인 미상**: 뉴스 없이 가격만 움직임 (`mystery mover`)

---

## 📊 회귀 분석 결과 (KR top-80 · n=1,927 · **시계열 75/25 split**)

| 모델 | R² test / F1 | baseline |
|:---|:---:|:---:|
| LIN forward alpha 1d / 5d / 20d | **−0.055 / −0.031 / −0.008** | — |
| LIN past mom5 (뉴스만, 가격 모멘텀 제외) | **+0.013** | 0 |
| LOG KOSPI 이김 | F1 = 0.401 | 0.348 |
| LOG 섹터 평균 이김 | F1 = 0.414 | 0.440 |

→ **미래 예측은 모든 horizon에서 불가** (R² 전부 음수).
→ 과거 변동 설명력은 약하지만 양수 (+0.013, train +0.016과 일치 — overfit 아님).

> ⚠ 초기엔 random split으로 past R² +0.034가 나왔으나, 시계열 데이터에 random split은
> look-ahead leakage를 일으킵니다. 시간 기준 split로 바꾼 정직한 수치가 위 표입니다.
> Scaler 도 train 구간에만 fit합니다.

### Event-driven attribution placebo 검증 (2026-06)

일 단위 ±2.5% 상대 변동을 직전 48h 사건 뉴스와 매칭하는 attribution도 검증했습니다:

| | 이벤트 날 | 조용한 날 (placebo) | lift |
|:---|:---:|:---:|:---:|
| 방향일치 뉴스 존재율 (상승) | 54% | 63% | **−9%p** |
| 방향일치 뉴스 존재율 (하락) | 40% | 51% | **−11%p** |
| 48h 사건 뉴스 양 | 7.2건 | 8.7건 | 음수 |

→ **대형주는 아무 날이나 사건 뉴스가 있습니다.** "변동일에 뉴스가 있다"는 것은
원인의 증거가 아니므로, UI는 "관련 뉴스 있음"이라고만 표기하고 인과를 주장하지 않습니다.
이 시스템의 검증된 가치는 **노이즈 필터링** (헤드라인 70%가 reactive/speculative/off_topic),
**mystery mover 탐지**, **뉴스 과열 경고**입니다.

---

## 🛠 기술 스택

- **Backend**: Python 3.12 stdlib `http.server` (no Flask), `concurrent.futures` parallel fetch
- **LLM**: OpenAI `gpt-4o-mini` (zero-shot 분류, temperature=0)
- **데이터 소스**: Yahoo Finance v8 · Naver Finance · Google News RSS · ^VIX · CL=F
- **분석**: `scikit-learn` (Logistic/Linear regression) · `numpy` (Bayesian shrinkage)
- **Frontend**: Vanilla JS · CSS Grid · No framework · ~100KB single file
- **배포**: Cloudflare Worker (정적) + Cloudflared tunnel (backend)
- **인증** (선택): Supabase + Google OAuth

---

## 🎯 철학

> "가격이 어디로 갈지" 는 시장이 결정합니다. 우린 그걸 알 수 없어요.
> 하지만 **"가격이 왜 움직였는지"** 는 뉴스로 사후 설명할 수 있습니다.

회귀 결과가 이 철학을 통계적으로 입증합니다:

- **forward R² < 0 (전 horizon)** → 가격 예측은 불가능
- **past R² > 0** → 동시기 가격 변동의 일부(~1.3%)는 뉴스로 설명 가능
- **시스템은 attribution + quality 평가에 집중** — UI에도 "사후 설명 · 예측 아님"을 명시

가격을 맞추는 게 아니라 **이미 일어난 일을 정확히 해석**합니다.

---

## 📜 라이센스

MIT

---

<div align="center">

**Built with curiosity · 가격 예측은 사양합니다 · 뉴스를 정직하게 읽습니다**

</div>
