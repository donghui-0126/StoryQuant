"""
Centralized ticker configuration for StoryQuant.
Single source of truth for all asset definitions.
"""

TICKERS = {
    # ── Crypto Major ──
    "BTC-USD": {"name": "Bitcoin", "name_ko": "비트코인", "market": "crypto", "sector": "Digital Asset", "keywords": ["bitcoin", "btc", "비트코인"]},
    "ETH-USD": {"name": "Ethereum", "name_ko": "이더리움", "market": "crypto", "sector": "Smart Contract", "keywords": ["ethereum", "eth", "이더리움", "ether"]},
    "SOL-USD": {"name": "Solana", "name_ko": "솔라나", "market": "crypto", "sector": "Smart Contract", "keywords": ["solana", "sol", "솔라나"]},
    "BNB-USD": {"name": "BNB", "name_ko": "바이낸스코인", "market": "crypto", "sector": "Exchange", "keywords": ["bnb", "binance coin", "바이낸스"]},
    "XRP-USD": {"name": "XRP", "name_ko": "리플", "market": "crypto", "sector": "Payment", "keywords": ["xrp", "ripple", "리플"]},
    "ADA-USD": {"name": "Cardano", "name_ko": "카르다노", "market": "crypto", "sector": "Smart Contract", "keywords": ["cardano", "ada", "카르다노"]},
    "DOGE-USD": {"name": "Dogecoin", "name_ko": "도지코인", "market": "crypto", "sector": "Meme", "keywords": ["dogecoin", "doge", "도지"]},
    "AVAX-USD": {"name": "Avalanche", "name_ko": "아발란체", "market": "crypto", "sector": "Smart Contract", "keywords": ["avalanche", "avax", "아발란체"]},
    "DOT-USD": {"name": "Polkadot", "name_ko": "폴카닷", "market": "crypto", "sector": "Interop", "keywords": ["polkadot", "dot", "폴카닷"]},
    "LINK-USD": {"name": "Chainlink", "name_ko": "체인링크", "market": "crypto", "sector": "Oracle", "keywords": ["chainlink", "link", "체인링크"]},
    "MATIC-USD": {"name": "Polygon", "name_ko": "폴리곤", "market": "crypto", "sector": "L2", "keywords": ["polygon", "matic", "폴리곤"]},
    "UNI-USD": {"name": "Uniswap", "name_ko": "유니스왑", "market": "crypto", "sector": "DeFi", "keywords": ["uniswap", "uni", "유니스왑"]},
    "ATOM-USD": {"name": "Cosmos", "name_ko": "코스모스", "market": "crypto", "sector": "Interop", "keywords": ["cosmos", "atom", "코스모스"]},
    "ARB-USD": {"name": "Arbitrum", "name_ko": "아비트럼", "market": "crypto", "sector": "L2", "keywords": ["arbitrum", "arb", "아비트럼"]},
    "OP-USD": {"name": "Optimism", "name_ko": "옵티미즘", "market": "crypto", "sector": "L2", "keywords": ["optimism", "op", "옵티미즘"]},
    "SUI-USD": {"name": "Sui", "name_ko": "수이", "market": "crypto", "sector": "Smart Contract", "keywords": ["sui", "수이"]},

    # ── US Stocks - Big Tech ──
    "NVDA": {"name": "NVIDIA", "name_ko": "엔비디아", "market": "us", "sector": "AI/Semiconductor", "keywords": ["nvidia", "nvda", "엔비디아"]},
    "AAPL": {"name": "Apple", "name_ko": "애플", "market": "us", "sector": "Big Tech", "keywords": ["apple", "aapl", "애플", "iphone"]},
    "MSFT": {"name": "Microsoft", "name_ko": "마이크로소프트", "market": "us", "sector": "Big Tech", "keywords": ["microsoft", "msft", "마이크로소프트", "azure"]},
    "GOOGL": {"name": "Alphabet", "name_ko": "구글", "market": "us", "sector": "Big Tech", "keywords": ["google", "alphabet", "googl", "구글"]},
    "AMZN": {"name": "Amazon", "name_ko": "아마존", "market": "us", "sector": "Big Tech", "keywords": ["amazon", "amzn", "아마존", "aws"]},
    "META": {"name": "Meta", "name_ko": "메타", "market": "us", "sector": "Big Tech", "keywords": ["meta", "facebook", "메타", "instagram"]},
    "TSLA": {"name": "Tesla", "name_ko": "테슬라", "market": "us", "sector": "EV/Energy", "keywords": ["tesla", "tsla", "테슬라", "elon"]},

    # ── US Stocks - Semiconductor ──
    "AMD": {"name": "AMD", "name_ko": "AMD", "market": "us", "sector": "Semiconductor", "keywords": ["amd", "advanced micro"]},
    "AVGO": {"name": "Broadcom", "name_ko": "브로드컴", "market": "us", "sector": "Semiconductor", "keywords": ["broadcom", "avgo", "브로드컴"]},
    "TSM": {"name": "TSMC", "name_ko": "TSMC", "market": "us", "sector": "Semiconductor", "keywords": ["tsmc", "taiwan semi", "TSMC"]},

    # ── US Stocks - Other ──
    "COIN": {"name": "Coinbase", "name_ko": "코인베이스", "market": "us", "sector": "Crypto/Finance", "keywords": ["coinbase", "coin", "코인베이스"]},
    "MSTR": {"name": "MicroStrategy", "name_ko": "마이크로스트래티지", "market": "us", "sector": "Bitcoin Treasury", "keywords": ["microstrategy", "mstr", "마이크로스트래티지"]},
    "MARA": {"name": "Marathon Digital", "name_ko": "마라톤디지털", "market": "us", "sector": "Bitcoin Mining", "keywords": ["marathon", "mara"]},
    "PLTR": {"name": "Palantir", "name_ko": "팔란티어", "market": "us", "sector": "AI/Defense", "keywords": ["palantir", "pltr", "팔란티어"]},

    # ── US ETFs/Index ──
    "SPY": {"name": "S&P 500", "name_ko": "S&P 500", "market": "us", "sector": "Index", "keywords": ["s&p", "spy", "s&p 500"]},
    "QQQ": {"name": "Nasdaq 100", "name_ko": "나스닥 100", "market": "us", "sector": "Index", "keywords": ["nasdaq", "qqq", "나스닥"]},
    "SOXL": {"name": "Semiconductor 3x", "name_ko": "반도체3배", "market": "us", "sector": "Leveraged ETF", "keywords": ["soxl", "반도체 etf"]},

    # ── Korean Stocks - KOSPI Mega Cap ──
    "005930.KS": {"name": "Samsung Electronics", "name_ko": "삼성전자", "market": "kr", "sector": "Semiconductor", "keywords": ["samsung electronics", "삼성전자"]},
    "000660.KS": {"name": "SK Hynix", "name_ko": "SK하이닉스", "market": "kr", "sector": "Semiconductor", "keywords": ["sk hynix", "sk하이닉스", "하이닉스"]},
    "035420.KS": {"name": "Naver", "name_ko": "네이버", "market": "kr", "sector": "Platform/AI", "keywords": ["naver", "네이버"]},
    "035720.KS": {"name": "Kakao", "name_ko": "카카오", "market": "kr", "sector": "Platform", "keywords": ["kakao corp", "카카오"]},
    "373220.KS": {"name": "LG Energy Solution", "name_ko": "LG에너지솔루션", "market": "kr", "sector": "Battery", "keywords": ["lg energy", "lg에너지솔루션", "엘지에너지"]},
    "006400.KS": {"name": "Samsung SDI", "name_ko": "삼성SDI", "market": "kr", "sector": "Battery", "keywords": ["samsung sdi", "삼성sdi"]},
    "051910.KS": {"name": "LG Chem", "name_ko": "LG화학", "market": "kr", "sector": "Chemical/Battery", "keywords": ["lg chem", "lg화학", "엘지화학"]},
    "207940.KS": {"name": "Samsung Biologics", "name_ko": "삼성바이오로직스", "market": "kr", "sector": "Bio", "keywords": ["samsung bio", "삼성바이오로직스", "삼성바이오"]},
    "068270.KS": {"name": "Celltrion", "name_ko": "셀트리온", "market": "kr", "sector": "Bio", "keywords": ["celltrion", "셀트리온"]},
    "066570.KS": {"name": "LG Electronics", "name_ko": "LG전자", "market": "kr", "sector": "Electronics", "keywords": ["lg electronics", "lg전자", "엘지전자"]},
    "032830.KS": {"name": "Samsung Life", "name_ko": "삼성생명", "market": "kr", "sector": "Insurance", "keywords": ["samsung life", "삼성생명"]},

    # ── KOSPI - Auto / Mobility ──
    "005380.KS": {"name": "Hyundai Motor", "name_ko": "현대자동차", "market": "kr", "sector": "Auto", "keywords": ["hyundai motor", "현대차", "현대자동차"]},
    "012330.KS": {"name": "Hyundai Mobis", "name_ko": "현대모비스", "market": "kr", "sector": "Auto Parts", "keywords": ["hyundai mobis", "현대모비스"]},
    "000270.KS": {"name": "Kia", "name_ko": "기아", "market": "kr", "sector": "Auto", "keywords": ["kia motors", "기아차", "기아"]},
    "086280.KS": {"name": "Hyundai Glovis", "name_ko": "현대글로비스", "market": "kr", "sector": "Logistics", "keywords": ["hyundai glovis", "현대글로비스", "글로비스"]},

    # ── KOSPI - Finance ──
    "105560.KS": {"name": "KB Financial", "name_ko": "KB금융", "market": "kr", "sector": "Finance", "keywords": ["kb financial", "kb금융", "국민은행"]},
    "055550.KS": {"name": "Shinhan Financial", "name_ko": "신한지주", "market": "kr", "sector": "Finance", "keywords": ["shinhan financial", "신한지주", "신한금융"]},
    "086790.KS": {"name": "Hana Financial", "name_ko": "하나금융지주", "market": "kr", "sector": "Finance", "keywords": ["hana financial", "하나금융지주", "하나금융"]},
    "316140.KS": {"name": "Woori Financial", "name_ko": "우리금융지주", "market": "kr", "sector": "Finance", "keywords": ["woori financial", "우리금융지주", "우리금융"]},
    "138040.KS": {"name": "Meritz Financial", "name_ko": "메리츠금융지주", "market": "kr", "sector": "Finance", "keywords": ["meritz", "메리츠금융지주", "메리츠"]},
    "323410.KS": {"name": "KakaoBank", "name_ko": "카카오뱅크", "market": "kr", "sector": "Finance/Internet", "keywords": ["kakaobank", "카카오뱅크"]},

    # ── KOSPI - Steel / Materials / Heavy Industry ──
    "005490.KS": {"name": "POSCO Holdings", "name_ko": "포스코홀딩스", "market": "kr", "sector": "Steel/Materials", "keywords": ["posco holdings", "포스코홀딩스", "포스코"]},
    "003670.KS": {"name": "POSCO Future M", "name_ko": "포스코퓨처엠", "market": "kr", "sector": "Battery Materials", "keywords": ["posco future", "포스코퓨처엠"]},
    "010130.KS": {"name": "Korea Zinc", "name_ko": "고려아연", "market": "kr", "sector": "Metals", "keywords": ["korea zinc", "고려아연"]},

    # ── KOSPI - Shipbuilding / Defense ──
    "009540.KS": {"name": "HD KSOE", "name_ko": "HD한국조선해양", "market": "kr", "sector": "Shipbuilding", "keywords": ["hd korea shipbuilding", "hd한국조선해양", "현대중공업그룹"]},
    "329180.KS": {"name": "HD Hyundai Heavy", "name_ko": "HD현대중공업", "market": "kr", "sector": "Shipbuilding", "keywords": ["hd hyundai heavy", "hd현대중공업", "현대중공업"]},
    "267250.KS": {"name": "HD Hyundai", "name_ko": "HD현대", "market": "kr", "sector": "Holdings", "keywords": ["hd hyundai", "hd현대"]},
    "010140.KS": {"name": "Samsung Heavy", "name_ko": "삼성중공업", "market": "kr", "sector": "Shipbuilding", "keywords": ["samsung heavy", "삼성중공업"]},
    "042660.KS": {"name": "Hanwha Ocean", "name_ko": "한화오션", "market": "kr", "sector": "Shipbuilding", "keywords": ["hanwha ocean", "한화오션", "대우조선해양"]},
    "012450.KS": {"name": "Hanwha Aerospace", "name_ko": "한화에어로스페이스", "market": "kr", "sector": "Defense/Aerospace", "keywords": ["hanwha aerospace", "한화에어로스페이스", "한화에어로"]},
    "079550.KS": {"name": "LIG Nex1", "name_ko": "LIG넥스원", "market": "kr", "sector": "Defense", "keywords": ["lig nex1", "lig넥스원"]},
    "047810.KS": {"name": "Korea Aerospace", "name_ko": "한국항공우주", "market": "kr", "sector": "Defense/Aerospace", "keywords": ["korea aerospace", "한국항공우주", "kai"]},
    "064350.KS": {"name": "Hyundai Rotem", "name_ko": "현대로템", "market": "kr", "sector": "Defense/Rail", "keywords": ["hyundai rotem", "현대로템"]},

    # ── KOSPI - Energy / Power ──
    "034020.KS": {"name": "Doosan Enerbility", "name_ko": "두산에너빌리티", "market": "kr", "sector": "Power/Nuclear", "keywords": ["doosan enerbility", "두산에너빌리티"]},
    "000150.KS": {"name": "Doosan", "name_ko": "두산", "market": "kr", "sector": "Holdings", "keywords": ["doosan corp", "두산"]},
    "267260.KS": {"name": "HD Hyundai Electric", "name_ko": "HD현대일렉트릭", "market": "kr", "sector": "Power Equipment", "keywords": ["hd hyundai electric", "hd현대일렉트릭", "현대일렉트릭"]},
    "010120.KS": {"name": "LS Electric", "name_ko": "LS ELECTRIC", "market": "kr", "sector": "Power Equipment", "keywords": ["ls electric", "ls일렉트릭", "ls electric"]},
    "015760.KS": {"name": "KEPCO", "name_ko": "한국전력", "market": "kr", "sector": "Utility", "keywords": ["kepco", "한국전력", "한전"]},

    # ── KOSPI - Telecom / Consumer ──
    "030200.KS": {"name": "KT", "name_ko": "KT", "market": "kr", "sector": "Telecom", "keywords": ["kt corp", "케이티", "kt"]},
    "017670.KS": {"name": "SK Telecom", "name_ko": "SK텔레콤", "market": "kr", "sector": "Telecom", "keywords": ["sk telecom", "sk텔레콤", "sk텔"]},
    "032640.KS": {"name": "LG Uplus", "name_ko": "LG유플러스", "market": "kr", "sector": "Telecom", "keywords": ["lg uplus", "lg유플러스"]},
    "033780.KS": {"name": "KT&G", "name_ko": "KT&G", "market": "kr", "sector": "Tobacco/Consumer", "keywords": ["kt&g", "kt앤지"]},
    "139480.KS": {"name": "Emart", "name_ko": "이마트", "market": "kr", "sector": "Retail", "keywords": ["emart", "이마트"]},
    "004170.KS": {"name": "Shinsegae", "name_ko": "신세계", "market": "kr", "sector": "Retail", "keywords": ["shinsegae", "신세계"]},
    "271560.KS": {"name": "Orion", "name_ko": "오리온", "market": "kr", "sector": "Food", "keywords": ["orion confec", "오리온"]},
    "097950.KS": {"name": "CJ CheilJedang", "name_ko": "CJ제일제당", "market": "kr", "sector": "Food", "keywords": ["cj cheiljedang", "cj제일제당"]},
    "090430.KS": {"name": "Amorepacific", "name_ko": "아모레퍼시픽", "market": "kr", "sector": "Beauty", "keywords": ["amorepacific", "아모레퍼시픽", "아모레"]},
    "352820.KS": {"name": "HYBE", "name_ko": "하이브", "market": "kr", "sector": "Entertainment", "keywords": ["hybe", "하이브", "bts"]},

    # ── KOSPI - Logistics / Shipping ──
    "011200.KS": {"name": "HMM", "name_ko": "HMM", "market": "kr", "sector": "Shipping", "keywords": ["hmm", "현대상선"]},
    "180640.KS": {"name": "Hanjin KAL", "name_ko": "한진칼", "market": "kr", "sector": "Holdings/Air", "keywords": ["hanjin kal", "한진칼"]},
    "003490.KS": {"name": "Korean Air", "name_ko": "대한항공", "market": "kr", "sector": "Airline", "keywords": ["korean air", "대한항공"]},

    # ── KOSDAQ - Battery Materials ──
    "086520.KQ": {"name": "EcoPro", "name_ko": "에코프로", "market": "kr", "sector": "Battery Materials", "keywords": ["ecopro", "에코프로"]},
    "247540.KQ": {"name": "EcoPro BM", "name_ko": "에코프로비엠", "market": "kr", "sector": "Battery Materials", "keywords": ["ecopro bm", "에코프로비엠"]},
    "066970.KQ": {"name": "L&F", "name_ko": "엘앤에프", "market": "kr", "sector": "Battery Materials", "keywords": ["l&f", "엘앤에프"]},

    # ── KOSDAQ - Semiconductor Equipment ──
    "058470.KQ": {"name": "Leeno Industrial", "name_ko": "리노공업", "market": "kr", "sector": "Semi Equipment", "keywords": ["leeno", "리노공업"]},
    "403870.KQ": {"name": "HPSP", "name_ko": "HPSP", "market": "kr", "sector": "Semi Equipment", "keywords": ["hpsp"]},
    "240810.KQ": {"name": "Wonik IPS", "name_ko": "원익IPS", "market": "kr", "sector": "Semi Equipment", "keywords": ["wonik ips", "원익ips", "원익"]},
    "005290.KQ": {"name": "Dongjin Semichem", "name_ko": "동진쎄미켐", "market": "kr", "sector": "Semi Materials", "keywords": ["dongjin semichem", "동진쎄미켐", "동진"]},

    # ── KOSDAQ - Bio / Pharma ──
    "196170.KQ": {"name": "Alteogen", "name_ko": "알테오젠", "market": "kr", "sector": "Bio", "keywords": ["alteogen", "알테오젠"]},
    "028300.KQ": {"name": "HLB", "name_ko": "HLB", "market": "kr", "sector": "Bio", "keywords": ["hlb"]},
    "302440.KS": {"name": "SK BioScience", "name_ko": "SK바이오사이언스", "market": "kr", "sector": "Bio", "keywords": ["sk bioscience", "sk바이오사이언스", "sk바이오"]},

    # ── KOSDAQ - Game / Entertainment ──
    "259960.KS": {"name": "Krafton", "name_ko": "크래프톤", "market": "kr", "sector": "Game", "keywords": ["krafton", "크래프톤"]},
    "263750.KQ": {"name": "Pearl Abyss", "name_ko": "펄어비스", "market": "kr", "sector": "Game", "keywords": ["pearl abyss", "펄어비스"]},
    "293490.KQ": {"name": "Kakao Games", "name_ko": "카카오게임즈", "market": "kr", "sector": "Game", "keywords": ["kakao games", "카카오게임즈"]},
    "036570.KS": {"name": "NCSoft", "name_ko": "엔씨소프트", "market": "kr", "sector": "Game", "keywords": ["ncsoft", "엔씨소프트", "엔씨"]},
    "041510.KQ": {"name": "SM Entertainment", "name_ko": "에스엠", "market": "kr", "sector": "Entertainment", "keywords": ["sm entertainment", "에스엠"]},
    "035900.KQ": {"name": "JYP", "name_ko": "JYP Ent.", "market": "kr", "sector": "Entertainment", "keywords": ["jyp", "jyp엔터테인먼트"]},

    # ── ADR (technically NYSE but Korean exposure) ──
    "CPNG": {"name": "Coupang", "name_ko": "쿠팡", "market": "kr", "sector": "E-commerce", "keywords": ["coupang", "쿠팡"]},

    # ── Japanese Stocks ──
    "7203.T": {"name": "Toyota", "name_ko": "토요타", "market": "jp", "sector": "Auto", "keywords": ["toyota", "토요타"]},
    "6758.T": {"name": "Sony", "name_ko": "소니", "market": "jp", "sector": "Electronics", "keywords": ["sony", "소니"]},

    # ── Commodities/FX (via ETF) ──
    "GLD": {"name": "Gold ETF", "name_ko": "금", "market": "us", "sector": "Commodity", "keywords": ["gold", "금", "금값"]},
    "USO": {"name": "Oil ETF", "name_ko": "원유", "market": "us", "sector": "Commodity", "keywords": ["oil", "crude", "원유", "유가"]},
}

# ── Helper functions ──

def get_all_tickers() -> list[str]:
    return list(TICKERS.keys())

def get_tickers_by_market(market: str) -> list[str]:
    return [t for t, cfg in TICKERS.items() if cfg["market"] == market]

def get_market_map() -> dict[str, str]:
    return {t: cfg["market"] for t, cfg in TICKERS.items()}

def get_ticker_keywords() -> dict[str, list[str]]:
    return {t: cfg["keywords"] for t, cfg in TICKERS.items()}

def get_ticker_name(ticker: str, lang: str = "en") -> str:
    cfg = TICKERS.get(ticker)
    if not cfg:
        return ticker
    return cfg["name_ko"] if lang == "ko" else cfg["name"]

def get_sector(ticker: str) -> str:
    return TICKERS.get(ticker, {}).get("sector", "Unknown")

def get_price_tickers() -> dict[str, list[str]]:
    """Group tickers by market for price fetching."""
    result = {}
    for ticker, cfg in TICKERS.items():
        market = cfg["market"]
        result.setdefault(market, []).append(ticker)
    return result
