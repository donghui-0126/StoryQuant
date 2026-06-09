"""미국 시장 (NYSE + NASDAQ) 어댑터.

데이터 소스:
  - Universe: Wikipedia S&P 500 list 스크래핑
  - 가격: Yahoo Finance v8 chart (auth 불필요)
  - 종목별 뉴스: Google News 검색 (예: "AAPL stock")
  - 시장 RSS: Google News 키워드 (Reuters, WSJ, CNBC, MarketWatch site:)
  - 키워드: 영문 BULL/BEAR/SUBSTANTIVE/REACTIVE/CATEGORY
"""
import re
import time
import urllib.parse

from .base import MarketProvider
from ..utils.http import http_get
from ..utils.parsing import decode_entities, parse_date


# ─── 영문 분류 키워드 (초기 시드) ─────────────────────────────
BULL_KEYS = (
    'surge', 'soar', 'jump', 'rally', 'gain', 'rise', 'climb', 'breakout',
    'beat', 'beats', 'beat estimates', 'top estimate', 'earnings beat',
    'record high', '52-week high', 'all-time high',
    'upgrade', 'buy rating', 'overweight', 'outperform',
    'expansion', 'growth', 'acquisition', 'partnership', 'deal',
    'approve', 'approved', 'win', 'awarded', 'launches', 'unveil',
    'optimistic', 'bullish',
)
BEAR_KEYS = (
    'plunge', 'tumble', 'slump', 'fall', 'drop', 'sink', 'crash', 'slide',
    'miss', 'missed', 'miss estimates', 'earnings miss',
    'record low', '52-week low',
    'downgrade', 'sell rating', 'underweight', 'underperform',
    'cut', 'lower guidance', 'warn', 'lawsuit', 'sec investigation',
    'recall', 'fine', 'penalty', 'bankruptcy', 'delisting',
    'layoff', 'job cut', 'pessimistic', 'bearish',
)
REACTIVE_KEYS = (
    'surge', 'plunge', 'soar', 'tumble', 'rally', 'crash', 'sell-off',
    'jumps', 'drops', 'rises', 'falls',
    'breakout', 'breakdown', 'support', 'resistance',
    'unusual volume', 'heavy trading',
    'top gainer', 'top loser', 'biggest mover',
)
SUBSTANTIVE_KEYS = (
    'earnings', 'revenue', 'eps', 'guidance', 'outlook',
    'merger', 'acquisition', 'm&a', 'divestiture', 'spin-off', 'ipo',
    'fda', 'approval', 'phase 3', 'phase 2', 'phase 1', 'patent',
    'ceo', 'resigns', 'appoints', 'cfo',
    'dividend', 'buyback', 'split',
    'contract', 'partnership', 'mou', 'launch', 'unveil',
    'lawsuit', 'settlement', 'investigation',
    'tariff', 'regulation', 'subsidy',
)

CATEGORY_KEYS = {
    'Earnings': ('earnings', 'revenue', 'eps', 'guidance', 'beat', 'miss', 'profit', 'loss'),
    'M&A': ('merger', 'acquisition', 'm&a', 'spin-off', 'divestiture', 'tender offer'),
    'Clinical/Reg': ('fda', 'approval', 'phase 3', 'phase 2', 'phase 1', 'recall',
                     'lawsuit', 'investigation', 'sec', 'doj'),
    'Leadership': ('ceo', 'cfo', 'resigns', 'appoints', 'board', 'executive'),
    'Capital': ('dividend', 'buyback', 'split', 'offering', 'secondary'),
    'Product/Biz': ('contract', 'partnership', 'mou', 'launch', 'unveil', 'patent',
                    'product', 'collaboration'),
    # v21.2 — Macro·Geopolitics
    'Macro·Geopolitics': (
        # War / geopolitics
        'war', 'invasion', 'airstrike', 'missile', 'drone', 'nuclear', 'ceasefire',
        'ukraine', 'russia', 'israel', 'iran', 'hamas', 'taiwan strait', 'north korea',
        'sanctions', 'embargo', 'tariff', 'trade war', 'export control', 'decoupling',
        # Monetary / rates
        'federal reserve', 'fed ', 'fomc', 'rate hike', 'rate cut', 'basis points',
        'jerome powell', 'treasury yield', 'yield curve', '10-year',
        # Inflation / economy
        'cpi', 'ppi', 'inflation', 'deflation', 'unemployment', 'gdp', 'recession',
        'consumer price', 'jobs report', 'retail sales', 'pce',
        # Commodities
        'crude oil', 'wti', 'brent', 'opec', 'opec+', 'oil supply',
        'natural gas', 'copper', 'gold price', 'commodities',
        # Politics / policy
        'election', 'impeachment', 'white house', 'congress', 'shutdown',
        'currency war', 'dollar strength', 'dollar weakness', 'yuan',
    ),
}

ROUTINE_KEYS = ('earnings report', 'guidance', 'consensus', 'expected', 'analyst forecast')
BIG_SURPRISE_KEYS = (
    'surprise', 'shock', 'soars', 'plunges', 'all-time high', 'all-time low',
    'recall', 'lawsuit', 'investigation', 'fine',
    'm&a', 'merger', 'acquisition', 'fda approval', 'patent',
    'ceo resigns', 'sudden', 'unexpectedly', 'bankruptcy',
)

SOURCE_PRIORS = {
    # Tier 1: 정통 통신사·일간지
    'Reuters': 1.00, 'reuters.com': 1.00,
    'Bloomberg': 0.95, 'bloomberg.com': 0.95,
    'Wall Street Journal': 0.95, 'WSJ': 0.95, 'wsj.com': 0.95,
    'Financial Times': 0.92, 'FT': 0.92, 'ft.com': 0.92,
    'AP': 0.95, 'Associated Press': 0.95, 'apnews.com': 0.95,
    # Tier 2: 메이저 비즈니스
    'CNBC': 0.85, 'cnbc.com': 0.85,
    "Barron's": 0.88, 'Barrons': 0.88, 'barrons.com': 0.88,
    'MarketWatch': 0.80, 'marketwatch.com': 0.80,
    "Investor's Business Daily": 0.85, 'IBD': 0.85, 'investors.com': 0.85,
    'Axios': 0.78, 'axios.com': 0.78,
    'Fortune': 0.78, 'fortune.com': 0.78,
    'Forbes': 0.72, 'forbes.com': 0.72,
    'Yahoo Finance': 0.75, 'finance.yahoo.com': 0.75,
    'Business Insider': 0.65, 'businessinsider.com': 0.65,
    # Tier 3: 대체/리테일 oriented
    'Seeking Alpha': 0.55, 'seekingalpha.com': 0.55,
    'Benzinga': 0.55, 'benzinga.com': 0.55,
    'TheStreet': 0.60, 'thestreet.com': 0.60,
    'Zacks': 0.65, 'zacks.com': 0.65, 'Zacks Investment Research': 0.65,
    'Stock Titan': 0.50, 'MarketBeat': 0.55,
    # 일반
    'GNews': 0.55, 'gnews': 0.55,
    'GNews Tech': 0.55, 'GNews Biotech': 0.55, 'GNews Energy': 0.55,
}

# US 시총 상위 100 — 2025-Q4 기준 mcap 정렬 (분기마다 수동 갱신).
# Wikipedia S&P 500 alpha 정렬을 보완해서, sweep top_n=120 호출 시 큰 종목 보장.
TOP_BY_MCAP = (
    ('AAPL', 'Apple'),         ('MSFT', 'Microsoft'),     ('NVDA', 'NVIDIA'),
    ('GOOGL', 'Alphabet (A)'), ('GOOG', 'Alphabet (C)'),  ('AMZN', 'Amazon'),
    ('META', 'Meta Platforms'),('BRK-B', 'Berkshire Hathaway'), ('AVGO', 'Broadcom'),
    ('TSLA', 'Tesla'),         ('LLY', 'Eli Lilly'),      ('JPM', 'JPMorgan Chase'),
    ('V', 'Visa'),             ('WMT', 'Walmart'),        ('UNH', 'UnitedHealth'),
    ('XOM', 'Exxon Mobil'),    ('MA', 'Mastercard'),      ('PG', 'Procter & Gamble'),
    ('JNJ', 'Johnson & Johnson'), ('ORCL', 'Oracle'),     ('HD', 'Home Depot'),
    ('COST', 'Costco'),        ('ABBV', 'AbbVie'),        ('NFLX', 'Netflix'),
    ('KO', 'Coca-Cola'),       ('BAC', 'Bank of America'),('CVX', 'Chevron'),
    ('CRM', 'Salesforce'),     ('AMD', 'AMD'),            ('PEP', 'PepsiCo'),
    ('TMUS', 'T-Mobile'),      ('ADBE', 'Adobe'),         ('LIN', 'Linde'),
    ('TMO', 'Thermo Fisher'),  ('CSCO', 'Cisco'),         ('MCD', "McDonald's"),
    ('ACN', 'Accenture'),      ('WFC', 'Wells Fargo'),    ('ABT', 'Abbott'),
    ('DIS', 'Disney'),         ('GE', 'GE Aerospace'),    ('IBM', 'IBM'),
    ('PM', 'Philip Morris'),   ('MRK', 'Merck'),          ('CAT', 'Caterpillar'),
    ('VZ', 'Verizon'),         ('TXN', 'Texas Instruments'),('AXP', 'American Express'),
    ('INTU', 'Intuit'),        ('GS', 'Goldman Sachs'),   ('MS', 'Morgan Stanley'),
    ('NOW', 'ServiceNow'),     ('QCOM', 'Qualcomm'),      ('PFE', 'Pfizer'),
    ('AMAT', 'Applied Materials'), ('ISRG', 'Intuitive Surgical'), ('NEE', 'NextEra Energy'),
    ('UBER', 'Uber'),          ('SPGI', 'S&P Global'),    ('BX', 'Blackstone'),
    ('RTX', 'RTX Corp'),       ('PLTR', 'Palantir'),      ('UNP', 'Union Pacific'),
    ('PGR', 'Progressive'),    ('LOW', "Lowe's"),         ('BKNG', 'Booking Holdings'),
    ('T', 'AT&T'),             ('SCHW', 'Charles Schwab'),('HON', 'Honeywell'),
    ('SYK', 'Stryker'),        ('TJX', 'TJX'),            ('BLK', 'BlackRock'),
    ('GILD', 'Gilead'),        ('ETN', 'Eaton'),          ('VRTX', 'Vertex'),
    ('PANW', 'Palo Alto Networks'), ('ADP', 'ADP'),       ('ANET', 'Arista Networks'),
    ('LRCX', 'Lam Research'),  ('CB', 'Chubb'),           ('C', 'Citigroup'),
    ('MU', 'Micron'),          ('PLD', 'Prologis'),       ('MDT', 'Medtronic'),
    ('REGN', 'Regeneron'),     ('FI', 'Fiserv'),          ('CMCSA', 'Comcast'),
    ('CI', 'Cigna'),           ('SBUX', 'Starbucks'),     ('AMT', 'American Tower'),
    ('BSX', 'Boston Scientific'), ('NKE', 'Nike'),        ('KKR', 'KKR'),
    ('DE', 'Deere'),           ('SHW', 'Sherwin-Williams'), ('ZTS', 'Zoetis'),
    ('ELV', 'Elevance Health'),('TT', 'Trane Technologies'), ('CMG', 'Chipotle'),
    ('CRWD', 'CrowdStrike'),   ('MO', 'Altria'),          ('GEV', 'GE Vernova'),
)

RSS_FEEDS = {
    # ─── Tier 1: 정통 통신사 / 일간지 (highest reliability) ───
    'gn_reuters':       'https://news.google.com/rss/search?q=site:reuters.com+(stock+OR+market+OR+earnings)&hl=en-US&gl=US&ceid=US:en',
    'gn_bloomberg':     'https://news.google.com/rss/search?q=site:bloomberg.com+(stock+OR+market+OR+earnings)&hl=en-US&gl=US&ceid=US:en',
    'gn_wsj':           'https://news.google.com/rss/search?q=site:wsj.com+(stock+OR+market+OR+earnings)&hl=en-US&gl=US&ceid=US:en',
    'gn_ft':            'https://news.google.com/rss/search?q=site:ft.com+(stock+OR+market+OR+earnings)&hl=en-US&gl=US&ceid=US:en',
    'gn_ap':            'https://news.google.com/rss/search?q=site:apnews.com+(stock+OR+market+OR+economy)&hl=en-US&gl=US&ceid=US:en',
    # ─── Tier 2: 메이저 비즈니스 미디어 ───
    'gn_cnbc':          'https://news.google.com/rss/search?q=site:cnbc.com+market&hl=en-US&gl=US&ceid=US:en',
    'gn_barrons':       'https://news.google.com/rss/search?q=site:barrons.com&hl=en-US&gl=US&ceid=US:en',
    'gn_marketwatch':   'https://news.google.com/rss/search?q=site:marketwatch.com&hl=en-US&gl=US&ceid=US:en',
    'gn_ibd':           'https://news.google.com/rss/search?q=site:investors.com+(stock+OR+market)&hl=en-US&gl=US&ceid=US:en',
    'gn_axios':         'https://news.google.com/rss/search?q=site:axios.com+markets&hl=en-US&gl=US&ceid=US:en',
    'gn_fortune':       'https://news.google.com/rss/search?q=site:fortune.com+(stock+OR+market)&hl=en-US&gl=US&ceid=US:en',
    'gn_forbes':        'https://news.google.com/rss/search?q=site:forbes.com+(stock+OR+market)&hl=en-US&gl=US&ceid=US:en',
    'gn_yahoofin':      'https://news.google.com/rss/search?q=site:finance.yahoo.com&hl=en-US&gl=US&ceid=US:en',
    'gn_businessinsider':'https://news.google.com/rss/search?q=site:businessinsider.com+(stock+OR+market)&hl=en-US&gl=US&ceid=US:en',
    # ─── Tier 3: 대체/기타 ───
    'gn_seekingalpha':  'https://news.google.com/rss/search?q=site:seekingalpha.com&hl=en-US&gl=US&ceid=US:en',
    'gn_benzinga':      'https://news.google.com/rss/search?q=site:benzinga.com&hl=en-US&gl=US&ceid=US:en',
    'gn_thestreet':     'https://news.google.com/rss/search?q=site:thestreet.com&hl=en-US&gl=US&ceid=US:en',
    'gn_zacks':         'https://news.google.com/rss/search?q=site:zacks.com&hl=en-US&gl=US&ceid=US:en',
    # ─── 일반 검색 (catch-all) ───
    'gn_us_market':     'https://news.google.com/rss/search?q=stock+market+earnings&hl=en-US&gl=US&ceid=US:en',
    'gn_us_tech':       'https://news.google.com/rss/search?q=tech+stock+(NVDA+OR+AAPL+OR+MSFT+OR+GOOG+OR+META)&hl=en-US&gl=US&ceid=US:en',
    'gn_us_biotech':    'https://news.google.com/rss/search?q=biotech+(FDA+OR+clinical+OR+approval)+stock&hl=en-US&gl=US&ceid=US:en',
    'gn_us_energy':     'https://news.google.com/rss/search?q=oil+gas+energy+stock&hl=en-US&gl=US&ceid=US:en',
}

GNEWS_PAPER_MAP = {
    'gn_reuters':        'Reuters',
    'gn_bloomberg':      'Bloomberg',
    'gn_wsj':            'WSJ',
    'gn_ft':             'Financial Times',
    'gn_ap':             'AP',
    'gn_cnbc':           'CNBC',
    'gn_barrons':        "Barron's",
    'gn_marketwatch':    'MarketWatch',
    'gn_ibd':            "Investor's Business Daily",
    'gn_axios':          'Axios',
    'gn_fortune':        'Fortune',
    'gn_forbes':         'Forbes',
    'gn_yahoofin':       'Yahoo Finance',
    'gn_businessinsider':'Business Insider',
    'gn_seekingalpha':   'Seeking Alpha',
    'gn_benzinga':       'Benzinga',
    'gn_thestreet':      'TheStreet',
    'gn_zacks':          'Zacks',
    'gn_us_market':      'GNews',
    'gn_us_tech':        'GNews Tech',
    'gn_us_biotech':     'GNews Biotech',
    'gn_us_energy':      'GNews Energy',
}


# US 종목 → 섹터 매핑 (TOP_BY_MCAP 100개 + 주요)
US_SECTOR_MAP = {
    # tech (Big Tech / Semis / SaaS)
    'AAPL': 'tech', 'MSFT': 'tech', 'NVDA': 'tech', 'GOOGL': 'tech', 'GOOG': 'tech',
    'AMZN': 'tech', 'META': 'tech', 'AVGO': 'tech', 'ORCL': 'tech', 'NFLX': 'tech',
    'CRM': 'tech', 'AMD': 'tech', 'ADBE': 'tech', 'TMUS': 'tech', 'CSCO': 'tech',
    'IBM': 'tech', 'TXN': 'tech', 'INTU': 'tech', 'NOW': 'tech', 'QCOM': 'tech',
    'AMAT': 'tech', 'PLTR': 'tech', 'PANW': 'tech', 'ANET': 'tech', 'LRCX': 'tech',
    'MU': 'tech', 'CMCSA': 'tech', 'CRWD': 'tech', 'UBER': 'tech',
    # financials
    'JPM': 'financials', 'V': 'financials', 'MA': 'financials', 'BAC': 'financials',
    'WFC': 'financials', 'AXP': 'financials', 'GS': 'financials', 'MS': 'financials',
    'SPGI': 'financials', 'BX': 'financials', 'PGR': 'financials', 'SCHW': 'financials',
    'BLK': 'financials', 'CB': 'financials', 'C': 'financials', 'BRK-B': 'financials',
    'KKR': 'financials', 'FI': 'financials',
    # healthcare / biotech
    'LLY': 'healthcare', 'UNH': 'healthcare', 'JNJ': 'healthcare', 'ABBV': 'healthcare',
    'MRK': 'healthcare', 'TMO': 'healthcare', 'PFE': 'healthcare', 'ABT': 'healthcare',
    'ISRG': 'healthcare', 'GILD': 'healthcare', 'VRTX': 'healthcare', 'REGN': 'healthcare',
    'SYK': 'healthcare', 'MDT': 'healthcare', 'BSX': 'healthcare', 'CI': 'healthcare',
    'ELV': 'healthcare', 'ZTS': 'healthcare',
    # consumer / retail
    'WMT': 'consumer', 'PG': 'consumer', 'HD': 'consumer', 'COST': 'consumer',
    'KO': 'consumer', 'PEP': 'consumer', 'MCD': 'consumer', 'NKE': 'consumer',
    'SBUX': 'consumer', 'TJX': 'consumer', "LOW": 'consumer', 'CMG': 'consumer',
    'PM': 'consumer', 'MO': 'consumer', 'DIS': 'consumer', 'BKNG': 'consumer',
    # energy / oil
    'XOM': 'energy', 'CVX': 'energy',
    # industrials / defense / aerospace
    'CAT': 'industrials', 'GE': 'defense', 'RTX': 'defense', 'HON': 'industrials',
    'DE': 'industrials', 'UNP': 'transport', 'ETN': 'industrials', 'TT': 'industrials',
    # utilities / real estate
    'NEE': 'utility', 'AMT': 'real_estate', 'PLD': 'real_estate',
    # materials
    'LIN': 'materials', 'SHW': 'materials',
    # telecom
    'T': 'telecom', 'VZ': 'telecom',
    # autos
    'TSLA': 'auto', 'GEV': 'industrials',
    # ADP/payroll
    'ADP': 'financials',
    # accenture etc
    'ACN': 'tech',
    # airbnb
    'ABNB': 'consumer',
}

# US Macro regime → sector 영향
US_MACRO_SECTOR_IMPACT = {
    'risk_off': {
        'defense': +0.7, 'energy': +0.3, 'utility': +0.4, 'consumer': +0.2,
        'healthcare': +0.2, 'real_estate': +0.1,
        'tech': -0.6, 'financials': -0.4, 'auto': -0.5, 'industrials': -0.3,
        'transport': -0.5, 'materials': -0.3,
    },
    'risk_on': {
        'tech': +0.6, 'consumer': +0.4, 'auto': +0.4, 'industrials': +0.3,
        'transport': +0.4, 'financials': +0.3, 'materials': +0.3,
        'defense': -0.2, 'utility': -0.3, 'real_estate': -0.2,
    },
    'oil_up': {
        'energy': +0.8, 'materials': +0.2, 'defense': +0.1,
        'transport': -0.6, 'auto': -0.4, 'consumer': -0.3, 'tech': -0.1,
    },
    'rate_up': {
        'financials': +0.5,                                    # 순이자마진 확대
        'tech': -0.5, 'real_estate': -0.6, 'utility': -0.4,    # duration risk
        'consumer': -0.3, 'auto': -0.3,
    },
    'usd_strong': {
        'consumer': -0.2, 'tech': -0.3, 'industrials': -0.3,   # 해외 매출 비중 큰 기업 ↓
        'energy': -0.2, 'materials': -0.2,
        'financials': +0.2, 'real_estate': +0.1,
    },
}


class UsMarket(MarketProvider):
    id = 'us'
    name = 'United States (NYSE + NASDAQ)'
    currency = 'USD'
    tz_offset_hours = -5     # ET (NY)
    benchmark_symbol = '^GSPC'
    market_open_hour = 9.5
    market_close_hour = 16.0
    locale = 'en-US'
    other_category = 'Other'
    sector_map = US_SECTOR_MAP
    macro_sector_impact = US_MACRO_SECTOR_IMPACT

    bull_keys = BULL_KEYS
    bear_keys = BEAR_KEYS
    substantive_keys = SUBSTANTIVE_KEYS
    reactive_keys = REACTIVE_KEYS
    category_keys = CATEGORY_KEYS
    routine_keys = ROUTINE_KEYS
    big_surprise_keys = BIG_SURPRISE_KEYS
    source_priors = SOURCE_PRIORS

    def __init__(self):
        super().__init__()
        # 시드: hardcoded mcap 우선순위
        self._universe_cache = {c: {'name': n, 'market': 'US'} for c, n in TOP_BY_MCAP}

    def fetch_universe(self, top_per_market=200):
        """Hardcoded TOP_BY_MCAP (mcap 정렬) + Wikipedia S&P 500 list (알파벳 추가) 병합.
           dict insertion order 가 보존되므로 list(univ.keys())[:N] 하면 mcap 우선."""
        out = {}
        # 1. mcap 우선순위 (먼저 채움)
        for code, name in TOP_BY_MCAP:
            out[code] = {'name': name, 'market': 'US'}
        # 2. Wikipedia 스크래핑 — 나머지 종목 보충
        try:
            raw = http_get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', timeout=15)
            html = raw.decode('utf-8', errors='replace')
            tbl_match = re.search(r'<table[^>]*id="constituents"[^>]*>(.*?)</table>', html, re.S)
            if tbl_match:
                tbl = tbl_match.group(1)
                row_pat = re.compile(
                    r'<tr>\s*<td[^>]*>\s*<a[^>]*>([A-Z][A-Z0-9\.\-]*)</a>.*?<td[^>]*>\s*<a[^>]*>([^<]+)</a>',
                    re.S,
                )
                for m in row_pat.finditer(tbl):
                    symbol = m.group(1).strip()
                    name = decode_entities(m.group(2)).strip()
                    if symbol and name:
                        yahoo_sym = symbol.replace('.', '-')
                        if yahoo_sym not in out:
                            out[yahoo_sym] = {'name': name, 'market': 'US'}
                    if len(out) >= top_per_market:
                        break
        except Exception as e:
            print(f'[US universe] Wikipedia fetch failed: {e} — falling back to hardcoded TOP_BY_MCAP')
        return out

    def get_rss_feeds(self):
        return RSS_FEEDS

    def get_paper_map(self):
        return GNEWS_PAPER_MAP

    def format_yahoo_symbol(self, code):
        return code

    def yahoo_symbol_candidates(self, code):
        return [code]

    def fetch_stock_news_native(self, code, page=1, page_size=20):
        """Google News search for {ticker} stock — US 종목별 뉴스 (Yahoo 직접 RSS는 차단됨)."""
        # 회사명도 함께 검색해야 ticker 외 회사명 멘션 헤드라인도 잡힘
        info = self._universe_cache.get(code, {}) if self._universe_cache else {}
        company_name = info.get('name', '')
        # 1차: ticker stock
        query = f'{code} stock'
        url = f'https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en'
        try:
            raw = http_get(url, timeout=10)
            xml = raw.decode('utf-8', errors='replace')
        except Exception:
            return []
        articles = []
        for m in re.finditer(r'<item>(.*?)</item>', xml, re.S):
            body = m.group(1)
            title_m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S)
            date_m = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', body, re.S)
            link_m = re.search(r'<link[^>]*>(.*?)</link>', body, re.S)
            if not title_m:
                continue
            title = decode_entities(title_m.group(1).strip())
            sep = title.rfind(' - ')
            paper = title[sep+3:].strip() if sep > 0 else 'GNews'
            title = title[:sep].strip() if sep > 0 else title
            ts = parse_date(date_m.group(1).strip(), default_tz_offset_hours=-5) if date_m else 0
            articles.append({
                'title': title,
                'body': '',
                'link': link_m.group(1).strip() if link_m else '',
                'paper': paper,
                'ts': ts,
            })
            if len(articles) >= page_size * page:
                break
        # paginate (간단 — Google News는 page 안 받음)
        start = (page - 1) * page_size
        return articles[start:start + page_size]

    def fetch_marketcap(self, codes):
        """TODO: Yahoo Finance v8 quote 또는 yahoo.com/quote HTML 스크래핑.
           현재는 stub — 'current' universe mode만 사용 (시점별 ranking 없음)."""
        return {'ts': int(time.time() * 1000), 'quotes': [], 'source': 'us-stub'}


provider = UsMarket()
