"""시장 어댑터 추상 인터페이스.

각 시장(KR, US, ...)은 이 인터페이스를 구현해 다음 정보를 제공한다:
  - 메타: id / name / currency / tz / 거래시간 / 벤치마크 심볼
  - 종목 universe (코드 → 이름) — 시점별 상위 N
  - RSS 피드 list (key, url) + Google News alias 매핑
  - 분류 키워드 (BULL/BEAR/SUBSTANTIVE/REACTIVE/CATEGORY)
  - 매체 신뢰도 prior
  - 테마 바스켓 (테마명 → 종목 list)
  - 종목 검색 → ticker 후보 (Yahoo Finance 심볼 형식)
"""


class MarketProvider:
    id = 'base'
    name = 'Base'
    currency = 'USD'
    tz_offset_hours = 0
    benchmark_symbol = '^GSPC'   # default S&P 500
    market_open_hour = 9.0       # local time
    market_close_hour = 16.0
    locale = 'en-US'
    other_category = 'Other'     # 무분류 fallback 라벨 (KR='기타')

    # v21.2 — Macro regime → sector 영향 매핑.
    # 형식: { regime_name: { sector_name: ±impact_factor (-1.0 ~ +1.0) } }
    # 'risk_off' = 전쟁/제재/금리인상/CPI 쇼크 → 안전자산·방산↑, 성장주·하이베타↓
    # 'risk_on'  = 평화/금리인하/실업률 개선 → 성장주·소비재↑
    # 'oil_up'   = 유가급등 → 에너지↑ 항공·운송↓
    # 'rate_up'  = 금리상승 → 금융·보험↑ 부동산·테크↓
    macro_sector_impact = {
        'risk_off': {},     # 하위 클래스가 채움
        'risk_on':  {},
        'oil_up':   {},
        'rate_up':  {},
    }
    # 종목 코드 → 섹터 매핑 (간이 hardcode). 시장별 hardcode.
    sector_map = {}      # { 'AAPL': 'tech', '005930': 'tech', ... }

    # 분류 키워드 — 하위 클래스가 채움
    bull_keys = ()
    bear_keys = ()
    substantive_keys = ()
    reactive_keys = ()
    category_keys = {}      # {'카테고리명': (키워드, ...)}
    routine_keys = ()       # 'routine'(예상된) 키워드
    big_surprise_keys = ()  # 'shock' 키워드

    source_priors = {}      # {매체명: 0.0~1.0}

    def __init__(self):
        self._universe_cache = None
        self._universe_ts = 0

    # ── universe ──
    def fetch_universe(self, top_per_market=200):
        """시총 상위 종목 fetch. 반환 {code: {'name', 'market'}}."""
        raise NotImplementedError

    def universe(self):
        """캐시된 universe (load_universe 호출 후 조회)."""
        return self._universe_cache or {}

    def load_universe(self, top_per_market=200):
        """애플리케이션 부팅 시 호출. universe 캐시."""
        try:
            u = self.fetch_universe(top_per_market=top_per_market)
            if u and len(u) > 10:
                self._universe_cache = u
                import time
                self._universe_ts = time.time()
                return u
        except Exception:
            pass
        return self._universe_cache or {}

    # ── 종목 멘션 추출 ──
    def tag_tickers(self, text, limit=6, min_name_len=3):
        """텍스트에서 universe 종목명 매칭 → [{'code', 'name'}]."""
        if not text:
            return []
        out = []
        seen = set()
        items = sorted(self.universe().items(), key=lambda kv: -len(kv[1].get('name') or ''))
        for code, info in items:
            name = info.get('name') or ''
            if len(name) < min_name_len:
                continue
            if name in text and code not in seen:
                out.append({'code': code, 'name': name})
                seen.add(code)
                if len(out) >= limit:
                    break
        return out

    # ── feeds ──
    def get_rss_feeds(self):
        """{source_key: rss_url} 매핑. Google News는 키 prefix 'gn_' 권장."""
        return {}

    def get_paper_map(self):
        """Google News의 source_key → 매체명 매핑 (헤드라인의 ' - 매체' suffix가 비표준일 때 fallback)."""
        return {}

    # ── 가격 ──
    def format_yahoo_symbol(self, code):
        """6자리 코드/티커 → Yahoo Finance 심볼. KR='005930.KS', US='AAPL'."""
        return code

    def stock_news_url(self, code):
        """종목별 뉴스 fetch URL. KR=Naver, US=Yahoo. None 이면 historical만 사용."""
        return None

    def fetch_stock_news_native(self, code, page=1, page_size=20):
        """시장 native 종목 뉴스 API. 실패시 [] 반환. enrich 안 적용 — caller가 함."""
        return []

    # ── 카테고리 ──
    def categories(self):
        return tuple(self.category_keys.keys()) + ('기타',) if '기타' not in self.category_keys else tuple(self.category_keys.keys())

    # ── 테마 ──
    def theme_basket(self):
        """[{'name', 'desc', 'emoji', 'stocks': [{'code','name','weight'}]}]."""
        return []

    def theme_keyword_map(self):
        """{테마명: [키워드, ...]} — 헤드라인에서 테마 매핑용."""
        return {}

    # ── 시총 ──
    def fetch_marketcap(self, codes):
        """{code: {marketCap, last, name, pe, foreignPct}}. 시장별 native (Naver / Yahoo / etc)."""
        return {'ts': 0, 'quotes': [], 'source': self.id}
