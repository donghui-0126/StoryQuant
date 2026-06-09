# 중간보고서: StoryQuant

> 뉴스가 만든 시장 흐름을 자동으로 분류·집계·랭킹해 **"왜 움직였는가"**를 1초 안에 보여주는 KR/US 멀티시장 트레이딩 대시보드

| 항목 | 내용 |
|---|---|
| 과목 | 서비스데이터사이언스 |
| 학기 | 2026-1학기 |
| 팀명 | StoryQuant |
| 팀원·역할 | ✏️ 제출 전 채우기 |
| 제출일 | 2026. 05. 26 (화) |
| 발표 자료 | `presentation-full-dark.pdf` (18장) · `presentation.html` (라이브) · `presentation-full.mp4` (10분 14초) |

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 팀명 | StoryQuant |
| 팀원 및 역할 | ✏️ 본인 + 팀원 이름 / 데이터·모델·UI·배포 등 역할 기재 |
| 프로젝트명 | StoryQuant — 뉴스 기반 KR/US 멀티시장 트레이딩 대시보드 |
| 대상 사용자 | 한국·미국 시장을 동시에 추적하는 개인 데이트레이더 / 1인 매크로 투자자 |
| 해결하려는 문제 | 매일 수천 건의 헤드라인 정보 과부하 + 가격 움직임과 뉴스 인과 단절 |
| 서비스 한 줄 설명 | 실시간 뉴스를 호악재·실질성·카테고리·구체성·매체 신뢰도로 자동 분류하고, 가격 데이터와 결합한 종합 점수로 KR·US 횡단 랭킹 + 30~120일 백테스트로 검증된 신호 제공 |
| 현재 개발 단계 | 총 28개 추적 기능 중 22개 실제 구동 · KR 394 / US 165 종목 universe 실측 · 32+ 매체 RSS 5분 폴링 · 5개 분류 자동 라벨링 · 8 모드 walk-forward 백테스트 완성 · 외부 URL 라이브 서빙 |

---

## 2. 고객 니즈 및 제품 목표

### 2.1 어떤 사용자의 어떤 문제를 해결하려는가

**타겟 사용자**: KR과 US 시장을 동시에 추적해야 하는 개인 데이트레이더 / 1인 매크로 투자자.

**핵심 pain point**:
- KR 32+ 매체, US 22+ 매체 = 매일 **수천 건**의 헤드라인. 다 읽을 수 없음.
- 같은 종목에 호재·악재가 섞여 있을 때 **방향성 판단 시간 30초 이상**.
- "이미 다 반영된 뉴스"인지 "신선한 catalyst"인지 분간 어려움.
- 가격은 보이는데 **뉴스 ↔ 가격 인과**가 안 보임.
- 섹터 뉴스가 개별 종목 추천으로 연결 안 됨 (예: "2차전지株 약세" → 어느 종목?).

### 2.2 기존 서비스 / 대안의 한계

| 대안 | 한계 |
|---|---|
| 토스증권 AI 시그널 (2025-11) + 실시간 이슈 (2026-03) | **가장 가까운 경쟁자.** KR-only, 분석 결과가 블랙박스 요약이라 사용자가 alpha 직접 측정 불가. 2026-01 AI 오류 보도로 신뢰성 이슈도 존재. |
| Bloomberg Terminal | 월 $2,000+, 개인엔 비현실적 |
| Naver 금융 | 단순 chronological. 자동 분류·랭킹 없음 |
| 증권사 HTS 뉴스 | 종목별 시각화 없음, US 시장 부재 |
| ChatGPT 뉴스 요약 | 지연 + 환각, 검증 불가 |

### 2.3 우리 Web/App이 제공하려는 핵심 가치

> KR · US 시장의 단일 종목 또는 시장 전체 가격 움직임 뒤에 있는 **뉴스 흐름**을 자동으로 분류·집계·랭킹해, 개인 투자자가 **1초 안에 "왜 움직였는지"**를 파악하고 **30~120일 백테스트로 검증된 신호**로 의사결정할 수 있게 한다.

---

## 3. Product Goal → ML / AI Framing

### 3.1 ML 문제 정의

핵심은 하나의 **ranking 문제**:

```
f( 가격 · 뉴스 · 시장 분위기 )  →  종목별 종합 점수  →  상위 K개 매수 후보
```

뉴스 신호(input feature)는 5개 분류 작업의 출력을 종목·기간 단위로 집계해서 만든다.

| # | 작업 | input | → output | 접근법 |
|---|---|---|---|---|
| f₁ | Sentiment | 뉴스 텍스트 | bull / bear / neut + score [-1,1] | 룰 기반 (KR 50+ / US 60+ 키워드) |
| f₂ | Substance | 뉴스 텍스트 | substantive / reactive / neutral | 룰 기반 |
| f₃ | Category | 뉴스 텍스트 | 실적 · M&A · 임상규제 · 거시지정학 ...(7+) | 룰 기반 |
| f₄ | Specificity | 뉴스 텍스트 | [0..3] (숫자·금액·% 카운트) | regex 기반 |
| f₅ | Source reliability | 매체명 | [0..1] prior | hardcoded 50+ 매체 |
| f₆ | **Composite ranking** | (가격, 뉴스, macro) | 종목별 점수 → 상위 K개 | weighted blend + 통계 검증 |

### 3.2 가능한 ML/AI Formulation 비교

| 접근법 | 장점 | 한계 | 선택 |
|---|---|---|---|
| LLM 전용 (Claude / GPT) | 요약·해석 좋음, 환각 제어 가능 | 비용·지연·검증 어려움, KR 매체 fine-tune 부재 | 후순위 (한 줄 평 only) |
| Fine-tuned KR-FinBERT | 한국어 도메인 성능 높음 | 학습 데이터 라벨링 비용, 환경 재현 부담 | V2 검토 |
| SBERT 임베딩 + cosine 매칭 | 섹터/테마 뉴스 포섭 가능 | 임베딩 DB 별도, 동음이의 노이즈, alpha 검증 어려움 | 미채택 |
| **룰 기반 + 통계 검증 (IC)** | 설명 가능 · 빠른 iteration · 무료 · **백테스트로 적중률 직접 측정** | 한국어 형태소 분석 한계, 신조어 수동 추가 | **현재 MVP** |

### 3.3 현재 단계 선택 이유

"AI 활용"이 목적이 아니라 **사용자가 검증할 수 있는 신호**가 목적이다. 룰 기반으로 만든 polarity factor가 walk-forward IR = **+0.115**로 측정 가능한 alpha를 보여줬고, regime-conditional 분석에서 시장 위기 시기 한국 **+3.05%** · 미국 **+2.23%** (win rate 70%+) 초과 수익이 검증됐다. 이 baseline 위에서 향후 FinBERT pseudo-label로 substance 정밀도 개선이 다음 단계다.

---

## 4. 데이터 및 모델/AI 접근법

### 4.1 필요한 데이터 유형

- 종목 universe (티커, 이름, 시장, 시총)
- 시장 RSS 헤드라인 (실시간)
- 종목별 historical 뉴스 (최대 4년)
- OHLCV 가격 시계열
- 거시 지표 (VIX, 유가, 금리, USD index)

### 4.2 현재 확보 데이터

| 항목 | 한국 (KR) | 미국 (US) |
|---|---|---|
| Universe | 394 종목 — Naver Finance 스크래핑 | 165 종목 — Wikipedia S&P 500 + 시총 상위 100 hardcoded |
| 시장 RSS | 32개 (매경 4 · 파이낸셜뉴스 · 뉴시스 · 연합인포맥스 · 한겨레 + Google News 우회 20) | 22개 (Reuters · Bloomberg · WSJ · FT · CNBC · MarketWatch · IBD · ...) |
| 종목별 뉴스 | Naver mobile API (m.stock.naver.com) | Google News 검색 (news.google.com/rss/search?q=...) |
| 시총/PER/외인% | Naver scraping (실측) | **Stub — TODO 명시** |
| 가격 | Yahoo Finance v8 (.KS / .KQ) | Yahoo Finance v8 |
| Macro | ^VIX · CL=F (WTI) · ^TNX (10Y 금리) · DX-Y.NYB (DXY) — 양시장 공통 ||

### 4.3 라벨링 데이터 상태

**Weakly-labeled**: 키워드 기반 self-labeling. 정식 hand-labeled 학습 데이터셋 없음. → V2에서 KR-FinBERT 의사 라벨로 substance 정밀도 검증 예정.

### 4.4 데이터 저장 방식

- 24시간 메모리 캐시 (process-level)
- 7일 디스크 캐시 — `/tmp/sq_news_cache`, MD5 키
- 영구 DB 없음 (의도적 stateless 설계)

### 4.5 데이터 부족 / 품질 이슈

| 이슈 | 설명 |
|---|---|
| 데이터 소스 비대칭 | KR = Naver native API (한국 매체 통합), US = Google News 검색 — 같은 종목이라도 quality·분류 결과 다름 |
| 본문 부재 | RSS title + summary만 → 분류 정밀도 제한 (애로사항 §9 모델 정체의 일부 원인) |
| 섹터 뉴스 누락 | "2차전지株 약세" 같이 종목명 미명시 헤드라인은 종목별 API에 안 잡힘 |
| Historical 깊이 한계 | Naver mobile API는 최근 100건만 / 4년치는 Google News date-range로 별도, 첫 콜드런 30분 |
| 법적 회색지대 | Naver scraping robots.txt 모호, Google News TOS 회색 — V2에서 정식 라이선스 검토 필요 |

### 4.6 현재 사용 방식 (모델 / API / 룰 기반)

- **분류 5종**: 룰 기반 키워드 매칭 (KR 200+ keywords, US 130+ keywords) → 한 함수 `enrich_article()`에서 동시 적용 (5ms/건)
- **중복 제거**: `simple_dedup()` Jaccard 토큰 유사도 ≥ 0.55 + 48시간 윈도우
- **이미 반영 감지**: 뉴스 직전 5일 가격 변동과 sentiment 일치 여부로 priced_in 플래그
- **매크로 분위기**: VIX·유가·금리 기반 risk_off / risk_on / oil_up / rate_up 자동 분류
- **종합 랭킹**: 6 factor weighted blend — `0.30·mom5 + 0.20·mom20 + 0.25·polarity + 0.15·density + 0.10·vol_z + macro_adj − priced_in_penalty`
- **검증**: 14 factor IC + orthogonality matrix + regime-conditional alpha 자동 산정

### 4.7 향후 개선 방향

1. KR-FinBERT 의사 라벨로 substance 분류 정밀도 검증 (목표 IR > 0.3)
2. 합법적 historical 뉴스 라이선스 검토 (DART, FactSet 등)
3. 캐시 워밍 cron 자동화 (nightly fetch)
4. 본문 fetch 도입으로 분류 정밀도 향상

---

## 5. 서비스 구조: IA, User Flow, Wireframe

### 5.1 전체 메뉴 및 화면 구조 (Information Architecture)

```
StoryQuant 대시보드 (root, /story_quant.html)
├── 헤더 — 🇰🇷↔🇺🇸 시장 토글 · 인덱스 스트립 (KOSPI·KOSDAQ·USDKRW)
├── §278 한국 신문사 헤드라인 모니터 (메인 lobby)
│    ├── 매체 32개 RSS stream
│    ├── 5분류 자동 라벨 (호악재·실질성·카테고리·구체성·매체 신뢰도)
│    ├── 검색 / 필터 / 매체 분포 통계
│    └── 종목 태그 클릭 → 종목 상세 sticky panel
├── §282 테마 회전 모니터 — 14개 테마 바스켓 카드
├── §백테스트 (워크포워드) — 8 모드 신호 검증
│    └── 결과 5 패널 (자산 곡선, IC, 신호 중복도, 분위기별 alpha, 카테고리별 반감기)
└── 종목 상세 sticky panel (#knm-detail)
     ├── 차트 (LINE/CANDLE/VOL + MA20/60/RSI, 1d ~ 10y)
     ├── 종목별 뉴스 (KR=Naver mobile, US=Google News)
     └── 시세 메타 (KR 시총·PER·외인%, US 시총 stub)
```

### 5.2 핵심 사용자 시나리오

1. **아침 브리핑 (장 시작 전)** — 헤드라인 모니터에서 32 매체 신선 뉴스 + sentiment/category 자동 분류 확인. 시장 분위기 (위기 / 평온) 진단.
2. **"왜 움직였지?" (장중)** — 종목 클릭 → 종목별 뉴스 (priced_in 플래그 포함) + 차트 + 종합 신호. 섹터 뉴스 → 테마 회전으로 관련 종목 확장.
3. **신호 검증 (주말)** — 8 모드 백테스트 → IC, 위험 대비 수익, 분위기별 alpha, 상위/하위 그룹 수익 차 확인 후 다음 주 전략 결정.

### 5.3 화면 간 이동 및 기능 연결

전 화면이 단일 SPA (Single Page Application). URL 파라미터 `?market=kr|us`로 시장 토글, `localStorage('STORYQUANT_MARKET')`로 영속화. PWA manifest로 iOS 홈 화면 추가 가능. 헤드라인의 종목 태그를 클릭하면 sticky panel이 열리고, 테마 카드의 대표 종목 칩 클릭도 동일한 패널로 진입.

### 5.4 AI/ML 기능이 사용자 흐름 중 어느 지점에서 작동

- **모든 헤드라인** → `enrich_article()` 한 함수에서 5개 분류 동시 적용 (5ms/건)
- **종목 클릭 후 sticky panel** → priced_in 자동 판별 + 종합 점수 페널티 적용
- **매크로 진단** → VIX/유가/금리 기반 시장 분위기 자동 분류
- **백테스트 페이지 자체**가 모델 지표 대시보드 — 사용자가 8 모드를 토글하며 신호 적중률, 위험 대비 수익, 분위기별 alpha를 직접 측정

---

## 6. 현재 구현된 Web/App 기능

총 **28개 추적 기능**을 다섯 단계로 정직하게 구분.

| 구분 | 개수 | 예시 |
|---|---|---|
| **실제 구현** | **22** | HTTP 라우팅 12 endpoints · KR/US 시장 어댑터 분리 (v21.0) · KR universe (Naver scraping, 394 종목) · KR 시총/PER/외인% scraping · 32 RSS 폴링 · KR 종목별 뉴스 (Naver mobile API) · Yahoo Finance v8 chart (KR/US 공통) · 5개 ML 분류 · 종합 랭킹 sweep · 중복 제거 · priced-in 감지 · 매크로 분위기 분류 · macro beta 계산 · 8 모드 walk-forward 백테스트 · 24h 메모리 + 7d 디스크 캐시 · 3.7MB SPA + PWA · 모바일 반응형 · 시장 토글 · Cloudflare Worker 배포 |
| 부분 구현 | 3 | US universe (Wiki 스크래핑 + hardcoded TOP_BY_MCAP 100) · Paper trading (recent_picks ad-hoc만, 자동 누적 X) · Topic clustering (src/topics/ legacy, serve/ 통합 X) |
| Hardcoded | 1 | 매체 신뢰도 사전확률 50+ (Reuters 1.00 / 연합 1.00 / Bloomberg 0.95 / ...) |
| Stub | 1 | US 시총 `fetch_marketcap` (TODO 명시, 빈 quotes 반환) |
| 미구현 | 1 | LLM 한 줄 평 (README 약속, claude_hook.py stub만 존재) |

### 6.1 사용자가 실제로 수행 가능한 작업

1. 시장 토글 (KR ↔ US) — 한 클릭
2. 헤드라인 검색·필터·매체 분포 통계
3. 종목 태그 클릭으로 종목 상세 진입
4. 차트 모드 전환 (LINE/CANDLE/VOL + MA20/60/RSI), range 1d~10y
5. 종목별 뉴스 페이지네이션
6. 테마 카드 클릭 → 종목 바스켓 확인
7. 백테스트 8 모드 실행 → 결과 5 패널 분석

### 6.2 라이브 접속 URL

`https://likelihood-televisions-fcc-socks.trycloudflare.com/story_quant.html` (Cloudflare Tunnel)

API: `/api/news` · `/quote` · `/universe` · `/sweep` · `/walkforward` · `/macro`

---

## 7. 수업 내용 반영 매핑

강의에서 배운 단계들이 산출물의 어느 요소에 반영됐는지 — 단순 나열이 아닌 **설계 판단 → 구현 요소**의 연결.

| 수업 내용 | 설계 판단 | 구현 요소 |
|---|---|---|
| 고객 니즈 분석 | "정보 과부하 + 가격↔뉴스 단절"을 핵심 pain point로 정의 → 개인 데이트레이더 / 1인 매크로 투자자를 target으로 설정 | 헤드라인 모니터를 단순 list가 아닌 **자동 라벨링 stream**으로 설계 |
| 제품 목표 정의 | "AI 활용"이 아닌 "왜 움직였는지 1초 안에"라는 가치 중심 문장으로 정리 | 1초 내 narrative 확인 → 종목 클릭 → 백테스트 검증의 3-step flow로 압축 |
| ML Problem Framing | 제품 목표를 6개 task로 분해 (sentiment / substance / category / specificity / source-prior / ranking). 각 input/output 명시 | `serve/core/classify.py`의 `enrich_article()` 한 함수에서 f₁~f₅ 동시 적용, f₆은 `serve/core/strategy.py` |
| 데이터 검토 | 저작권·robots.txt 제약 검토 → Naver 직접 + Google News 우회 + Yahoo Finance v8(auth-free) 조합. 라벨링 데이터 부재 → 약한 라벨 MVP | 32 RSS, S&P 500 universe, 시장별 키워드 사전 (KR 200+, US 130+). 7일 disk 캐시 |
| ML 접근법 선택 | LLM-only / FinBERT / SBERT / Rule+IC 4 옵션 비교 → 설명 가능 + 백테스트 검증 가능한 Rule+IC 선택 | 14 factor IC orthogonality matrix · regime-conditional alpha decomposition · category half-life 자동 산정 |
| Business / Model Metric | Model: IC IR · Hit rate · Decile spread · Regime alpha. Business: 헤드라인→차트 클릭률, mystery-mover 클릭, 재방문률 | 백테스트 페이지가 곧 **모델 지표 대시보드**. 사용자가 자기 신호 신뢰도를 직접 확인 |
| IA / User Flow / Wireflow | 시장 토글 → 모니터 → 종목 → 백테스트의 4-step linear flow. ML 개입 지점 = 모니터(분류) + 백테스트(랭킹) | 3.7MB SPA + `?market=kr|us` URL routing + localStorage 영속화. PWA manifest로 iOS 홈화면 추가 |
| Vibe Coding | Claude Code를 활용해 v18 → v21.0 까지 7번 iteration. 대규모 리팩토링 + 시장 어댑터 분리 24h 안에 | monolith 1,872줄 → `serve/{utils,markets,core,api}` 모듈화. 시장 무관 코어 + 어댑터 패턴으로 US 추가 |
| Iteration Plan | "기능 추가 중단 → UI/UX 개선" 시점에 사용자(본인) 피드백으로 chrome 최소화. 정확도·정합성 양보 X | FAB·배너·온보딩 제거. PRO 모드 디폴트. story_quant.html 320 섹션 → 3 섹션으로 cut |

---

## 8. 성과 측정 계획: Business Metric과 Model Metric

### 8.1 Business Metric

서비스 성공 판단 기준 — 사용자 행동 지표.

- 가입자 / DAU (현재 본인 1명 → 베타 사용자 5명 목표)
- 헤드라인 → 차트 클릭률 (분류 정밀도가 클릭 결정에 미치는 영향)
- "Mystery mover" 클릭 후 체류 시간 (뉴스 부족한데 가격 움직인 종목 → 호기심 지표)
- 주간 재방문률 (서비스의 lock-in 강도)
- 백테스트 모드 변경 횟수 (사용자가 신호를 직접 검증한 강도)

### 8.2 Model Metric / AI Quality Metric

모델·AI 기능 품질 판단 기준.

| 지표 | 정의 | 현재 측정값 |
|---|---|---|
| **IC (Information Coefficient)** | factor와 forward return의 상관관계 | polarity factor 평균 IC 측정 중 |
| **IR (Information Ratio)** | IC 평균 / IC 표준편차 — 신호 일관성 | polarity **+0.115** (목표 0.3+) |
| Hit rate | IC > 0 기간 비율 | polarity 약 65% |
| Decile spread | Q5(상위) - Q1(하위) 평균 forward return | 측정 가능 |
| Category half-life | 카테고리별 평균 forward return + std | 실적·M&A·임상규제 등 7 카테고리 별 산정 |
| Regime-conditional alpha | 위기/평온/중립 분위기별 초과 수익 | **risk_off: KR +3.05% / US +2.23% (win 70%+)** |
| Latency | 분류 + 종합 점수 응답 시간 | 5ms / 헤드라인 · 백테스트 5분+ (개선 필요) |

### 8.3 두 지표의 연결

> Model Metric의 IR이 높아지면 (신호 적중률 향상) → 사용자가 종합 점수 상위 종목을 클릭할 확률 증가 → Business Metric인 헤드라인→차트 클릭률·재방문률 향상.
>
> 즉 사업 지표인 **"사용자가 신호 신뢰"**를 위해 **모델 지표 노출이 화면 구조의 핵심**이 됐고, 백테스트 페이지가 곧 모델 지표 대시보드 역할을 한다.

### 8.4 현재 측정 가능 vs 향후 측정 가능

| 지표 | 현재 | 최종 발표까지 |
|---|---|---|
| IC IR, Hit rate, Sharpe, decile, regime alpha | ✓ 백테스트 페이지에서 즉시 | — |
| Latency | ✓ 분류 5ms 측정 가능 | 백테스트 progressive streaming 도입 후 첫 응답 1초 이내 목표 |
| Paper trading win rate | ✗ recent_picks ad-hoc만 | 매일 Top-3 자동 누적 후 30일 forward win rate 측정 |
| 사용자 재방문률 · 클릭률 | ✗ 로그 영구 저장 X | 베타 사용자 5명 onboarding 후 주간 retention 측정 |

---

## 9. 현재 애로사항 및 Trouble Shooting 요청

| 유형 | 현재 문제 · 시도한 해결 | 필요한 도움 |
|---|---|---|
| **모델** | Polarity factor IR=**+0.115** (양수지만 약함). 목표 0.3 이상. **가설**: 룰 기반 substance 분류가 "매수 상향" 같은 analyst 의견을 substantive로 오분류. **시도**: 키워드 사전 확장 + 시간대 가중 도입 — 효과 marginal. | FinBERT 의사 라벨로 substance 분류 정밀도 검증 방법. labeled set 효율 구축법 (active learning 가능?). IR을 +0.3 이상으로 끌어올릴 feature 후보 추천. |
| **데이터** | Naver scraping은 robots.txt 회색지대. Google News는 rate limit · TOS 회색. Historical 뉴스 4년 fetch 첫 콜드런 30분. **시도**: 24h 메모리 + 7d 디스크 캐시 + ThreadPool 14 worker. | 한국·미국 뉴스 합법적 historical 라이선스 옵션 (DART, FactSet, Refinitiv 대안). 캐시 워밍 자동화 (cron nightly fetch). Vector DB로 substring 재검색 vs 다시 fetch 트레이드오프. |
| **기획** | 타겟 사용자 "개인 데이트레이더"가 너무 좁은지 / 너무 넓은지. "퀀트 호기심 일반인"으로 확장 시 백테스트 페이지 인지 부하. **시도**: PRO 모드 디폴트 / Lab 모드 분리, chrome 최소화. | Product scope 피드백. KR-only vs KR+US 동시 노출의 의사결정 부하 평가. |
| **종목 뉴스** | KR/US 데이터 소스 비대칭 (Naver native vs Google News 검색) + 본문 부재 + 섹터 뉴스 누락 + US 동음이의 노이즈 + Naver 100건 한정. | 본문 fetch 합법 라이선스. KR/US 분류 일관성 확보 방법. 종목명 미명시 섹터 뉴스를 universe 매칭으로 잡는 방법. |

---

## 10. 향후 개발 계획

### 10.1 우선순위 Action Plan

| # | 개발 항목 | 담당자 | 완료 목표 | 비고 |
|---|---|---|---|---|
| 1 | **Substance IR 0.3+** — FinBERT 의사 라벨로 substance 분류 정밀도 검증 | ✏️ | 5/31 | 필수 — alpha 핵심 |
| 2 | US 시총 scraping 구현 — 현재 stub 제거 | ✏️ | 6/03 | US treemap 완성 |
| 3 | story_quant.html 분해 — public/js/sections lazy load | ✏️ | 6/07 | 모바일 LCP < 2.5s |
| 4 | Paper trading 시그널 누적 — 매일 Top-3 저장 + forward return 측정 | ✏️ | 6/10 | 라이브 검증 |
| 5 | LLM 한 줄 평 — Claude Haiku 종목 카드 인라인 (선택) | ✏️ | 6/13 | API key 있을 때만 |
| 6 | **베타 사용자 5명** onboarding + 피드백 | 전체 | 6/15 | Business Metric 측정 |

### 10.2 최종 발표까지 반드시 완성

우선순위 #1, #2, #3, #6.

### 10.3 가능하면 완성할 추가 기능

우선순위 #4 (paper trading 자동 누적), #5 (LLM 한 줄 평).

### 10.4 축소 / 제거할 기능

- Topic clustering (src/topics/) — serve/ 통합 보류, 카테고리 분류로 충분
- 텔레그램 알림 — legacy README만 약속, 제거
- 온체인 / 고래 추적 — KR/US 주식 focus로 cut

### 10.5 사용자 테스트 계획

5명 베타 친구 (KR 트레이더) → 1주일 사용 후:
- 헤드라인 → 차트 클릭률 (자동 측정)
- "Mystery mover" 클릭 후 체류 시간
- "1주일 뒤 다시 쓸 의향" 정성 설문
- 가장 자주 본 섹션 + 가장 안 본 섹션 — IA 보강 방향 결정

### 10.6 최종 산출물 목표

- KR · US 두 시장 100% 동등 동작 (US 시총 stub 제거)
- 모바일 초기 렌더 LCP < 2.5초
- 실질 정보 신호 적중률 IR > 0.3 확보
- 5명 사용자 주간 재방문률 측정 가능 상태

---

> **요약**: 우리는 개인 KR · US 데이트레이더의 "왜 움직였는지 모르는 문제"를 해결하기 위해 이 dashboard를 만들고 있으며, 수업에서 학습한 고객 니즈 분석 → 제품 목표 정의 → ML/AI framing → 데이터 검토 → metric 설정 → IA/User Flow 설계 → Vibe Coding 구현 과정을 거쳐 **28개 추적 기능 / 22개 실제 구현 / 검증된 polarity factor (IR=+0.115)**의 중간 결과물에 도달했다. 남은 문제는 substance 정밀도 · US 시총 stub · 3.7MB SPA 분해 · 라이브 alpha 누적이며, 이 순서로 6월 15일까지 해결할 계획이다.
