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

    # ── Korean Stocks ──
    "005930.KS": {"name": "Samsung Electronics", "name_ko": "삼성전자", "market": "kr", "sector": "Semiconductor", "keywords": ["samsung", "삼성전자", "삼성"]},
    "000660.KS": {"name": "SK Hynix", "name_ko": "SK하이닉스", "market": "kr", "sector": "Semiconductor", "keywords": ["sk hynix", "sk하이닉스", "하이닉스"]},
    "035420.KS": {"name": "Naver", "name_ko": "네이버", "market": "kr", "sector": "Platform/AI", "keywords": ["naver", "네이버"]},
    "035720.KS": {"name": "Kakao", "name_ko": "카카오", "market": "kr", "sector": "Platform", "keywords": ["kakao", "카카오"]},
    "373220.KS": {"name": "LG Energy Solution", "name_ko": "LG에너지솔루션", "market": "kr", "sector": "Battery", "keywords": ["lg energy", "lg에너지", "엘지에너지"]},
    "006400.KS": {"name": "Samsung SDI", "name_ko": "삼성SDI", "market": "kr", "sector": "Battery", "keywords": ["samsung sdi", "삼성sdi"]},
    "051910.KS": {"name": "LG Chem", "name_ko": "LG화학", "market": "kr", "sector": "Chemical/Battery", "keywords": ["lg chem", "lg화학", "엘지화학"]},
    "068270.KS": {"name": "Celltrion", "name_ko": "셀트리온", "market": "kr", "sector": "Bio", "keywords": ["celltrion", "셀트리온"]},
    "105560.KS": {"name": "KB Financial", "name_ko": "KB금융", "market": "kr", "sector": "Finance", "keywords": ["kb financial", "kb금융", "국민은행"]},
    "055550.KS": {"name": "Shinhan Financial", "name_ko": "신한지주", "market": "kr", "sector": "Finance", "keywords": ["shinhan", "신한"]},
    "003670.KS": {"name": "Posco Holdings", "name_ko": "포스코홀딩스", "market": "kr", "sector": "Steel/Materials", "keywords": ["posco", "포스코"]},
    "012330.KS": {"name": "Hyundai Mobis", "name_ko": "현대모비스", "market": "kr", "sector": "Auto Parts", "keywords": ["hyundai mobis", "현대모비스"]},
    "005380.KS": {"name": "Hyundai Motor", "name_ko": "현대자동차", "market": "kr", "sector": "Auto", "keywords": ["hyundai motor", "현대차", "현대자동차"]},

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
