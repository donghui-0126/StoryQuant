"""
StoryQuant v2 Pipeline Orchestrator
뉴스 크롤링 → 그래프 적재 → 가격 이벤트 감지 → RAG 기반 귀인 → 내러티브 생성

v1과의 차이:
  - TF-IDF 토픽 추출 제거 → amure-db 그래프 Claim 노드로 대체
  - Rule-based 4팩터 귀인 제거 → RAG 검색 + Support 엣지로 대체
  - SQLite articles/events/attributions/topics 테이블 제거 → 그래프로 이동
"""

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawlers.news_crawler import crawl_all_news
from src.prices.price_fetcher import fetch_prices, get_default_tickers
from src.prices.event_detector import detect_events
from src.graph.client import AmureClient
from src.graph.mapper import ingest_articles_to_graph, ingest_events_to_graph
from src.graph.attribution import attribute_unprocessed_events
from src.graph.reasoning import update_narrative_lifecycle, get_active_narratives
from src.db.schema import get_connection, init_db
from src.db.queries import insert_prices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_pipeline(hours_back: int = 6) -> dict:
    """
    전체 파이프라인 실행 (1-shot).

    Phase 1: INGEST — 뉴스 크롤링 + 가격 수집
    Phase 2: GRAPH  — 뉴스→Evidence, 이벤트→Fact 노드 생성
    Phase 3: CONNECT — RAG 기반 귀인 (Evidence→Fact Support 엣지)
    Phase 4: REASON — 내러티브 lifecycle 업데이트
    """
    results = {}

    # ── Init ──
    conn = get_connection()
    init_db(conn)
    client = AmureClient()

    if not client.is_available():
        logger.error("amure-db가 응답하지 않습니다. 'cargo run' 으로 서버를 먼저 시작하세요.")
        logger.info("amure-db 없이 데이터 수집만 진행합니다.")
        return _run_ingest_only(conn, hours_back)

    logger.info("amure-db 연결 확인 ✓")

    # ── Phase 1: INGEST ──
    logger.info("Phase 1/4: 데이터 수집")

    # 뉴스 크롤링
    news_df = crawl_all_news(hours_back=hours_back)
    if news_df.empty:
        logger.warning("크롤링된 뉴스 없음 — 샘플 데이터로 진행")
        news_df = _generate_sample_news()
    results["news_count"] = len(news_df)
    logger.info("  뉴스 %d건 수집", len(news_df))

    # 가격 데이터
    tickers = get_default_tickers()
    all_tickers = [t for ts in tickers.values() for t in ts]
    price_df = fetch_prices(all_tickers)
    if price_df.empty:
        logger.warning("가격 데이터 없음 — 샘플 데이터로 진행")
        price_df = _generate_sample_prices(all_tickers)

    insert_prices(conn, price_df)
    results["price_tickers"] = price_df["ticker"].nunique() if not price_df.empty else 0
    logger.info("  가격 %d 자산, %d 레코드", results["price_tickers"], len(price_df))

    # ── Phase 2: GRAPH — 노드 생성 ──
    logger.info("Phase 2/4: 그래프 노드 생성")

    # 뉴스 → Evidence 노드
    news_result = ingest_articles_to_graph(client, news_df)
    results["evidence_created"] = news_result["created"]
    logger.info("  Evidence 노드 %d개 생성", news_result["created"])

    # 이벤트 감지 + Fact 노드
    events_df = detect_events(price_df)
    if not events_df.empty:
        event_result = ingest_events_to_graph(client, events_df)
        results["fact_created"] = event_result["created"]
        logger.info("  Fact 노드 %d개 생성 (%d개 이벤트)", event_result["created"], len(events_df))
    else:
        results["fact_created"] = 0
        logger.info("  감지된 이벤트 없음")

    # ── Phase 3: CONNECT — RAG 귀인 ──
    logger.info("Phase 3/4: RAG 기반 귀인")
    attr_result = attribute_unprocessed_events(client)
    results["attribution_edges"] = attr_result["edges_created"]
    results["reasons_created"] = attr_result["reasons_created"]
    logger.info(
        "  %d개 이벤트 처리, %d개 Support 엣지, %d개 Reason 생성",
        attr_result["events_processed"],
        attr_result["edges_created"],
        attr_result["reasons_created"],
    )

    # ── Phase 4: REASON — 내러티브 ──
    logger.info("Phase 4/4: 내러티브 분석")
    lifecycle_result = update_narrative_lifecycle(client)
    narratives = get_active_narratives(client)
    results["narratives"] = len(narratives)
    logger.info("  %d개 내러티브 활성", len(narratives))

    # 그래프 저장
    client.save()

    # 요약
    summary = client.graph_summary()
    logger.info("=" * 50)
    logger.info("파이프라인 완료!")
    logger.info("  그래프 요약: %s", summary)
    logger.info("=" * 50)

    conn.close()
    client.close()
    results["graph_summary"] = summary
    return results


def _run_ingest_only(conn, hours_back: int) -> dict:
    """amure-db 없이 데이터 수집만 진행 (graceful degradation)."""
    results = {}

    news_df = crawl_all_news(hours_back=hours_back)
    results["news_count"] = len(news_df)
    logger.info("뉴스 %d건 수집 (그래프 미연결)", len(news_df))

    tickers = get_default_tickers()
    all_tickers = [t for ts in tickers.values() for t in ts]
    price_df = fetch_prices(all_tickers)
    if not price_df.empty:
        insert_prices(conn, price_df)
    results["price_rows"] = len(price_df)

    events_df = detect_events(price_df)
    results["events_detected"] = len(events_df)
    logger.info("이벤트 %d개 감지 (귀인 없음 — amure-db 필요)", len(events_df))

    conn.close()
    return results


# ── Sample data generators (fallback) ──

def _generate_sample_news() -> pd.DataFrame:
    from datetime import datetime, timedelta
    import numpy as np

    now = datetime.utcnow()
    samples = [
        {"title": "Bitcoin ETF sees record inflows as institutional demand surges", "market": "crypto", "source": "CoinDesk"},
        {"title": "Ethereum upgrades push network efficiency to new highs", "market": "crypto", "source": "CoinTelegraph"},
        {"title": "Fed signals potential rate cut amid cooling inflation data", "market": "us", "source": "Reuters"},
        {"title": "NVIDIA beats earnings expectations on AI chip demand", "market": "us", "source": "CNBC"},
        {"title": "Tesla announces new gigafactory expansion in Asia", "market": "us", "source": "CNBC"},
        {"title": "삼성전자 HBM3E 양산 본격화, AI 반도체 수요 대응", "market": "kr", "source": "네이버금융"},
        {"title": "SK하이닉스 1분기 실적 서프라이즈, HBM 매출 급증", "market": "kr", "source": "매일경제"},
        {"title": "Bitcoin short squeeze triggers rapid price surge above 70K", "market": "crypto", "source": "CoinDesk"},
        {"title": "S&P 500 hits all-time high on strong jobs data", "market": "us", "source": "Reuters"},
        {"title": "Solana DeFi TVL reaches new record amid memecoin frenzy", "market": "crypto", "source": "CoinTelegraph"},
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
    for key, val in results.items():
        print(f"  {key}: {val}")
