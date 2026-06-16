<div align="center">

# 📊 StoryQuant

### **가격이 왜 움직였는가, 뉴스는 얼마나 믿을 만한가**

뉴스 기반 KR 주식 모바일 분석 도구
가격 예측이 아닌 **노이즈 필터링 + 변동의 사후 설명(attribution)**

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![gpt-4o-mini](https://img.shields.io/badge/LLM-gpt--4o--mini-10a37f.svg)](https://platform.openai.com/)
[![Sector](https://img.shields.io/badge/sector-KRX_WICS-8a6418.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)
[![Mobile-First](https://img.shields.io/badge/mobile-first-ff4858.svg)](#)

</div>

---

## 💡 한 줄 요약

> 증권 뉴스의 70~90%는 잡음입니다. StoryQuant은 **읽을 가치 있는 실제 사건만 골라내고**,
> 가격이 왜 움직였는지를 뉴스로 사후 설명합니다. **예측은 하지 않습니다.**

TikTok 스타일 세로 reels UI에서 종목별 **실제 사건 헤드라인**과 **호재/악재 집계**, 그리고
그 분류의 **AI 판단 근거**까지 투명하게 보여줍니다.

---

## ✨ 핵심 기능

| | 설명 |
|:---:|---|
| 🎬 | **세로 reels 카드** — 실제 사건 헤드라인이 카드의 콘텐츠. "호재 N · 악재 N · 잡음 N건 걸러냄" |
| 🧠 | **gpt-4o-mini 분류** — `event_bull · event_bear · reactive · speculative · off_topic` 5단계 + scope(`stock · sector · macro`) |
| 🔎 | **분류 근거 + 한줄평** — 왜 호재/악재인지(또는 왜 제외인지)와 전문가 관점 한 줄 코멘트 |
| 📈 | **코스피·섹터 대비 상대수익률** — 절대 수익률이 아닌 alpha로 종목 고유 움직임 분리 |
| 📁 | **KRX WICS 섹터 분류** — 2,800종목 자동 매핑, 섹터 시트(같은 섹터 종목 + 업종 뉴스) |
| 🔔 | **저장 종목 새 소식 알림** — 실제 사건·큰 변동만 (최근 3일), 알림 피로 방지 |
| ⚡ | **이미 반영분 자동 차감** — `priced_in` 사건은 "실제 사건"에서 빼고 사유 표기 |
| 🎨 | **다크/라이트 모드 · Pretendard · 글씨 크기** — 설정 탭에서 조절 |
| 🌐 | **Cloudflare Worker 배포** — 고정 주소 1개로 정적 앱 + API 프록시 |

---

## 🧠 LLM은 어떻게 쓰이나

```
헤드라인/본문  ──▶  ① 분류        event_bull / event_bear / reactive / speculative / off_topic
                              + scope(stock/sector/macro) + confidence
              ──▶  ② 분류 근거   왜 그렇게 판단했는지 한 줄
              ──▶  ③ 한줄평      실제 사건에만 — 본문을 읽고 통찰 한 문장 (금융·경제·시사·사회 관점)
```

**신뢰성 장치**
- event 분류는 `confidence ≥ 0.7`일 때만 점수 반영 (애매하면 중립)
- 한줄평은 제목이 아닌 **본문**을 투입 → 막연한 코멘트 방지
- "확인 필요·지켜봐야" 류 **면피 표현**, 본문에 없는 **지어낸 비율("연매출의 24%")** 은 게이트에서 폐기
- 캐시 ~86,000 헤드라인 · sweep 1회 갱신 ≈ **$0.02** · 분류 temp 0 / 한줄평 temp 0.3

> 섹터 분류는 LLM이 아니라 **한국거래소 WICS 공식 업종**을 사용합니다 (`scripts/gen_sector_map.py`).

---

## 🎯 무엇을 버리고 무엇을 남겼나

자체 검증을 통해 **되는 것과 안 되는 것을 구분**했습니다.

| 🗑 폐기 (검증 실패) | ✓ 남김 (검증된 가치) |
|---|---|
| 미래 가격 예측 — forward R² < 0 (전 구간) | LLM 노이즈 필터 + 실제 사건 큐레이션 |
| 합성 뉴스 점수(0~100) — 예측력 미확인 | 호재/악재 **집계** (세어볼 수 있는 사실) |
| 이벤트 인과 타임라인 — placebo로 반증 | 코스피·섹터 대비 상대수익률 |
| 키워드 룰 호악재 — "급등=호재" 역인과 | mystery mover · 뉴스 과열 경고 |
| 커뮤니티 · 미장(US) 탭 — 핵심에 집중 | WICS 섹터 분류 · 분류 근거·신뢰도 공개 |

---

## 🏗 아키텍처

```
                ┌──────────────────────────────────────────┐
                │            shorts.html (모바일)          │
                │   ┌────┬────┬────┬────┬────┐             │
                │   │핫  │탐색│저장│설정│ 나 │             │
                │   └────┴────┴────┴────┴────┘             │
                └──────────────┬───────────────────────────┘
                               │ /api/sweep, /stock-news, /stock-one,
                               │ /saved-digest, /stock-chart, /universe
                ┌──────────────▼───────────────────────────┐
                │     serve/  —  Python stdlib HTTP        │
                │   ┌──────────────┬──────────────┐        │
                │   │  markets/    │   core/      │        │
                │   │  ─ kr.py     │  ─ strategy  │        │
                │   │  ─ kr_sectors│  ─ news      │        │
                │   │    (WICS)    │  ─ classify  │        │
                │   │  ─ base.py   │  ─ llm_class │        │
                │   │  (KR 전용)   │  ─ digest    │        │
                │   └──────────────┴──────────────┘        │
                └──────────────┬───────────────────────────┘
       ┌───────────────────────┼───────────────────────────┐
       ▼                       ▼                           ▼
  Yahoo Finance v8     Naver / Google News           OpenAI API
  (OHLC 차트)          (헤드라인 · WICS 업종)         (gpt-4o-mini)
```

---

## 📁 디렉토리 구조

```
storyquant/
├── shorts.html                  # 메인 모바일 UI (세로 reels)
├── serve.py                     # entry point — python serve.py 8765
├── serve/                       # backend 패키지
│   ├── api/handler.py           #   HTTP 라우터
│   ├── core/                    #   strategy · news · classify · llm_classify · digest · quote · macro
│   └── markets/                 #   kr · base · kr_sectors (WICS). us.py 는 보류(UI 비활성)
│
├── worker/                      # Cloudflare Worker — 정적 앱 + /api 프록시 (고정 주소)
├── deploy/                      # setup.sh · build-public.sh · tunnel-keeper.sh
│
├── docs/                        # 문서 · 발표
│   ├── final-presentation.html  #   최종 발표 슬라이드 (10장)
│   ├── report.md / report.html  #   보고서
│   └── ...
│
├── scripts/                     # gen_sector_map.py(WICS) · 캡쳐 · TTS
└── legacy/                      # v1(Streamlit) · v2(단일 HTML) · 구 RSS worker 보존
```

---

## ⚡ 빠른 시작

```bash
# 1. 환경
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. OpenAI 키 (LLM 분류용)
echo "OPENAI_API_KEY=sk-..." > .env

# 3. 서버 (부팅 시 KR sweep 캐시 자동 워밍)
python serve.py 8765
open http://127.0.0.1:8765/shorts.html

# 4. WICS 섹터 맵 갱신 (선택, 일회성)
python scripts/gen_sector_map.py
```

**배포 (Cloudflare Worker — 고정 주소)**

```bash
npx wrangler login          # 1회
bash deploy/setup.sh        # KV 생성 → 빌드 → 배포 → 터널 등록
bash deploy/tunnel-keeper.sh &   # 백엔드 터널 상시 유지 + 주소 변경 시 KV 자동 갱신
```

---

## 🔌 API

| Endpoint | 설명 |
|:---|:---|
| `GET /api/sweep?top_n=200&market=kr` | 종목별 집계 + 섹터 신호 (부팅 시 워밍) |
| `GET /api/stock-one?code=...` | 단일 종목 카드 데이터 (검색·섹터 → 릴 삽입용) |
| `GET /api/stock-news?code=...&page_size=50` | 종목 뉴스 (LLM 분류·근거·한줄평 적용) |
| `GET /api/saved-digest?codes=a,b,c` | 저장 종목 새 소식 (실제 사건 + 큰 변동, 최근 3일) |
| `GET /api/stock-chart?code=...&range=1mo` | OHLC 차트 |
| `GET /api/walkforward?...` | 1년 backtest + 회귀 (검증용) |

---

## 🧬 무엇을 측정하나 — "점수" 대신 "집계"

카드에는 **세어볼 수 있는 사실**만 표시합니다 (검증 실패한 합성 점수는 제거).

```
실제 사건  =  substantive(LLM event_*)  &  !priced_in
호재 N · 악재 N  =  실제 사건 중 sentiment 집계  (최신 20건 기준)
뉴스 분위기  =  (호재 - 악재) / (호재 + 악재 + 5) × 100   ← Bayesian shrinkage
                × (0.5 + 0.5 × 실질비율)
```

가격은 **집계에 넣지 않습니다.** 가격은 비교(verdict)에만 쓰입니다:

- **일치**: 좋은 사건 + 코스피 이김 → 분류와 시장 반응 합치
- **안 맞음**: 좋은 사건인데 코스피 못 이김 → 이미 반영 / 분류 오류 의심
- **원인 미상**: 뉴스 없이 가격만 움직임 (`mystery mover`)

**신뢰도** 는 표본 크기·실질 뉴스 비율·언론사 평균으로 자동 산정 (보류 / 낮음 / 보통 / 높음).

---

## 📊 검증 — 정직하게 깨부쉈다 (KR top-80 · 시계열 75/25 split)

| 검증 | 결과 | 결론 |
|:---|:---:|:---|
| forward 수익률 R² (1d / 5d / 20d) | **−0.055 / −0.031 / −0.008** | 미래 예측 불가 |
| past 설명 R² (뉴스만) | **+0.013** | 동시기 변동 일부 설명 |
| 이벤트 attribution placebo | 조용한 날이 뉴스 **더 많음** | 인과 근거 없음 |
| 노이즈 필터 (헤드라인 분류) | 70~90% 잡음 제거 | ✅ 검증된 가치 |

> 시계열 split + train 구간에만 scaler fit. random split의 leakage(+0.034)를 정직하게 교정한 수치.
> 미래를 맞추지 않습니다 — **이미 일어난 일을 정확히 읽습니다.**

---

## 🛠 기술 스택

- **Backend**: Python 3.12 stdlib `http.server`, `concurrent.futures` 병렬 fetch
- **LLM**: OpenAI `gpt-4o-mini` (분류 + 근거 + 한줄평, 디스크 캐시)
- **데이터**: Yahoo Finance v8 · Naver Finance(뉴스·WICS 업종) · Google News RSS
- **분석**: `scikit-learn`(검증용 회귀) · Bayesian shrinkage
- **Frontend**: Vanilla JS · CSS 변수 테마(다크/라이트) · Pretendard · 단일 파일
- **배포**: Cloudflare Worker(정적+프록시) + cloudflared tunnel
- **인증/광고**(설정 시): Firebase Google 로그인 · AdSense in-feed (config-gated)

---

## 🎯 철학

> "가격이 어디로 갈지"는 시장이 정합니다. 우린 그걸 알 수 없어요.
> 하지만 **"무엇이 진짜 사건이고 무엇이 잡음인지"** 는 정직하게 골라줄 수 있습니다.

검증 안 된 것은 주장하지 않습니다. 숫자 하나로 요약하는 대신,
**세어볼 수 있는 사실과 그 판단 근거**를 투명하게 보여줍니다.

---

## 📜 라이센스

MIT

---

<div align="center">

**Built with curiosity · 가격 예측은 사양합니다 · 뉴스를 정직하게 읽습니다**

</div>
