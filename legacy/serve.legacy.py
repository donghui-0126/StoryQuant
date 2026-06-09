#!/usr/bin/env python3
"""
StoryQuant 로컬 서버 — 정적 HTML + 실 데이터 API 프록시.

기존 `python3 -m http.server 8765` 대체. 추가 endpoint:

  GET /api/news?sources=mk,fnnews,...&limit=80
  GET /api/quote?codes=005930,000660,...

브라우저는 이 서버를 같은 origin으로 보므로 CORS 문제 없음.
의존성 0 — 표준 라이브러리만 사용.

실행:
  python3 serve.py [PORT]    (기본 8765)
"""
import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ROOT = '/home/amuredo/StoryQuant'

# ─── KR 신문사 RSS 매핑 ──────────────────────────────────
# 2026-04-30 검증된 작동 피드만. CF bot block / 404 매체는 제외.
RSS_FEEDS = {
    # 매일경제 (4 카테고리)
    'mk':          'https://www.mk.co.kr/rss/30000023/',         # 매경 증권
    'mk_econ':     'https://www.mk.co.kr/rss/30100041/',         # 매경 경제일반
    'mk_industry': 'https://www.mk.co.kr/rss/40300001/',         # 매경 산업
    'mk_general':  'https://www.mk.co.kr/rss/30000001/',         # 매경 종합
    # 파이낸셜뉴스
    'fnnews':   'https://www.fnnews.com/rss/r20/fn_realnews_stock.xml',
    'fn_econ':  'https://www.fnnews.com/rss/r20/fn_realnews_economy.xml',
    # 이데일리: RSS endpoint dead (HTML redirect) — 2026-04-30 제거
    # 뉴시스
    'newsis':   'https://www.newsis.com/RSS/economy.xml',
    # 연합인포맥스 (금융전문)
    'einfomax': 'https://news.einfomax.co.kr/rss/allArticle.xml',
    # 한겨레 경제
    'hani':     'https://www.hani.co.kr/rss/economy/',
    # 시사저널 (전체)
    'sisajournal': 'https://www.sisajournal.com/rss/allArticle.xml',
    # 시사IN (전체)
    'sisain':   'https://www.sisain.co.kr/rss/allArticle.xml',
    # KD프레스 (소형 매체, 인기)
    'kdpress':  'https://www.kdpress.co.kr/rss/clickTop.xml',
    # ─── Google News RSS 우회: 직접 RSS가 막힌 매체들 ───
    'gn_hankyung':  'https://news.google.com/rss/search?q=site:hankyung.com+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_chosunbiz': 'https://news.google.com/rss/search?q=site:biz.chosun.com&hl=ko&gl=KR&ceid=KR:ko',
    'gn_yna':       'https://news.google.com/rss/search?q=site:yna.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_sedaily':   'https://news.google.com/rss/search?q=site:sedaily.com+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_edaily':    'https://news.google.com/rss/search?q=site:edaily.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_mt':        'https://news.google.com/rss/search?q=site:mt.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_asiae':     'https://news.google.com/rss/search?q=site:asiae.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_herald':    'https://news.google.com/rss/search?q=site:heraldcorp.com+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
}

# Google News는 title이 "헤드라인 - 매체명" 형태 → 분리. 직접 RSS는 다른 처리.
GNEWS_PAPER_MAP = {
    'gn_hankyung':  '한경',
    'gn_chosunbiz': '조선비즈',
    'gn_yna':       '연합',
    'gn_sedaily':   '서경',
    'gn_edaily':    '이데일리',
    'gn_mt':        '머투',
    'gn_asiae':     '아시아경제',
    'gn_herald':    '헤럴드',
}

# 시드 KR_TICKERS — universe loader 실패 시 fallback. 정상이면 fetch_universe()가 채움.
KR_TICKERS = {
    '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션',
    '006400':'삼성SDI','051910':'LG화학','207940':'삼성바이오로직스',
    '068270':'셀트리온','005380':'현대차','000270':'기아',
    '005490':'POSCO홀딩스','003670':'포스코퓨처엠','012330':'현대모비스',
    '012450':'한화에어로스페이스','034020':'두산에너빌리티','267260':'HD현대일렉트릭',
    '010120':'LS ELECTRIC','079550':'LIG넥스원','047810':'한국항공우주',
    '042660':'한화오션','009540':'HD한국조선해양','010140':'삼성중공업',
    '066570':'LG전자','105560':'KB금융','055550':'신한지주',
    '086790':'하나금융지주','316140':'우리금융지주','035420':'네이버',
    '035720':'카카오','352820':'하이브','259960':'크래프톤',
    '036570':'엔씨소프트','086520':'에코프로','247540':'에코프로비엠',
    '196170':'알테오젠','058470':'리노공업','042700':'한미반도체',
    '011200':'HMM','015760':'한국전력','323410':'카카오뱅크',
    '028300':'HLB','326030':'SK바이오팜'
}

# Universe (Naver KOSPI + KOSDAQ 시총 상위 N) — 백그라운드로 채워짐.
UNIVERSE = {}    # code → {'name', 'market', 'cap'}
UNIVERSE_TS = 0


def fetch_universe(top_per_market=200):
    """Naver 시가총액 페이지 스크래핑. KOSPI sosok=0, KOSDAQ sosok=1.
       각 시장 상위 top_per_market 까지 (페이지당 50)."""
    out = {}
    pages = (top_per_market + 49) // 50
    sock_pat = re.compile(r'<a[^>]+href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>')
    cap_pat = re.compile(r'<a[^>]+href="/item/main\.naver\?code=(\d{6})".*?<td[^>]*class="number"[^>]*>([\d,]+)</td>', re.S)

    def fetch_one(market_code, page):
        market_name = 'KOSPI' if market_code == 0 else 'KOSDAQ'
        url = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok={market_code}&page={page}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 StoryQuant'})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
            html = raw.decode('euc-kr', errors='replace')
            results = []
            for m in sock_pat.finditer(html):
                code, name = m.group(1), decode_entities(m.group(2)).strip()
                if name:
                    results.append({'code': code, 'name': name, 'market': market_name})
            return results
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = []
        for market in (0, 1):
            for p in range(1, pages + 1):
                futs.append(ex.submit(fetch_one, market, p))
        for f in as_completed(futs):
            for item in f.result():
                if item['code'] not in out:
                    out[item['code']] = item
    return out


def reload_universe():
    """매 24h 한 번만 실제로 fetch. 시작 시 한 번 + 24h 마다."""
    global UNIVERSE, UNIVERSE_TS
    try:
        u = fetch_universe(top_per_market=200)
        if u and len(u) > 50:
            UNIVERSE = u
            UNIVERSE_TS = time.time()
            # KR_TICKERS도 업데이트해서 tag_tickers에서 활용
            for code, info in u.items():
                KR_TICKERS[code] = info['name']
            print(f'[Universe] loaded {len(u)} tickers (KOSPI+KOSDAQ top 200×2)')
    except Exception as e:
        print(f'[Universe] load failed: {e} — using seed list ({len(KR_TICKERS)} tickers)')

BULL_KEYS = ['급등','상승','돌파','신고가','강세','반등','상한가','최고가','호재','어닝서프라이즈','서프라이즈','흑자전환','흑자','수주','수출 증가','실적개선','실적 개선','최대실적','사상최대','사상 최대','역대 최대','성장','확대','증가','급증','신기록','매수','상향','목표가 상향','투자의견 상향','비중확대','추천','수혜','기대감','낙관','긍정적','승인','통과','체결','신규상장','재상장','편입']
BEAR_KEYS = ['급락','하락','폭락','약세','조정','하한가','최저가','신저가','악재','어닝쇼크','쇼크','적자','적자전환','감익','역성장','실적부진','실적 부진','어닝미스','가이던스 하향','수주 감소','감소','축소','둔화','위축','매도','하향','목표가 하향','투자의견 하향','비중축소','비관','리스크','우려','부정적','경계','규제','금지','제재','벌금','기소','조사','수사','압수수색','상장폐지','거래정지','감자','워크아웃','법정관리']

# v20.4 — Reactive (사후적, 가격 묘사만) vs Substantive (새로운 정보) 분류
# 가설 (사용자): 급등/급락 자체를 보도하는 사후 뉴스는 정보 가치 0. 실질 정보가 누적될 때 진짜 신호.
REACTIVE_KEYS = [
    # 가격 동작 묘사 (post-facto)
    '급등','급락','폭등','폭락','강세','약세','반등','반락',
    '상승세','하락세','오름세','내림세','상승전환','하락전환',
    '신고가','신저가','52주 신고','52주 신저','상한가','하한가',
    '랠리','폭주','급반등','급락세',
    # 차트/기술 분석만
    '차트','캔들','저항선','지지선','골든크로스','데드크로스',
    # 시장 묘사
    '특징주','관심주','이슈주','테마주 부각',
    # 거래량 묘사 (사후)
    '거래량 급증','거래량 폭증','대량매수','대량매도',
    # 단순 묘사
    '주가 급등','주가 폭등','주가 강세','주가 상승','주가 하락',
]
SUBSTANTIVE_KEYS = [
    # 실적/회계 (hard facts)
    '영업이익','영업익','매출','순익','순이익','EPS','어닝서프라이즈','어닝쇼크',
    '컨센서스','가이던스','분기 실적','연간 실적','실적 발표',
    # 사업 활동
    '수주','계약','체결','공급','MOU','파트너십','협력 체결','합작',
    '신제품','출시','런칭','공개','발표','선보여',
    '인수','합병','M&A','매각','지분 매입','지분 인수','블록딜',
    # 임상/규제
    '임상','FDA','승인','신약','특허','품목허가','3상','2상','1상',
    '규제','제재','벌금','기소','조사','수사','압수수색',
    # 거버넌스/인사
    '대표','CEO','회장','사임','선임','이사회','인사','임원변경',
    # 자본/주주환원
    '배당','자사주 매입','자사주 소각','유상증자','무상증자','감자',
    '주총','주주총회','주식 분할','액면분할',
    # 정부/정책
    '정책','법안','국회','예산','규제 완화','지원','보조금',
    # 신기술/혁신
    'AI 모델','신기술','특허 등록','개발 성공','개발성공',
    # 자금/투자
    '투자 유치','자금 조달','상장','IPO','공모',
]


def classify_substance(text):
    """뉴스 분류: substantive (실질 정보) / reactive (가격 묘사만) / neutral (기타).
       substantive 키워드가 있으면 substantive (reactive 키워드 함께 있어도 substance 우선).
       reactive만 있으면 reactive. 둘 다 없으면 neutral."""
    if not text:
        return 'neutral'
    has_sub = any(k in text for k in SUBSTANTIVE_KEYS)
    has_react = any(k in text for k in REACTIVE_KEYS)
    if has_sub:
        return 'substantive'
    if has_react:
        return 'reactive'
    return 'neutral'


# ───────────────────────────────────────────────────────────────────────────
# v20.5 — Alpha enrichment scoring (13 research directions, A1/A2/A3/B3/D1)
# ───────────────────────────────────────────────────────────────────────────

# A1 — Specificity: 구체성 (숫자/금액/% 포함). 0..3.
_NUM_AMOUNT = re.compile(r'\d{1,4}(?:,\d{3})*(?:\.\d+)?\s*(?:조|억|만|천)\s*(?:원|달러|엔|위안)?')
_NUM_USD = re.compile(r'\$\s*\d|\d{1,4}(?:,\d{3})*(?:\.\d+)?\s*(?:USD|달러)')
_PCT = re.compile(r'\d+(?:\.\d+)?\s*%')
_QTR = re.compile(r'(?:1Q|2Q|3Q|4Q|\d+분기|\d+년\s*\d+분기|상반기|하반기|FY\d{2,4})')
_BIG_NUM = re.compile(r'\b\d{3,}\b')

def specificity_score(text):
    """구체성 점수: 0..3. 숫자/금액/% 많을수록 alpha."""
    if not text:
        return 0.0
    s = 0.0
    if _NUM_AMOUNT.search(text):
        s += 1.0
    elif _NUM_USD.search(text):
        s += 0.6
    pct = len(_PCT.findall(text))
    s += min(1.0, pct * 0.5)
    if _QTR.search(text):
        s += 0.5
    big = len(_BIG_NUM.findall(text))
    s += min(0.5, big * 0.2)
    return round(min(3.0, s), 2)


# A2 — Source reliability prior. 정통 일간지/통신사 = high. 인터넷 매체 = mid/low.
SOURCE_PRIORS = {
    # 통신사·정통 일간지 (high reliability)
    '연합뉴스': 1.00, '연합인포맥스': 0.95, 'yna': 1.00,
    '한국경제': 0.92, '한경': 0.92, 'hankyung': 0.92, 'gn_hankyung': 0.92,
    '매일경제': 0.92, '매경': 0.92, 'mk': 0.92, 'gn_maeil': 0.92,
    '조선비즈': 0.85, 'gn_chosun': 0.85,
    '이데일리': 0.85, 'edaily': 0.85,
    '서울경제': 0.82, 'sedaily': 0.82,
    '파이낸셜뉴스': 0.80, 'fnnews': 0.80,
    '뉴시스': 0.85, 'newsis': 0.85,
    '머니투데이': 0.75, 'mt': 0.75,
    'KBS': 0.85, 'SBS': 0.82, 'MBC': 0.82, 'YTN': 0.82,
    # 일반 (default)
    'GNews': 0.55, 'gnews': 0.55,
}
def source_reliability(paper):
    """매체 priors 매핑. unknown은 0.50 (mid)."""
    if not paper:
        return 0.50
    p = paper.strip()
    if p in SOURCE_PRIORS:
        return SOURCE_PRIORS[p]
    pl = p.lower()
    if pl in SOURCE_PRIORS:
        return SOURCE_PRIORS[pl]
    # 부분 매칭 (Google News의 "한국경제 - HK" 같은 변형)
    for k, v in SOURCE_PRIORS.items():
        if k in p:
            return v
    return 0.50


# A3 — Surprise: substantive + 충분 specific + non-routine 토큰
# routine 키워드 (기대했던 정보 = 덜 surprise)
_ROUTINE_KEYS = ('실적 발표', '분기 실적', '컨센서스', '예상', '전망', '가이던스')
# 고-surprise 키워드 (예상 밖 사건)
_BIG_SURPRISE = ('서프라이즈', '쇼크', '급증', '급감', '사상 최대', '사상최대', '역대 최대',
                 '리콜', '소송', '제재', '벌금', '압수수색', '구속', '기소', '배임', '횡령',
                 'M&A', '인수', '합병', 'FDA', '품목허가', '특허 승인', '신고가', 'IPO',
                 '회장 사임', '대표 사임', '갑작스럽', '돌연')
def surprise_score(text, substance, specificity):
    """예상 밖 점수: 0..3. substantive·specific·shock 키워드 다수 → 높음."""
    if not text:
        return 0.0
    s = 0.0
    # base: substance × specificity 보너스
    if substance == 'substantive':
        s += 0.5 + min(1.0, specificity * 0.3)
    big_hits = sum(1 for k in _BIG_SURPRISE if k in text)
    s += min(1.5, big_hits * 0.7)
    # routine 키워드 있으면 감점 (이미 예상된 정보)
    if any(k in text for k in _ROUTINE_KEYS):
        s -= 0.4
    return round(max(0.0, min(3.0, s)), 2)


# D1 — News Spectrum: 7개 카테고리. 종목 detail에 분포 시각화.
NEWS_CATEGORIES = ('실적', 'M&A', '임상·규제', '인사·거버넌스', '배당·자본', '신제품·사업', '기타')
_CAT_KEYS = {
    '실적': ('영업이익', '영업익', '매출', '순이익', 'EPS', '어닝', '컨센서스', '가이던스',
            '분기 실적', '연간 실적', '실적 발표', '흑자전환', '적자전환', '사상최대', '사상 최대'),
    'M&A': ('인수', '합병', 'M&A', '매각', '지분 매입', '지분 인수', '블록딜', '경영권', '딜'),
    '임상·규제': ('임상', 'FDA', '신약', '품목허가', '3상', '2상', '1상', '특허',
                '규제', '제재', '벌금', '기소', '조사', '수사', '압수수색', '리콜', '승인'),
    '인사·거버넌스': ('대표', 'CEO', '회장', '사임', '선임', '이사회', '임원', '주총',
                    '주주총회', '경영', '이사 선임'),
    '배당·자본': ('배당', '자사주', '소각', '유상증자', '무상증자', '감자', '액면분할', '주식 분할'),
    '신제품·사업': ('수주', '계약', '체결', '공급', 'MOU', '파트너십', '협력', '신제품',
                  '출시', '런칭', '공개', '발표', '신기술', 'AI 모델', '개발 성공'),
}
def categorize_news(text):
    """뉴스 카테고리: 7종 중 하나. 첫 매칭 우선 (순서: 실적 > M&A > 임상 > 인사 > 배당 > 신제품 > 기타)."""
    if not text:
        return '기타'
    for cat in ('실적', 'M&A', '임상·규제', '인사·거버넌스', '배당·자본', '신제품·사업'):
        if any(k in text for k in _CAT_KEYS[cat]):
            return cat
    return '기타'


# B3 — Time-of-day bucket. KR 시장 09:00-15:30. pre/intra/after.
def time_of_day_bucket(ts_ms):
    """장 시간 기반 bucket: 'pre'(00-09)/'intra'(09-15)/'after'(15-24). KST 기준."""
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=9)))
        h = dt.hour + dt.minute / 60.0
        if h < 9.0:
            return 'pre'
        if h < 15.5:
            return 'intra'
        return 'after'
    except Exception:
        return 'intra'


# E2 — Simple dedup: 제목 prefix 8단어 동일이면 같은 article로 묶음
def simple_dedup(articles, prefix_words=8):
    """비슷한 제목 dedup. 같은 prefix면 가장 신뢰도 높은 1개만 keep."""
    seen = {}
    out = []
    for a in articles:
        title = (a.get('title') or '').strip()
        if not title:
            continue
        key = ' '.join(title.split()[:prefix_words])[:60]
        prev = seen.get(key)
        if prev is None:
            seen[key] = len(out)
            out.append(a)
        else:
            # 더 신뢰도 높은 매체로 swap (또는 specificity 더 높은 것)
            cur_score = (a.get('source_score') or 0.5) + (a.get('specificity') or 0) * 0.2
            old = out[prev]
            old_score = (old.get('source_score') or 0.5) + (old.get('specificity') or 0) * 0.2
            if cur_score > old_score:
                a = dict(a)
                a['_dup_count'] = (old.get('_dup_count') or 1) + 1
                out[prev] = a
            else:
                out[prev]['_dup_count'] = (old.get('_dup_count') or 1) + 1
    return out


def enrich_article(art):
    """article에 specificity / surprise / source_score / category / tod 추가. inline mutate."""
    text = (art.get('title') or '') + ' ' + (art.get('body') or art.get('description') or '')
    spec = specificity_score(text)
    sub = art.get('substance') or 'neutral'
    art['specificity'] = spec
    art['surprise'] = surprise_score(text, sub, spec)
    art['source_score'] = source_reliability(art.get('paper') or art.get('source') or '')
    art['category'] = categorize_news(text)
    art['tod'] = time_of_day_bucket(art.get('ts') or int(time.time() * 1000))
    return art


def classify(text):
    if not text:
        return ('neut', 0)
    bull = sum(1 for k in BULL_KEYS if k in text)
    bear = sum(1 for k in BEAR_KEYS if k in text)
    total = bull + bear
    if total == 0:
        return ('neut', 0)
    score = (bull - bear) / total
    if score > 0.2:
        return ('bull', round(score, 2))
    if score < -0.2:
        return ('bear', round(score, 2))
    return ('neut', round(score, 2))


def tag_tickers(text):
    """Universe 기반 자동 태깅. 너무 짧은 이름은 false-positive 방지차 skip."""
    if not text:
        return []
    out = []
    seen = set()
    # 긴 이름부터 매칭 (조선 vs 조선해양 같은 부분일치 회피)
    items = sorted(KR_TICKERS.items(), key=lambda kv: -len(kv[1]))
    for code, name in items:
        if len(name) < 3:
            continue
        if name in text and code not in seen:
            out.append({'code': code, 'name': name})
            seen.add(code)
            if len(out) >= 6:
                break
    return out


def http_get(url, timeout=8, extra_headers=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) StoryQuant/1.0',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.5',
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_rss(xml_text, source_key):
    is_gnews = source_key.startswith('gn_')
    items = []
    for m in re.finditer(r'<item[^>]*>(.*?)</item>', xml_text, re.S):
        body = m.group(1)
        title_m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S)
        link_m = re.search(r'<link[^>]*>(.*?)</link>', body, re.S)
        date_m = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', body, re.S)
        desc_m = re.search(r'<description[^>]*>(.*?)</description>', body, re.S)
        if not title_m:
            continue
        title = strip_tags(decode_entities(title_m.group(1).strip()))
        link = strip_tags(decode_entities((link_m.group(1).strip() if link_m else '')))
        desc = strip_tags(decode_entities((desc_m.group(1).strip() if desc_m else '')))
        # Google News: 제목이 "헤드라인 - 매체명" → 매체명을 source 표시에 활용
        if is_gnews:
            sep = title.rfind(' - ')
            if sep > 0:
                paper_in_title = title[sep+3:].strip()
                title = title[:sep].strip()
            else:
                paper_in_title = GNEWS_PAPER_MAP.get(source_key, source_key)
        else:
            paper_in_title = None
        ts = parse_date(date_m.group(1).strip()) if date_m else int(time.time() * 1000)
        sentiment, score = classify(title + ' ' + desc)
        substance = classify_substance(title + ' ' + desc)
        item = {
            'source': source_key,
            'paper': paper_in_title,    # Google News의 경우 채움
            'title': title,
            'description': desc,
            'link': link,
            'ts': ts,
            'sentiment': sentiment,
            'score': score,
            'substance': substance,
            'tickers': tag_tickers(title + ' ' + desc),
        }
        items.append(enrich_article(item))
    return items


def decode_entities(s):
    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', s, flags=re.S)
    s = (s.replace('&lt;', '<').replace('&gt;', '>')
           .replace('&amp;', '&').replace('&quot;', '"')
           .replace('&apos;', "'").replace('&#039;', "'"))
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return s


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def parse_date(s):
    s = (s or '').strip()
    if not s:
        return int(time.time() * 1000)
    # Try RFC 2822: "Thu, 30 Apr 2026 15:08:58 +09:00"
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt:
            return int(dt.timestamp() * 1000)
    except Exception:
        pass
    # Try ISO without TZ: "2026-04-30 15:57:30" (assume KST = UTC+9)
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone(timedelta(hours=9)))
            return int(dt.timestamp() * 1000)
        except Exception:
            continue
    # ISO with TZ
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return int(dt.timestamp() * 1000)
    except Exception:
        pass
    return int(time.time() * 1000)


def fetch_news(sources, limit):
    sources = [s for s in sources if s in RSS_FEEDS]
    if not sources:
        sources = list(RSS_FEEDS.keys())
    results = []
    errors = []

    def fetch_one(src):
        url = RSS_FEEDS[src]
        try:
            raw = http_get(url, timeout=8)
            text = raw.decode('utf-8', errors='replace')
            return src, parse_rss(text, src)
        except Exception as e:
            return src, e

    by_source = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_one, s): s for s in sources}
        for f in as_completed(futs):
            src, val = f.result()
            if isinstance(val, Exception):
                errors.append({'source': src, 'error': str(val)[:100]})
            else:
                # 각 source 안에서 시간 역순 정렬
                val.sort(key=lambda x: -x['ts'])
                by_source[src] = val
                results.extend(val)

    # 균형 분배: limit/sources 만큼씩 캡 → merged time-sort.
    # 신선도 높은 매체가 모두 차지하지 않도록.
    if by_source and limit > 0:
        per_src = max(5, limit // max(1, len(by_source)) + 2)
        balanced = []
        for src, items in by_source.items():
            balanced.extend(items[:per_src])
        balanced.sort(key=lambda x: -x['ts'])
        trimmed = balanced[:limit]
    else:
        results.sort(key=lambda x: -x['ts'])
        trimmed = results[:limit]
    bull = sum(1 for x in trimmed if x['sentiment'] == 'bull')
    bear = sum(1 for x in trimmed if x['sentiment'] == 'bear')
    neut = sum(1 for x in trimmed if x['sentiment'] == 'neut')
    polarity = round((bull - bear) / max(1, bull + bear) * 100) if (bull + bear) > 0 else 0
    return {
        'ts': int(time.time() * 1000),
        'stats': {
            'total': len(trimmed), 'bull': bull, 'bear': bear, 'neut': neut,
            'sources': len(sources), 'polarity': polarity,
        },
        'errors': errors,
        'articles': trimmed,
    }


def fetch_stock_news(code, page=1, page_size=20):
    """Naver mobile API: m.stock.naver.com/api/news/stock/<CODE> — 구조화 JSON."""
    url = f'https://m.stock.naver.com/api/news/stock/{code}?pageSize={page_size}&page={page}'
    try:
        raw = http_get(url, timeout=8, extra_headers={
            'User-Agent': 'Mozilla/5.0 (iPhone) AppleWebKit/605 Mobile',
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://m.stock.naver.com/',
        })
        j = json.loads(raw.decode('utf-8', errors='replace'))
    except Exception as e:
        return {'code': code, 'error': str(e)[:80], 'articles': []}

    # Response: list of clusters; each cluster has items[]
    articles = []
    for cluster in (j if isinstance(j, list) else []):
        for it in cluster.get('items', []):
            title = decode_entities(it.get('title', '')).strip()
            if not title:
                continue
            body_text = decode_entities(it.get('body', '')).strip()
            dt_str = it.get('datetime', '')   # "YYYYMMDDHHmm"
            ts = int(time.time() * 1000)
            try:
                from datetime import datetime, timezone, timedelta
                dt = datetime.strptime(dt_str, '%Y%m%d%H%M').replace(tzinfo=timezone(timedelta(hours=9)))
                ts = int(dt.timestamp() * 1000)
            except Exception:
                pass
            sentiment, score = classify(title + ' ' + body_text)
            substance = classify_substance(title + ' ' + body_text)
            link = it.get('mobileNewsUrl') or it.get('linkUrl') or ''
            articles.append(enrich_article({
                'title': title,
                'body': body_text[:200],   # 본문 일부만
                'link': link,
                'paper': it.get('officeName', ''),
                'ts': ts,
                'sentiment': sentiment,
                'score': score,
                'substance': substance,
            }))
    # E2 — 비슷한 제목 dedup
    articles = simple_dedup(articles)
    return {'code': code, 'page': page, 'articles': articles, 'total': len(articles)}


def fetch_stock_chart(code, range_='3mo'):
    """Yahoo Finance daily candles for KR stock — 가격 시계열.
       ^XXX (인덱스) / XXX=X (FX) 형식은 그대로 사용, 그 외는 .KS / .KQ 시도."""
    if code.startswith('^') or code.endswith('=X'):
        candidates = [code]
    else:
        candidates = [code + '.KS', code + '.KQ']
    for sym in candidates:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&range={range_}'
        try:
            raw = http_get(url, timeout=8)
            j = json.loads(raw)
            result = j.get('chart', {}).get('result', [None])[0]
            if not result:
                continue
            meta = result.get('meta', {})
            ts_arr = result.get('timestamp', []) or []
            q = (result.get('indicators', {}).get('quote', [{}])[0]) if result.get('indicators') else {}
            bars = []
            for i, t in enumerate(ts_arr):
                c = q.get('close', [None] * len(ts_arr))[i]
                if c is None:
                    continue
                bars.append({'t': t * 1000, 'c': c, 'v': q.get('volume', [None]*len(ts_arr))[i]})
            return {
                'code': code, 'symbol': sym,
                'last': meta.get('regularMarketPrice'),
                'currency': meta.get('currency', 'KRW'),
                'bars': bars,
            }
        except Exception:
            continue
    return {'code': code, 'error': 'no_data', 'bars': []}


def fetch_historical_news(query, start_date, end_date):
    """Google News date-range 검색 — 과거 임의 시점 뉴스 가능. RFC2822 pubDate."""
    q = f'{query} after:{start_date} before:{end_date}'
    url = 'https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + '&hl=ko&gl=KR&ceid=KR:ko'
    try:
        raw = http_get(url, timeout=10)
        xml = raw.decode('utf-8', errors='replace')
    except Exception as e:
        return []
    items = []
    for m in re.finditer(r'<item>(.*?)</item>', xml, re.S):
        body = m.group(1)
        title_m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S)
        date_m = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', body, re.S)
        link_m = re.search(r'<link[^>]*>(.*?)</link>', body, re.S)
        if not title_m:
            continue
        title = decode_entities(title_m.group(1).strip())
        # GNews 형식: "headline - source"
        sep = title.rfind(' - ')
        paper = title[sep+3:].strip() if sep > 0 else 'GNews'
        title = title[:sep].strip() if sep > 0 else title
        ts = parse_date(date_m.group(1).strip()) if date_m else 0
        sentiment, score = classify(title)
        substance = classify_substance(title)
        items.append(enrich_article({
            'title': title, 'paper': paper, 'ts': ts,
            'sentiment': sentiment, 'score': score,
            'substance': substance,
            'link': link_m.group(1).strip() if link_m else '',
        }))
    return items


_HIST_NEWS_CACHE = {}   # v20.6 — (name, start_iso, end_iso) → (ts, items). 24h TTL.
def fetch_news_window_for_code(code, name, start_ts, end_ts):
    """주어진 시간 범위의 종목 뉴스. Google News 2주 단위 chunked.
       v20.6: process-level cache로 walkforward 비교 실험 시 historical news 재요청 회피."""
    from datetime import datetime, timedelta
    start_d = datetime.fromtimestamp(start_ts / 1000).date()
    end_d = datetime.fromtimestamp(end_ts / 1000).date()
    cache_key = (name, start_d.isoformat(), end_d.isoformat())
    now = time.time()
    cached = _HIST_NEWS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 86400:
        return cached[1]
    all_items = []
    chunk = timedelta(days=14)
    cur = start_d
    while cur < end_d:
        nxt = min(cur + chunk, end_d)
        items = fetch_historical_news(name, cur.isoformat(), nxt.isoformat())
        all_items.extend(items)
        cur = nxt
    # dedupe by title+ts
    seen = set()
    out = []
    for it in all_items:
        k = (it['title'][:40], it['ts'] // 86400000)
        if k in seen:
            continue
        seen.add(k); out.append(it)
    out.sort(key=lambda x: x['ts'])
    _HIST_NEWS_CACHE[cache_key] = (now, out)
    # cap cache size
    if len(_HIST_NEWS_CACHE) > 600:
        oldest = min(_HIST_NEWS_CACHE.items(), key=lambda kv: kv[1][0])
        _HIST_NEWS_CACHE.pop(oldest[0])
    return out


def fetch_one_for_sweep(code):
    """한 종목의 composite signal 계산용 raw 데이터 수집."""
    try:
        chart = fetch_stock_chart(code, '1mo')
        bars = chart.get('bars', [])
        if len(bars) < 5:
            return None
        news = fetch_stock_news(code, page=1)
        articles = news.get('articles', [])

        last = bars[-1]['c']
        b5 = bars[-6]['c'] if len(bars) >= 6 else bars[0]['c']
        b20 = bars[-21]['c'] if len(bars) >= 21 else bars[0]['c']
        mom_5 = (last - b5) / b5 * 100
        mom_20 = (last - b20) / b20 * 100

        # 거래량 z-score (오늘 vs 직전 20일 평균)
        vols = [b.get('v') or 0 for b in bars[-21:-1]]
        vols = [v for v in vols if v > 0]
        vol_z = 0
        if len(vols) >= 5:
            avg = sum(vols) / len(vols)
            var = sum((v - avg) ** 2 for v in vols) / len(vols)
            std = var ** 0.5
            last_v = bars[-1].get('v') or 0
            if std > 0:
                vol_z = (last_v - avg) / std

        # 뉴스 polarity + 밀도
        bull = sum(1 for a in articles if a['sentiment'] == 'bull')
        bear = sum(1 for a in articles if a['sentiment'] == 'bear')
        neut = len(articles) - bull - bear
        polarity = ((bull - bear) / (bull + bear) * 100) if (bull + bear) > 0 else 0
        # 밀도: 많은 뉴스 = attention. 1-건당 0.2점, max 3.
        density = min(3.0, len(articles) * 0.15)
        # v20.5 — enrichment 평균
        spec_avg = (sum(a.get('specificity') or 0 for a in articles) / len(articles)) if articles else 0
        surp_max = max((a.get('surprise') or 0 for a in articles), default=0)
        src_avg = (sum(a.get('source_score') or 0.5 for a in articles) / len(articles)) if articles else 0.5
        sub_count = sum(1 for a in articles if a.get('substance') == 'substantive')
        cat_dist = {}
        for a in articles:
            c = a.get('category') or '기타'
            cat_dist[c] = cat_dist.get(c, 0) + 1
        # C3 — Mystery mover: 가격 큰 변동인데 뉴스 거의 없음
        is_mystery = (abs(mom_5) >= 3.0 and len(articles) <= 1)

        # 합성 점수 — 단위 정규화
        score = (
            0.30 * max(-15, min(15, mom_5))      # 5일 수익률
            + 0.20 * max(-25, min(25, mom_20)) / 2  # 20일 수익률 (반쯤)
            + 0.25 * (polarity / 10)             # -10..+10
            + 0.15 * density                     # 0..3
            + 0.10 * max(-3, min(3, vol_z))      # 거래량 z
        )
        info = UNIVERSE.get(code, {})
        return {
            'code': code,
            'name': info.get('name', KR_TICKERS.get(code, code)),
            'market': info.get('market', '?'),
            'last': last,
            'mom_5': round(mom_5, 2),
            'mom_20': round(mom_20, 2),
            'polarity': round(polarity, 0),
            'news_count': len(articles),
            'news_bull': bull,
            'news_bear': bear,
            'vol_z': round(vol_z, 2),
            'score': round(score, 2),
            # v20.5 enrichment
            'specificity': round(spec_avg, 2),
            'surprise_max': round(surp_max, 2),
            'src_avg': round(src_avg, 2),
            'sub_count': sub_count,
            'cat_dist': cat_dist,
            'is_mystery': is_mystery,
        }
    except Exception:
        return None


def walkforward_backtest(top_n=80, days=120, top_k=8, hold=5, use_news=True, mode='blend',
                         universe_mode='current', cat_filter=(), start_offset_days=0):
    """과거 N일 walk-forward 백테스트 — 미래 참조 X.
       mode:
         'blend':         가격 모멘텀 + 뉴스 polarity 합성 (default)
         'price_only':    가격 모멘텀만
         'news_only':     뉴스 polarity + 밀도만
         'attention':     뉴스 attention surge (3일/14일 비율) — 가격과 직교 가설 검증
         'attn_blend':    0.5 mom5 + 0.5 attention — 직교 인자 결합
         'substantive':   실질 뉴스 polarity 가중
         'informational': polarity × specificity × source × substantive (v20.5)
       cat_filter: tuple of categories — dominant cat이 이 중 하나여야만 long candidate. ex ('실적','M&A').
       start_offset_days: 0이면 최신 윈도우, N이면 N일 전부터의 윈도우 (약세장 검증용).
       또한 각 factor의 IC (forward return과의 Pearson correlation) 계산해서 직교성·예측력 정량화.
       Long-only top K. hold 일 후 청산.
    """
    if mode == 'price_only':
        use_news = False
    elif mode in ('news_only', 'attention', 'attn_blend'):
        use_news = True

    # ── Universe pool 결정 ──
    # 'current'  : 현재 시총 top N (survivorship 편향 ⚠)
    # 'kospi200' : 현재 KOSPI top 200 정적 (KOSDAQ 제외 — 상대적으로 안정)
    # 'dynamic'  : 시점별 동적 — 모든 stock fetch 후 implied_shares × price[t]로 historical mcap 계산
    if universe_mode == 'kospi200':
        codes = [c for c, info in UNIVERSE.items() if info.get('market') == 'KOSPI'][:200]
    elif universe_mode == 'dynamic':
        # 더 큰 candidate pool — 시점별 ranking에 들 수 있는 모든 후보
        codes = list(UNIVERSE.keys())[:400] if UNIVERSE else list(KR_TICKERS.keys())[:400]
    else:    # 'current'
        codes = list(UNIVERSE.keys())[:top_n] if UNIVERSE else list(KR_TICKERS.keys())[:top_n]

    # 1. Charts — 약세장 검증을 위해 start_offset_days > 0이면 더 긴 range
    chart_range = '2y' if start_offset_days > 0 else '1y'
    needed = days + 30 + start_offset_days
    charts = {}
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = {ex.submit(fetch_stock_chart, c, chart_range): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            bars = r.get('bars', []) if r else []
            if r and len(bars) >= needed:
                # start_offset_days 만큼 끝에서 잘라내기 → 그 시점에서의 윈도우 사용
                if start_offset_days > 0:
                    charts[r['code']] = bars[-(days + 30 + start_offset_days) : -start_offset_days]
                else:
                    charts[r['code']] = bars[-(days + 30):]

    if len(charts) < top_k * 2 + 5:
        return {'error': f'insufficient charts: {len(charts)} (need {top_k*2+5}+)'}

    # ── Dynamic universe: 현재 시총 + 종가로 implied_shares 계산
    implied_shares = {}
    if universe_mode == 'dynamic':
        # marketcap fetch (cached). 모든 chart 있는 stock에 대해.
        chart_codes = list(charts.keys())
        try:
            mc = fetch_marketcap(chart_codes)
            for q in mc.get('quotes', []):
                code = q.get('code')
                cap = q.get('marketCap'); last = q.get('last')
                if code and cap and last and last > 0:
                    implied_shares[code] = cap / last
        except Exception:
            pass

    # 2. Historical news per stock (only if use_news=True)
    news_by_code = {}
    if use_news:
        first_ts = min(charts[c][0]['t'] for c in charts)
        last_ts = max(charts[c][-1]['t'] for c in charts)
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {}
            for c, bars in charts.items():
                name = (UNIVERSE.get(c) or {}).get('name') or KR_TICKERS.get(c, c)
                if len(name) < 2:
                    continue
                futs[ex.submit(fetch_news_window_for_code, c, name, first_ts, last_ts)] = c
            for f in as_completed(futs):
                code = futs[f]
                try:
                    news_by_code[code] = f.result()
                except Exception:
                    news_by_code[code] = []

    # 3. Benchmark KOSPI — fetch index, align by timestamp not by length
    bench = fetch_stock_chart('^KS11', '1y')
    bench_bars_full = bench.get('bars', []) if bench else []

    # 4. Common date alignment — use min length of stock charts
    min_len = min(len(b) for b in charts.values())
    series = {c: bars[-min_len:] for c, bars in charts.items()}

    # Align bench by ts: find bench bar closest to each stock bar
    bench_bars = []
    if bench_bars_full:
        # Index bench by date (yyyy-mm-dd) for robust alignment
        from datetime import datetime, timezone
        bench_by_day = {}
        for b in bench_bars_full:
            day = datetime.fromtimestamp(b['t']/1000, tz=timezone.utc).date()
            bench_by_day[day] = b
        # For each stock-day in series, find matching bench day (or nearest prior)
        any_stock = next(iter(series.values()))
        sorted_bench_days = sorted(bench_by_day.keys())
        for stock_bar in any_stock:
            stock_day = datetime.fromtimestamp(stock_bar['t']/1000, tz=timezone.utc).date()
            if stock_day in bench_by_day:
                bench_bars.append(bench_by_day[stock_day])
            else:
                # nearest prior trading day
                prior = [d for d in sorted_bench_days if d <= stock_day]
                if prior:
                    bench_bars.append(bench_by_day[prior[-1]])
                else:
                    bench_bars.append(bench_bars_full[0] if bench_bars_full else None)

    # 5. Walk-forward simulation
    rebalance_points = list(range(20, min_len - hold, hold))
    trades = []
    equity = [1.0]
    bench_equity = [1.0]
    ic_history = []   # 각 rebalance에서 factor별 IC (Pearson)
    # v20.5 — 카테고리별 forward return (B1 half-life용)
    cat_forwards = {c: [] for c in NEWS_CATEGORIES}
    # 모든 feat_rows 누적 (E1 decile, C3 mystery용)
    all_feat = []

    for t in rebalance_points:
        scores = []
        t_ts = series[next(iter(series))][t]['t']
        # 14-day news window for polarity at t
        news_window_start = t_ts - 14 * 86400000
        attn_window_start = t_ts - 3 * 86400000   # 3일 윈도우 (vs 14일 baseline)
        # ── Dynamic universe: 시점 t의 historical mcap top top_n 만 후보 ──
        if universe_mode == 'dynamic' and implied_shares:
            cap_at_t = []
            for code, bars in series.items():
                if code not in implied_shares:
                    continue
                cap_at_t.append((code, bars[t]['c'] * implied_shares[code]))
            cap_at_t.sort(key=lambda x: -x[1])
            allowed_codes = set(c for c, _ in cap_at_t[:top_n])
        else:
            allowed_codes = None   # all
        # 모든 후보 features 계산 — IC 측정용. 뒤에서 mode에 따라 score 결정.
        feat_rows = []   # (code, mom5, mom20, polarity, density, attention, dispersion, news_count, forward)
        for code, bars in series.items():
            if allowed_codes is not None and code not in allowed_codes:
                continue
            cur = bars[t]['c']
            mom5 = (cur / bars[t-5]['c'] - 1) * 100 if t >= 5 else 0
            mom20 = (cur / bars[t-20]['c'] - 1) * 100 if t >= 20 else 0
            mom5_clip = max(-15, min(15, mom5))
            mom20_clip = max(-25, min(25, mom20))
            polarity = 0; n_count = 0; n_recent = 0; bull = 0; bear = 0
            # v20.4 — substantive-only counters (실질 정보만)
            s_bull = 0; s_bear = 0; s_count = 0; r_count = 0
            # v20.5 — 추가 factor: A1 specificity, A2 source, A3 surprise, B3 tod
            spec_avg = 0.0; surp_avg = 0.0; src_avg = 0.5; info_score = 0.0
            tod_pre = 0; tod_intra = 0; tod_after = 0
            cat_counts = {c: 0 for c in NEWS_CATEGORIES}
            if use_news and code in news_by_code:
                relevant = [a for a in news_by_code[code] if news_window_start <= a['ts'] <= t_ts]
                bull = sum(1 for a in relevant if a['sentiment'] == 'bull')
                bear = sum(1 for a in relevant if a['sentiment'] == 'bear')
                n_count = len(relevant)
                if (bull + bear) > 0:
                    polarity = (bull - bear) / (bull + bear) * 100
                n_recent = sum(1 for a in relevant if a['ts'] >= attn_window_start)
                # ★ Substantive subset
                substantive = [a for a in relevant if a.get('substance') == 'substantive']
                reactive = [a for a in relevant if a.get('substance') == 'reactive']
                s_bull = sum(1 for a in substantive if a['sentiment'] == 'bull')
                s_bear = sum(1 for a in substantive if a['sentiment'] == 'bear')
                s_count = len(substantive)
                r_count = len(reactive)
                # v20.5 — 새 factors (집계만; 일부 fetcher는 enrich field 없을 수 있음 → default 0)
                if relevant:
                    spec_vals = [a.get('specificity') or 0 for a in relevant]
                    surp_vals = [a.get('surprise') or 0 for a in relevant]
                    src_vals = [a.get('source_score') or 0.5 for a in relevant]
                    spec_avg = sum(spec_vals) / len(spec_vals)
                    surp_avg = sum(surp_vals) / len(surp_vals)
                    src_avg = sum(src_vals) / len(src_vals)
                    for a in relevant:
                        tod = a.get('tod') or 'intra'
                        if tod == 'pre': tod_pre += 1
                        elif tod == 'after': tod_after += 1
                        else: tod_intra += 1
                        cat = a.get('category') or '기타'
                        if cat in cat_counts: cat_counts[cat] += 1
                # info_score: 정보의 진짜 가치 = polarity × specificity × source × substantive_ratio
                sub_ratio = s_count / max(1, n_count)
                info_score = (polarity / 100.0) * (1 + spec_avg) * src_avg * (0.5 + sub_ratio)
            density = min(3.0, n_count * 0.15)
            attention = (n_recent / max(1, n_count)) if n_count >= 3 else 0
            disagree = (min(bull, bear) / max(1, max(bull, bear))) if (bull + bear) >= 3 else 0
            # Substantive polarity (실질 뉴스만, 사후 가격 묘사 제외)
            s_polarity = ((s_bull - s_bear) / (s_bull + s_bear) * 100) if (s_bull + s_bear) > 0 else 0
            s_density = min(3.0, s_count * 0.20)   # substantive는 더 의미있어서 가중 ↑
            # reactive ratio: 0=실질만, 1=사후만 (높을수록 noise)
            reactive_ratio = (r_count / max(1, n_count)) if n_count >= 3 else 0
            # B3 tod skew: pre+after 비율 (장중 외 = 정보성 더 높음 가설)
            tod_offmkt = ((tod_pre + tod_after) / max(1, n_count)) if n_count >= 3 else 0

            forward = (bars[t+hold]['c'] / cur - 1) * 100
            feat_rows.append({
                'code': code, 'mom5': mom5_clip, 'mom20': mom20_clip,
                'polarity': polarity, 'density': density, 'attention': attention,
                'disagree': disagree, 'n_count': n_count, 'forward': forward,
                's_polarity': s_polarity, 's_density': s_density,
                's_count': s_count, 'reactive_ratio': reactive_ratio,
                # v20.5
                'specificity': spec_avg, 'surprise': surp_avg, 'src_avg': src_avg,
                'info_score': info_score, 'tod_offmkt': tod_offmkt,
                'cat_counts': cat_counts,
            })

        # Score by mode
        scores = []
        for f in feat_rows:
            # v20.6 — cat_filter: dominant 카테고리가 이 set 안에 있어야 long candidate
            if cat_filter:
                cc = f.get('cat_counts') or {}
                if not cc:
                    continue
                # dominant cat (cc 중 max). '기타'는 제외.
                non_etc = {k: v for k, v in cc.items() if k != '기타' and v > 0}
                if not non_etc:
                    continue
                top_cat = max(non_etc, key=lambda k: non_etc[k])
                if top_cat not in cat_filter:
                    continue
            if mode == 'price_only':
                s = 0.7 * f['mom5'] + 0.3 * (f['mom20'] / 2)
            elif mode == 'news_only':
                if f['n_count'] < 2: continue
                s = 0.6 * (f['polarity'] / 10) + 0.4 * f['density']
            elif mode == 'substantive':
                # v20.4 — 실질 뉴스만 (사후적 가격 묘사 제외) + 가격 모멘텀
                if f['s_count'] < 1: continue
                s = (
                    0.30 * f['mom5']
                    + 0.20 * (f['mom20'] / 2)
                    + 0.35 * (f['s_polarity'] / 10)    # ★ substantive polarity 강조
                    + 0.15 * f['s_density']
                )
            elif mode == 'attention':
                if f['n_count'] < 3: continue
                # pure attention surge — 가격 모멘텀과 직교 가설
                s = f['attention'] * 100 + 0.2 * f['polarity']/10   # 약간 polarity 보조
            elif mode == 'attn_blend':
                # 가격 + attention 직교 결합
                s = 0.5 * f['mom5'] + 0.5 * (f['attention'] * 100)
            elif mode == 'informational':
                # v20.5 — 정보의 가치 가중: polarity × specificity × source × substantive
                if f['n_count'] < 1: continue
                s = (
                    0.30 * f['mom5']
                    + 0.20 * (f['mom20'] / 2)
                    + 0.40 * (f['info_score'] * 50)   # info_score range ~ -1..+3 → ×50 for unit match
                    + 0.10 * f['density']
                )
            else:    # blend
                s = (
                    0.40 * f['mom5']
                    + 0.20 * (f['mom20'] / 2)
                    + 0.30 * (f['polarity'] / 10)
                    + 0.10 * f['density']
                )
            scores.append((f['code'], s, f['forward']/100, f['polarity'], f['n_count']))

        # v20.5 — 카테고리 dominant 시 forward return (B1)
        for r in feat_rows:
            cc = r.get('cat_counts') or {}
            if not cc: continue
            top_cat = max(cc, key=lambda k: cc[k])
            if cc[top_cat] >= 1 and top_cat != '기타':
                cat_forwards[top_cat].append(r['forward'])
            all_feat.append({
                'mom5': r['mom5'], 'polarity': r['polarity'], 'n_count': r['n_count'],
                'specificity': r['specificity'], 'surprise': r['surprise'],
                'forward': r['forward'],
            })

        # IC (Pearson correlation) 계산: 각 factor vs forward return
        if len(feat_rows) >= 5:
            def pearson(xs, ys):
                n = len(xs)
                if n < 3: return None
                mx = sum(xs)/n; my = sum(ys)/n
                num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
                vx = sum((x-mx)**2 for x in xs) ** 0.5
                vy = sum((y-my)**2 for y in ys) ** 0.5
                if vx*vy == 0: return None
                return num / (vx*vy)
            fwd = [r['forward'] for r in feat_rows]
            ic_period = {}
            for fac in ('mom5', 'mom20', 'polarity', 'density', 'attention', 'disagree',
                        's_polarity', 's_density', 'reactive_ratio',
                        'specificity', 'surprise', 'src_avg', 'info_score', 'tod_offmkt'):
                xs = [r[fac] for r in feat_rows]
                ic_period[fac] = pearson(xs, fwd)
            ic_history.append(ic_period)

        if len(scores) < top_k * 2:
            continue
        scores.sort(key=lambda x: -x[1])
        longs = scores[:top_k]
        shorts = scores[-top_k:]

        long_ret = sum(s[2] for s in longs) / top_k
        short_ret = -sum(s[2] for s in shorts) / top_k
        # Long-only strategy (more realistic for KR retail)
        equity.append(equity[-1] * (1 + long_ret))
        if bench_bars and t + hold < len(bench_bars) and bench_bars[t] and bench_bars[t+hold]:
            br = bench_bars[t+hold]['c'] / bench_bars[t]['c'] - 1
            bench_equity.append(bench_equity[-1] * (1 + br))
        else:
            bench_equity.append(bench_equity[-1])

        trades.append({
            't_idx': t,
            't_ts': t_ts,
            'long_ret_pct': round(long_ret * 100, 2),
            'short_ret_pct': round(short_ret * 100, 2),
            'longs': [(s[0], (UNIVERSE.get(s[0]) or {}).get('name', s[0]), round(s[1], 2), round(s[3], 0), s[4]) for s in longs[:5]],
            'shorts': [(s[0], (UNIVERSE.get(s[0]) or {}).get('name', s[0]), round(s[1], 2), round(s[3], 0), s[4]) for s in shorts[-5:]],
        })

    # 6. Stats
    rets = [tr['long_ret_pct'] / 100 for tr in trades]
    if not rets:
        return {'error': 'no trades produced'}
    total_return = (equity[-1] - 1) * 100
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
    mean_ret = sum(rets) / len(rets)
    var_ret = sum((r - mean_ret) ** 2 for r in rets) / max(1, len(rets) - 1)
    std_ret = var_ret ** 0.5
    n_per_year = 252 / hold
    sharpe = (mean_ret * n_per_year) / (std_ret * (n_per_year ** 0.5)) if std_ret > 0 else 0

    peak = 1.0; mdd = 0
    for v in equity:
        if v > peak: peak = v
        d = (v - peak) / peak
        if d < mdd: mdd = d

    bench_total = (bench_equity[-1] - 1) * 100 if bench_equity else 0

    # Date strings
    start_date = ''
    end_date = ''
    if trades:
        from datetime import datetime
        start_date = datetime.fromtimestamp(trades[0]['t_ts'] / 1000).strftime('%Y-%m-%d')
        end_date = datetime.fromtimestamp(trades[-1]['t_ts'] / 1000).strftime('%Y-%m-%d')

    # Sample dates for equity curve x-axis
    curve_dates = []
    for i, t in enumerate(rebalance_points[:len(equity)-1]):
        if i < len(series[next(iter(series))]) - 1 and t < len(series[next(iter(series))]):
            ts = series[next(iter(series))][t]['t']
            curve_dates.append(ts)

    # IC summary — factor별 평균 + IR (mean / std)
    ic_summary = {}
    factors = ('mom5', 'mom20', 'polarity', 'density', 'attention', 'disagree',
               's_polarity', 's_density', 'reactive_ratio',
               'specificity', 'surprise', 'src_avg', 'info_score', 'tod_offmkt')
    for fac in factors:
        vals = [period[fac] for period in ic_history if period.get(fac) is not None]
        if not vals:
            ic_summary[fac] = {'mean': None, 'std': None, 'ir': None, 'n': 0, 'hit_rate': None}
            continue
        m = sum(vals)/len(vals)
        v = (sum((x-m)**2 for x in vals) / max(1, len(vals)-1)) ** 0.5
        ir = m / v if v > 0 else None
        hit = sum(1 for x in vals if x > 0) / len(vals)
        ic_summary[fac] = {
            'mean': round(m, 4), 'std': round(v, 4),
            'ir': round(ir, 3) if ir is not None else None,
            'n': len(vals), 'hit_rate': round(hit, 3),
        }

    # 직교성 분석: factor 쌍 사이의 IC 시계열 상관 — 낮을수록 직교
    ortho = {}
    for i, fa in enumerate(factors):
        ortho[fa] = {}
        va = [p[fa] for p in ic_history if p.get(fa) is not None and p.get('mom5') is not None]
        for fb in factors:
            if fa == fb:
                ortho[fa][fb] = 1.0
                continue
            paired = [(p[fa], p[fb]) for p in ic_history if p.get(fa) is not None and p.get(fb) is not None]
            if len(paired) < 3:
                ortho[fa][fb] = None
                continue
            mx = sum(x for x,_ in paired)/len(paired); my = sum(y for _,y in paired)/len(paired)
            num = sum((x-mx)*(y-my) for x,y in paired)
            vx = sum((x-mx)**2 for x,_ in paired)**0.5; vy = sum((y-my)**2 for _,y in paired)**0.5
            ortho[fa][fb] = round(num/(vx*vy), 3) if vx*vy > 0 else None

    # B1 — Category half-life: 카테고리별 평균 forward return + sample 수
    cat_halflife = {}
    for cat, vals in cat_forwards.items():
        if len(vals) >= 5:
            mean_v = sum(vals) / len(vals)
            std_v = (sum((x - mean_v)**2 for x in vals) / max(1, len(vals)-1)) ** 0.5
            hit = sum(1 for x in vals if x > 0) / len(vals)
            cat_halflife[cat] = {
                'mean_pct': round(mean_v, 2), 'std_pct': round(std_v, 2),
                'n': len(vals), 'hit_rate': round(hit, 3),
                'hold_days': hold,
            }

    # E1 — Polarity decile spread: 5분위 (Q1=가장 약세, Q5=가장 강세) 평균 forward
    decile_spread = None
    pol_rows = [r for r in all_feat if r['n_count'] >= 2]
    if len(pol_rows) >= 25:
        sorted_pol = sorted(pol_rows, key=lambda r: r['polarity'])
        bsz = max(1, len(sorted_pol) // 5)
        deciles = []
        for i in range(5):
            chunk = sorted_pol[i*bsz : (i+1)*bsz] if i < 4 else sorted_pol[i*bsz:]
            if chunk:
                m = sum(r['forward'] for r in chunk) / len(chunk)
                deciles.append({'q': i+1, 'mean_pol': round(sum(r['polarity'] for r in chunk)/len(chunk), 1),
                                'mean_forward_pct': round(m, 2), 'n': len(chunk)})
        decile_spread = {
            'quintiles': deciles,
            'q5_minus_q1_pct': round(deciles[-1]['mean_forward_pct'] - deciles[0]['mean_forward_pct'], 2)
                if len(deciles) == 5 else None,
        }

    # C3 — Mystery mover stats: |mom5|>=3% AND n_count<=1
    mystery_count = sum(1 for r in all_feat if abs(r['mom5']) >= 3 and r['n_count'] <= 1)
    mystery_avg_fwd = (sum(r['forward'] for r in all_feat if abs(r['mom5']) >= 3 and r['n_count'] <= 1)
                      / max(1, mystery_count)) if mystery_count >= 5 else None

    return {
        'period': {'start': start_date, 'end': end_date, 'days': min_len},
        'config': {'top_n': top_n, 'top_k': top_k, 'hold': hold, 'use_news': use_news, 'mode': mode,
                   'universe_mode': universe_mode,
                   'cat_filter': list(cat_filter),
                   'start_offset_days': start_offset_days,
                   'eligible_stocks': len(series), 'rebalances': len(trades)},
        'stats': {
            'total_return_pct': round(total_return, 2),
            'win_rate_pct': round(win_rate, 1),
            'sharpe_annualized': round(sharpe, 2),
            'max_drawdown_pct': round(mdd * 100, 2),
            'mean_per_rebalance_pct': round(mean_ret * 100, 2),
            'std_per_rebalance_pct': round(std_ret * 100, 2),
        },
        'ic_summary': ic_summary,
        'ic_orthogonality': ortho,
        'cat_halflife': cat_halflife,           # v20.5 B1
        'decile_spread': decile_spread,         # v20.5 E1
        'mystery_mover': {                      # v20.5 C3 backtest stats
            'n': mystery_count,
            'avg_forward_pct': round(mystery_avg_fwd, 2) if mystery_avg_fwd is not None else None,
        },
        'benchmark': {
            'name': 'KOSPI buy-and-hold',
            'total_return_pct': round(bench_total, 2),
            'curve': bench_equity,
        },
        'equity_curve': equity,
        'curve_ts': curve_dates,
        'trades_first': trades[:5],
        'trades_last': trades[-5:],
    }


def fetch_recent_picks(top_n=120, lookbacks=(5, 10, 20)):
    """v20.7+v20.8 — 매 N일 전 시점 sweep top10 매수 → 오늘까지 실제 수익.
       Score = full sweep formula (mom5+mom20+뉴스 polarity+density+거래량 z) — 뉴스 포함.
       미래 참조 X: T-N 시점에서 [T-N-14, T-N] 윈도우 historical news 만 사용.
       24h 캐시 = 매일 자동 갱신."""
    codes = list(UNIVERSE.keys())[:top_n] if UNIVERSE else list(KR_TICKERS.keys())[:top_n]
    charts = {}
    needed = max(lookbacks) + 21
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = {ex.submit(fetch_stock_chart, c, '3mo'): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            if r and len(r.get('bars', [])) >= needed:
                charts[r['code']] = r['bars']

    bench = fetch_stock_chart('^KS11', '3mo')
    kospi_bars = bench.get('bars', []) if bench else []

    # v20.8 — Historical news per stock (한 번만 fetch, 모든 lookback 공유)
    # 윈도우: T-max_lb-14 ~ T (약 max_lb+14 일)
    news_by_code = {}
    if charts:
        max_lb = max(lookbacks)
        for c, bars in charts.items():
            ts_at_max = bars[-1 - max_lb]['t']
            news_start_for_c = ts_at_max - 14 * 86400000
            news_end_for_c = bars[-1]['t']
            charts[c] = bars   # noop, just for ref
        # earliest start ts across stocks
        first_ts_needed = min(b[-1 - max(lookbacks)]['t'] - 14 * 86400000 for b in charts.values())
        last_ts_needed = max(b[-1]['t'] for b in charts.values())
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {}
            for c, bars in charts.items():
                name = (UNIVERSE.get(c) or {}).get('name') or KR_TICKERS.get(c, c)
                if len(name) < 2:
                    news_by_code[c] = []; continue
                futs[ex.submit(fetch_news_window_for_code, c, name, first_ts_needed, last_ts_needed)] = c
            for f in as_completed(futs):
                code = futs[f]
                try:
                    news_by_code[code] = f.result()
                except Exception:
                    news_by_code[code] = []

    snapshots = []
    for lb in lookbacks:
        t_idx = -1 - lb
        cands = []
        for code, bars in charts.items():
            if abs(t_idx) + 20 >= len(bars):
                continue
            cur = bars[t_idx]['c']
            t_ts = bars[t_idx]['t']
            news_window_start = t_ts - 14 * 86400000

            m5 = (cur / bars[t_idx - 5]['c'] - 1) * 100
            m20 = (cur / bars[t_idx - 20]['c'] - 1) * 100

            # 거래량 z-score (T-1..T-21 baseline)
            vols = [b.get('v') or 0 for b in bars[t_idx - 21:t_idx]]
            vols = [v for v in vols if v > 0]
            vol_z = 0
            if len(vols) >= 5:
                avg = sum(vols) / len(vols)
                var = sum((v - avg) ** 2 for v in vols) / len(vols)
                std = var ** 0.5
                last_v = bars[t_idx].get('v') or 0
                if std > 0:
                    vol_z = (last_v - avg) / std

            # 뉴스 polarity / density at T-lb (14d 윈도우, T-lb 이전)
            polarity = 0; density = 0; n_count = 0
            bull = bear = 0
            if code in news_by_code:
                relevant = [a for a in news_by_code[code] if news_window_start <= a['ts'] <= t_ts]
                bull = sum(1 for a in relevant if a.get('sentiment') == 'bull')
                bear = sum(1 for a in relevant if a.get('sentiment') == 'bear')
                n_count = len(relevant)
                if (bull + bear) > 0:
                    polarity = (bull - bear) / (bull + bear) * 100
                density = min(3.0, n_count * 0.15)

            # Full sweep formula
            score = (
                0.30 * max(-15, min(15, m5))
                + 0.20 * max(-25, min(25, m20)) / 2
                + 0.25 * (polarity / 10)
                + 0.15 * density
                + 0.10 * max(-3, min(3, vol_z))
            )

            p_now = bars[-1]['c']
            forward = (p_now - cur) / cur * 100
            info = UNIVERSE.get(code, {})
            cands.append({
                'code': code,
                'name': info.get('name', KR_TICKERS.get(code, code)),
                'score': round(score, 2),
                'mom5_T': round(m5, 1),
                'mom20_T': round(m20, 1),
                'polarity_T': round(polarity, 0),
                'density_T': round(density, 1),
                'news_count_T': n_count,
                'news_bull_T': bull,
                'news_bear_T': bear,
                'vol_z_T': round(vol_z, 2),
                'forward_pct': round(forward, 2),
                'price_T': cur,
                'price_now': p_now,
            })
        if not cands:
            continue
        cands.sort(key=lambda x: -x['score'])
        top = cands[:10]
        avg_fwd = sum(t['forward_pct'] for t in top) / len(top)
        win = sum(1 for t in top if t['forward_pct'] > 0)
        kospi_fwd = 0.0
        if abs(t_idx) <= len(kospi_bars):
            k_T = kospi_bars[t_idx]['c']
            kospi_fwd = (kospi_bars[-1]['c'] - k_T) / k_T * 100
        sample = next(iter(charts.values()))
        snapshot_ts = sample[t_idx]['t']
        today_ts = sample[-1]['t']
        snapshots.append({
            'lookback_days': lb,
            'snapshot_ts': snapshot_ts,
            'today_ts': today_ts,
            'top': top,
            'avg_fwd_pct': round(avg_fwd, 2),
            'kospi_fwd_pct': round(kospi_fwd, 2),
            'alpha_pct': round(avg_fwd - kospi_fwd, 2),
            'win_count': win,
            'total': len(top),
        })

    return {
        'ts': int(time.time() * 1000),
        'universe_size': len(charts),
        'note': 'Full sweep formula (가격 + 뉴스 polarity·density + 거래량 z). 미래 참조 X. 24h 캐시 = 매일 자동 갱신.',
        'snapshots': snapshots,
    }


def fetch_sweep(top_n=120):
    """Universe top N 종목 sweep — composite signal 계산. 결과 캐시 1시간."""
    codes = list(UNIVERSE.keys())[:top_n] if UNIVERSE else list(KR_TICKERS.keys())[:top_n]
    results = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = [ex.submit(fetch_one_for_sweep, c) for c in codes]
        for f in as_completed(futs):
            r = f.result()
            if r: results.append(r)
    results.sort(key=lambda x: -x['score'])
    # v20.5 — Mystery mover bucket: 큰 가격 변동인데 뉴스 빈약 (인사이더 누설 의심·anomaly)
    mystery_movers = sorted(
        [r for r in results if r.get('is_mystery')],
        key=lambda x: -abs(x['mom_5'])
    )[:10]
    return {
        'ts': int(time.time() * 1000),
        'count': len(results),
        'top_bull': results[:15],
        'top_bear': results[-15:][::-1],
        'mystery_movers': mystery_movers,    # C3
        'all': results,
    }


def fetch_marketcap(codes):
    """Naver Finance 스크래핑으로 시총 수집. 1일 캐시.
       각 종목 페이지 fetch 후 시가총액 / PER / 외국인지분율 추출."""
    def parse_kr_amount(s):
        # "1,289조 1,044억원" → 1289 * 1e12 + 1044 * 1e8
        s = (s or '').strip()
        total = 0
        m = re.search(r'([\d,]+)\s*조', s)
        if m:
            total += int(m.group(1).replace(',', '')) * 10**12
        m = re.search(r'([\d,]+)\s*억', s)
        if m:
            total += int(m.group(1).replace(',', '')) * 10**8
        if total == 0:
            m = re.search(r'([\d,]+)', s)
            if m:
                total = int(m.group(1).replace(',', ''))
        return total or None

    def fetch_one(code):
        url = f'https://finance.naver.com/item/main.naver?code={code}'
        try:
            raw = http_get(url, timeout=6)
            html = raw.decode('utf-8', errors='replace')
        except Exception as e:
            return {'code': code, 'error': str(e)[:60]}
        # 시가총액 — Naver의 #_market_sum em 태그
        cap = None
        m = re.search(r'<em[^>]*id="_market_sum"[^>]*>([\s\S]*?)</em>', html)
        if m:
            cap = parse_kr_amount(re.sub(r'<[^>]+>', '', m.group(1)))
        if not cap:
            # 보조 — th 시가총액 td 패턴 (혹시 다른 페이지 레이아웃)
            m = re.search(r'<th[^>]*>\s*시가총액\s*</th>\s*<td[^>]*>(.*?)</td>', html, re.S)
            if m:
                cap = parse_kr_amount(re.sub(r'<[^>]+>', '', m.group(1)))
        # PER (낮은 줄에 있음)
        pe = None
        m = re.search(r'<em[^>]*id="_per"[^>]*>([\d,.\-]+)</em>', html)
        if m:
            try: pe = float(m.group(1).replace(',', ''))
            except: pass
        # 외국인 보유율
        fpct = None
        m = re.search(r'외국인.*?소진율.*?<em[^>]*>([\d.]+)</em>', html, re.S)
        if m:
            try: fpct = float(m.group(1))
            except: pass
        # 종목명
        name = None
        m = re.search(r'<div class="wrap_company">.*?<h2>.*?<a[^>]*>([^<]+)</a>', html, re.S)
        if m: name = m.group(1).strip()
        # 현재가
        last = None
        m = re.search(r'<p class="no_today">.*?<span class="no_up\b[^"]*"[^>]*>(.*?)</span>', html, re.S)
        if m:
            try:
                num = re.sub(r'<[^>]+>', '', m.group(1))
                last = int(num.replace(',', '').strip())
            except: pass
        if not last:
            # fallback: any blind-looking price
            m = re.search(r'class="blind">([\d,]+)</span>', html)
            if m:
                try: last = int(m.group(1).replace(',', ''))
                except: pass
        return {
            'code': code,
            'name': name,
            'last': last,
            'marketCap': cap,
            'pe': pe,
            'foreignPct': fpct,
        }

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(fetch_one, c) for c in codes[:80] if not (c.startswith('^') or c.endswith('=X'))]
        results = [f.result() for f in as_completed(futs)]
    return {'ts': int(time.time() * 1000), 'quotes': results, 'source': 'naver'}


def fetch_quote(codes, interval='1m', range_='1d'):
    """Yahoo Finance v8 chart 프록시 (분봉)."""
    def fetch_one(code):
        # 6-digit KR code: try .KS then .KQ
        candidates = [code] if code.startswith('^') or code.endswith('=X') else [code + '.KS', code + '.KQ']
        for sym in candidates:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval={interval}&range={range_}'
            try:
                raw = http_get(url, timeout=6)
                j = json.loads(raw)
                result = j.get('chart', {}).get('result', [None])[0]
                if not result:
                    continue
                meta = result.get('meta', {})
                ts_arr = result.get('timestamp', []) or []
                q = (result.get('indicators', {}).get('quote', [{}])[0]) if result.get('indicators') else {}
                bars = []
                for i, t in enumerate(ts_arr):
                    c = q.get('close', [None] * len(ts_arr))[i]
                    if c is None:
                        continue
                    bars.append({
                        't': t,
                        'o': q.get('open', [None] * len(ts_arr))[i],
                        'h': q.get('high', [None] * len(ts_arr))[i],
                        'l': q.get('low', [None] * len(ts_arr))[i],
                        'c': c,
                        'v': q.get('volume', [None] * len(ts_arr))[i],
                    })
                return {
                    'code': code, 'symbol': sym,
                    'last': meta.get('regularMarketPrice'),
                    'prev': meta.get('chartPreviousClose') or meta.get('previousClose'),
                    'currency': meta.get('currency'),
                    'exchange': meta.get('exchangeName'),
                    'bars': bars,
                }
            except Exception:
                continue
        return {'code': code, 'error': 'no_data'}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch_one, c) for c in codes[:50]]
        results = [f.result() for f in as_completed(futs)]
    return {'ts': int(time.time() * 1000), 'quotes': results}


# ─── HTTP 핸들러 ───────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    NEWS_CACHE = {'ts': 0, 'data': None, 'key': ''}
    QUOTE_CACHE = {}  # key → (ts, data)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        # HTML: 브라우저 캐시 무효화 — 페이지 업데이트 시 항상 새로 받도록
        if self.path.endswith('.html') or self.path == '/':
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/news':
            return self._api_news(u)
        if u.path == '/api/quote':
            return self._api_quote(u)
        if u.path == '/api/marketcap':
            return self._api_marketcap(u)
        if u.path == '/api/universe':
            return self._api_universe(u)
        if u.path == '/api/stock-news':
            return self._api_stock_news(u)
        if u.path == '/api/stock-chart':
            return self._api_stock_chart(u)
        if u.path == '/api/sweep':
            return self._api_sweep(u)
        if u.path == '/api/recent-picks':
            return self._api_recent_picks(u)
        if u.path == '/api/walkforward':
            return self._api_walkforward(u)
        if u.path == '/api':
            return self._api_index()
        return super().do_GET()

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=60')
        self.end_headers()
        self.wfile.write(body)

    def _api_index(self):
        self._send_json({
            'name': 'StoryQuant Local API',
            'endpoints': {
                '/api/news':         'sources=mk,fnnews,einfomax,hani,...&limit=80',
                '/api/quote':        'codes=005930,000660,...&interval=1m&range=1d',
                '/api/marketcap':    'codes=005930,000660,...  (Naver, 1day cache)',
                '/api/universe':     '?q=삼성  (KR 종목 검색 — 자동완성용)',
                '/api/stock-news':   '?code=005930&page=1  (종목별 과거 뉴스 from Naver)',
                '/api/stock-chart':  '?code=005930&range=3mo  (일봉 시계열, news 마커 매핑용)',
                '/api/sweep':        '?top_n=120  (전 종목 composite 신호 sweep, 1시간 캐시)',
                '/api/walkforward':  '?top_n=40&days=120&top_k=8&hold=5  (워크포워드 백테스트, 1일 캐시)',
            },
            'rss_sources': list(RSS_FEEDS.keys()),
            'universe_size': len(UNIVERSE),
        })

    def _api_universe(self, u):
        q = urllib.parse.parse_qs(u.query)
        query = (q.get('q', [''])[0] or '').strip().lower()
        items = list(UNIVERSE.values()) if UNIVERSE else [
            {'code': c, 'name': n, 'market': 'KOSPI'} for c, n in KR_TICKERS.items()
        ]
        if query:
            items = [it for it in items
                     if query in it['name'].lower() or query in it['code']]
            items = items[:50]
        # 검색어 없으면 전체 반환 (클라 자동완성에서 로컬 필터)
        self._send_json({'ts': UNIVERSE_TS * 1000 if UNIVERSE_TS else 0,
                         'count': len(items), 'items': items})

    STOCK_NEWS_CACHE = {}
    def _api_stock_news(self, u):
        q = urllib.parse.parse_qs(u.query)
        code = (q.get('code', [''])[0] or '').strip()
        page = int(q.get('page', ['1'])[0])
        if not re.match(r'^\d{6}$', code):
            return self._send_json({'error': 'invalid code'}, status=400)
        cache_key = f'{code}|{page}'
        now = time.time()
        c = Handler.STOCK_NEWS_CACHE.get(cache_key)
        if c and (now - c[0]) < 300:    # 5분 캐시
            return self._send_json(c[1])
        try:
            data = fetch_stock_news(code, page)
            Handler.STOCK_NEWS_CACHE[cache_key] = (now, data)
            if len(Handler.STOCK_NEWS_CACHE) > 100:
                old = min(Handler.STOCK_NEWS_CACHE.items(), key=lambda kv: kv[1][0])
                Handler.STOCK_NEWS_CACHE.pop(old[0])
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:100]}, status=500)

    WF_CACHE = {}   # config_key → {'ts', 'data', 'computing'}
    def _api_walkforward(self, u):
        q = urllib.parse.parse_qs(u.query)
        top_n = int(q.get('top_n', ['80'])[0])
        days = int(q.get('days', ['120'])[0])
        top_k = int(q.get('top_k', ['8'])[0])
        hold = int(q.get('hold', ['5'])[0])
        mode = q.get('mode', ['blend'])[0]
        if mode not in ('blend', 'price_only', 'news_only', 'attention', 'attn_blend', 'substantive', 'informational'):
            mode = 'blend'
        universe_mode = q.get('universe_mode', ['current'])[0]
        if universe_mode not in ('current', 'kospi200', 'dynamic'):
            universe_mode = 'current'
        use_news = q.get('use_news', ['1'])[0] != '0'
        force = q.get('force', ['0'])[0] == '1'
        # v20.6 — 카테고리 필터 (예: cat_filter=실적,M&A)
        cat_filter_raw = q.get('cat_filter', [''])[0]
        cat_filter = tuple(c.strip() for c in cat_filter_raw.split(',') if c.strip()) if cat_filter_raw else ()
        # v20.6 — 시간 윈도우 shift (약세장 검증용). 0 = 최신, 180 = 6개월 전 시점에서 시작
        start_offset_days = int(q.get('start_offset_days', ['0'])[0])
        start_offset_days = max(0, min(360, start_offset_days))
        key = f'{top_n}|{days}|{top_k}|{hold}|{mode}|{use_news}|{universe_mode}|{",".join(cat_filter)}|{start_offset_days}'
        now = time.time()
        slot = Handler.WF_CACHE.setdefault(key, {'ts': 0, 'data': None, 'computing': False})
        if not force and slot['data'] and (now - slot['ts']) < 86400:    # 1 day
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        if slot['computing'] and slot['data']:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        slot['computing'] = True
        try:
            data = walkforward_backtest(top_n=top_n, days=days, top_k=top_k, hold=hold, use_news=use_news,
                                        mode=mode, universe_mode=universe_mode,
                                        cat_filter=cat_filter, start_offset_days=start_offset_days)
            Handler.WF_CACHE[key] = {'ts': now, 'data': data, 'computing': False}
            self._send_json({'cached': False, **data})
        except Exception as e:
            slot['computing'] = False
            import traceback
            self._send_json({'error': str(e)[:200], 'trace': traceback.format_exc()[-400:]}, status=500)

    # v20.7 — Recent picks forward-test (24h cache = 매일 자동 갱신)
    RECENT_PICKS_CACHE = {}
    def _api_recent_picks(self, u):
        q = urllib.parse.parse_qs(u.query)
        top_n = int(q.get('top_n', ['120'])[0])
        force = q.get('force', ['0'])[0] == '1'
        now = time.time()
        slot = Handler.RECENT_PICKS_CACHE.setdefault(top_n, {'ts': 0, 'data': None, 'computing': False})
        if not force and slot['data'] and (now - slot['ts']) < 86400:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        if slot['computing'] and slot['data']:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        slot['computing'] = True
        try:
            data = fetch_recent_picks(top_n=top_n)
            Handler.RECENT_PICKS_CACHE[top_n] = {'ts': now, 'data': data, 'computing': False}
            self._send_json({'cached': False, **data})
        except Exception as e:
            slot['computing'] = False
            self._send_json({'error': str(e)[:200]}, status=500)

    SWEEP_CACHE = {}   # top_n → {'ts', 'data', 'computing'}
    def _api_sweep(self, u):
        q = urllib.parse.parse_qs(u.query)
        force = q.get('force', ['0'])[0] == '1'
        top_n = int(q.get('top_n', ['120'])[0])
        now = time.time()
        slot = Handler.SWEEP_CACHE.setdefault(top_n, {'ts': 0, 'data': None, 'computing': False})
        if not force and slot['data'] and (now - slot['ts']) < 3600:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        if slot['computing'] and slot['data']:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        slot['computing'] = True
        try:
            data = fetch_sweep(top_n=top_n)
            Handler.SWEEP_CACHE[top_n] = {'ts': now, 'data': data, 'computing': False}
            self._send_json({'cached': False, **data})
        except Exception as e:
            slot['computing'] = False
            self._send_json({'error': str(e)[:200]}, status=500)

    STOCK_CHART_CACHE = {}
    def _api_stock_chart(self, u):
        q = urllib.parse.parse_qs(u.query)
        code = (q.get('code', [''])[0] or '').strip()
        range_ = q.get('range', ['3mo'])[0]
        # 6-digit KR code OR ^index OR XXX=X FX symbol
        if not (re.match(r'^\d{6}$', code) or code.startswith('^') or code.endswith('=X')):
            return self._send_json({'error': 'invalid code'}, status=400)
        cache_key = f'{code}|{range_}'
        now = time.time()
        c = Handler.STOCK_CHART_CACHE.get(cache_key)
        if c and (now - c[0]) < 600:    # 10분 캐시
            return self._send_json(c[1])
        try:
            data = fetch_stock_chart(code, range_)
            Handler.STOCK_CHART_CACHE[cache_key] = (now, data)
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:100]}, status=500)

    def _api_news(self, u):
        q = urllib.parse.parse_qs(u.query)
        sources = q.get('sources', [''])[0].split(',') if q.get('sources') else list(RSS_FEEDS.keys())
        sources = [s.strip() for s in sources if s.strip()]
        limit = int(q.get('limit', ['80'])[0])
        cache_key = f'{",".join(sources)}|{limit}'
        now = time.time()
        c = Handler.NEWS_CACHE
        if c['key'] == cache_key and c['data'] is not None and (now - c['ts']) < 120:
            return self._send_json(c['data'])
        try:
            data = fetch_news(sources, limit)
            Handler.NEWS_CACHE = {'ts': now, 'data': data, 'key': cache_key}
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': f'news_fetch_failed: {e}'}, status=500)

    # 시총 캐시 — 하루 단위로만 갱신
    MCAP_CACHE = {'ts': 0, 'data': None, 'key': ''}

    def _api_marketcap(self, u):
        q = urllib.parse.parse_qs(u.query)
        codes = [c.strip() for c in q.get('codes', [''])[0].split(',') if c.strip()]
        if not codes:
            return self._send_json({'error': 'codes required'}, status=400)
        cache_key = ','.join(sorted(codes))
        now = time.time()
        c = Handler.MCAP_CACHE
        if c['key'] == cache_key and c['data'] is not None and (now - c['ts']) < 86400:
            return self._send_json(c['data'])
        try:
            data = fetch_marketcap(codes)
            Handler.MCAP_CACHE = {'ts': now, 'data': data, 'key': cache_key}
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': f'marketcap_fetch_failed: {e}'}, status=500)

    def _api_quote(self, u):
        q = urllib.parse.parse_qs(u.query)
        codes_raw = q.get('codes', [''])[0]
        codes = [c.strip() for c in codes_raw.split(',') if c.strip()]
        interval = q.get('interval', ['1m'])[0]
        range_ = q.get('range', ['1d'])[0]
        if not codes:
            return self._send_json({'error': 'codes required'}, status=400)
        cache_key = f'{",".join(codes)}|{interval}|{range_}'
        now = time.time()
        cached = Handler.QUOTE_CACHE.get(cache_key)
        if cached and (now - cached[0]) < 60:
            return self._send_json(cached[1])
        try:
            data = fetch_quote(codes, interval, range_)
            Handler.QUOTE_CACHE[cache_key] = (now, data)
            # 캐시 size limit
            if len(Handler.QUOTE_CACHE) > 50:
                oldest = min(Handler.QUOTE_CACHE.items(), key=lambda kv: kv[1][0])
                Handler.QUOTE_CACHE.pop(oldest[0])
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': f'quote_fetch_failed: {e}'}, status=500)

    def log_message(self, fmt, *args):
        # 깔끔한 로그
        sys.stderr.write(f'[{datetime.now().strftime("%H:%M:%S")}] {self.address_string()} {fmt % args}\n')


def main():
    import os, threading
    os.chdir(ROOT)
    # 백그라운드로 universe 로드 (서버 startup 막지 않음)
    threading.Thread(target=reload_universe, daemon=True).start()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler) as srv:
        print(f'╔══════════════════════════════════════════════╗')
        print(f'║  StoryQuant local server running             ║')
        print(f'║  http://127.0.0.1:{PORT}/story_quant.html      ║')
        print(f'║  API: /news /quote /universe /stock-news/-chart ║')
        print(f'╚══════════════════════════════════════════════╝')
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nstopped.')


if __name__ == '__main__':
    main()
