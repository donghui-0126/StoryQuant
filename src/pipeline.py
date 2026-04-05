"""
StoryQuant Pipeline Orchestrator
뉴스 크롤링 → 토픽 추출 → 가격 이벤트 감지 → 뉴스-이벤트 매핑 전체 파이프라인
"""

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawlers.news_crawler import crawl_all_news, save_news_csv
from src.prices.price_fetcher import fetch_prices, get_default_tickers, save_prices_csv
from src.prices.event_detector import detect_events, save_events_csv
from src.topics.topic_extractor import extract_topics, assign_topics_to_articles, save_topics_csv
from src.attribution.mapper import attribute_all_events, generate_attribution_summary, save_attribution_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_pipeline(hours_back: int = 6, return_threshold: float = 0.02, n_topics: int = 5) -> dict:
    """전체 파이프라인 실행. 각 단계 결과를 CSV로 저장하고 dict로 반환."""

    results = {}

    # Step 1: 뉴스 크롤링
    logger.info("Step 1/5: 뉴스 크롤링 시작")
    news_df = crawl_all_news(hours_back=hours_back)
    if news_df.empty:
        logger.warning("크롤링된 뉴스가 없습니다. 샘플 데이터로 진행합니다.")
        news_df = _generate_sample_news()
    save_news_csv(news_df)
    results["news"] = news_df
    logger.info(f"  → {len(news_df)}개 뉴스 수집 완료")

    # Step 2: 가격 데이터 수집
    logger.info("Step 2/5: 가격 데이터 수집")
    tickers = get_default_tickers()
    all_tickers = [t for ts in tickers.values() for t in ts]
    price_df = fetch_prices(all_tickers)
    if price_df.empty:
        logger.warning("가격 데이터를 가져올 수 없습니다. 샘플 데이터로 진행합니다.")
        price_df = _generate_sample_prices(all_tickers)
    save_prices_csv(price_df)
    results["prices"] = price_df
    logger.info(f"  → {price_df['ticker'].nunique()}개 자산, {len(price_df)}개 레코드")

    # Step 3: 토픽 추출
    logger.info("Step 3/5: Hot Topic 추출")
    topics_df = extract_topics(news_df, n_topics=n_topics)
    news_with_topics = assign_topics_to_articles(news_df, n_topics=n_topics)
    save_topics_csv(topics_df)
    results["topics"] = topics_df
    results["news_with_topics"] = news_with_topics
    logger.info(f"  → {len(topics_df)}개 토픽 추출 완료")

    # Step 4: 가격 이벤트 감지
    logger.info("Step 4/5: 가격 이벤트 감지")
    events_df = detect_events(price_df, return_threshold=return_threshold)
    if events_df.empty:
        logger.info("  → 감지된 이벤트 없음 (threshold 내)")
    else:
        save_events_csv(events_df)
        logger.info(f"  → {len(events_df)}개 이벤트 감지")
    results["events"] = events_df

    # Step 5: 뉴스-이벤트 매핑
    logger.info("Step 5/5: 뉴스-이벤트 Attribution")
    if not events_df.empty and not news_with_topics.empty:
        attribution_df = attribute_all_events(events_df, news_with_topics)
        summary_df = generate_attribution_summary(attribution_df)
        save_attribution_csv(attribution_df)
        results["attribution"] = attribution_df
        results["summary"] = summary_df
        logger.info(f"  → {len(attribution_df)}개 매핑 완료")
    else:
        results["attribution"] = pd.DataFrame()
        results["summary"] = pd.DataFrame()
        logger.info("  → 매핑할 이벤트/뉴스 없음")

    logger.info("파이프라인 완료!")
    return results


def _generate_sample_news() -> pd.DataFrame:
    """RSS 피드 실패 시 사용할 샘플 뉴스 데이터"""
    from datetime import datetime, timedelta
    import numpy as np

    now = datetime.utcnow()
    samples = [
        {"title": "Bitcoin ETF sees record inflows as institutional demand surges", "market": "crypto", "source": "CoinDesk"},
        {"title": "Ethereum upgrades push network efficiency to new highs", "market": "crypto", "source": "CoinTelegraph"},
        {"title": "Fed signals potential rate cut amid cooling inflation data", "market": "us", "source": "Reuters"},
        {"title": "NVIDIA beats earnings expectations on AI chip demand", "market": "us", "source": "CNBC"},
        {"title": "Tesla announces new gigafactory expansion in Asia", "market": "us", "source": "CNBC"},
        {"title": "Apple Vision Pro sales exceed analyst expectations", "market": "us", "source": "Reuters"},
        {"title": "삼성전자 HBM3E 양산 본격화, AI 반도체 수요 대응", "market": "kr", "source": "네이버금융"},
        {"title": "SK하이닉스 1분기 실적 서프라이즈, HBM 매출 급증", "market": "kr", "source": "매일경제"},
        {"title": "네이버 AI 검색 서비스 출시, 하이퍼클로바X 탑재", "market": "kr", "source": "네이버금융"},
        {"title": "Bitcoin short squeeze triggers rapid price surge above 70K", "market": "crypto", "source": "CoinDesk"},
        {"title": "S&P 500 hits all-time high on strong jobs data", "market": "us", "source": "Reuters"},
        {"title": "Solana DeFi TVL reaches new record amid memecoin frenzy", "market": "crypto", "source": "CoinTelegraph"},
        {"title": "코스피 외국인 매수세 지속, 반도체주 강세", "market": "kr", "source": "매일경제"},
        {"title": "Fed Chair Powell testimony hints at data-dependent approach", "market": "us", "source": "CNBC"},
        {"title": "Crypto market cap surpasses 3 trillion amid Bitcoin rally", "market": "crypto", "source": "CoinDesk"},
    ]

    rows = []
    for i, s in enumerate(samples):
        rows.append({
            "timestamp": (now - timedelta(minutes=np.random.randint(10, 350))).isoformat(),
            "title": s["title"],
            "source": s["source"],
            "market": s["market"],
            "url": f"https://example.com/news/{i}",
            "summary": s["title"],
        })
    return pd.DataFrame(rows)


def _generate_sample_prices(tickers: list) -> pd.DataFrame:
    """yfinance 실패 시 사용할 샘플 가격 데이터"""
    from datetime import datetime, timedelta
    import numpy as np

    now = datetime.utcnow()
    rows = []
    base_prices = {
        "BTC-USD": 70000, "ETH-USD": 3500, "SOL-USD": 150,
        "NVDA": 900, "AAPL": 180, "TSLA": 250, "SPY": 520,
        "005930.KS": 75000, "000660.KS": 180000, "035420.KS": 220000,
    }

    for ticker in tickers:
        base = base_prices.get(ticker, 100)
        for h in range(72):
            ts = now - timedelta(hours=72 - h)
            noise = np.random.normal(0, 0.01)
            price = base * (1 + noise)
            rows.append({
                "ticker": ticker,
                "timestamp": ts.isoformat(),
                "open": round(price * 0.999, 2),
                "high": round(price * 1.005, 2),
                "low": round(price * 0.995, 2),
                "close": round(price, 2),
                "volume": int(np.random.uniform(1e6, 1e8)),
            })
            base = price
    return pd.DataFrame(rows)


if __name__ == "__main__":
    results = run_pipeline()
    print("\n=== Pipeline Results ===")
    for key, df in results.items():
        if isinstance(df, pd.DataFrame):
            print(f"{key}: {len(df)} rows")
