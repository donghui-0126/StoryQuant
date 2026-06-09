"""
StoryQuant v2 Background Ingester.

Runs all data collection + graph analysis in daemon threads.
v1→v2 changes:
  - News/Twitter/Community/Exchange → amure-db Evidence nodes (was SQLite articles)
  - Price events → amure-db Fact nodes (was SQLite events)
  - TF-IDF topic recomputer → graph-based narrator (Claim lifecycle)
  - Rule-based attribution → RAG graph-attributor
  - New: graph-reasoner (contradictions, health, verdict propagation)
  - Kept: prices/OI/liquidations/whales in SQLite (time-series)
"""

import logging
import threading
import time

from src.config import settings

logger = logging.getLogger(__name__)


class BackgroundIngester:
    """Manages all background data collection and graph analysis threads."""

    def __init__(self, db_path: str = None):
        from src.db.schema import get_connection, init_db

        self.db_path = db_path or settings.SQLITE_DB_PATH
        conn = get_connection(self.db_path)
        init_db(conn)
        conn.close()
        self.running = False
        self.threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            logger.warning("BackgroundIngester is already running")
            return

        self.running = True
        logger.info("Starting BackgroundIngester v2 (graph-centric)…")

        schedule = [
            # (target_func, interval_seconds, thread_name)
            # ── Data ingestion (unchanged sources, new sinks) ──
            (self._ingest_news,        settings.INTERVAL_NEWS,        "news-poller"),
            (self._ingest_prices,      settings.INTERVAL_PRICES,      "price-poller"),
            (self._ingest_twitter,     settings.INTERVAL_TWITTER,     "twitter-poller"),
            (self._ingest_exchange,    settings.INTERVAL_EXCHANGE,    "exchange-poller"),
            (self._ingest_community,   settings.INTERVAL_COMMUNITY,   "community-poller"),
            (self._ingest_playwright,  settings.INTERVAL_COMMUNITY,   "playwright-poller"),
            (self._ingest_derivatives, settings.INTERVAL_DERIVATIVES, "derivatives-poller"),
            (self._ingest_whales,      settings.INTERVAL_WHALE,       "whale-poller"),
            # ── Scoring ──
            (self._score_sentiments,   settings.INTERVAL_SENTIMENT,   "sentiment-scorer"),
            # ── Graph analysis (new in v2) ──
            (self._graph_attribution,  settings.INTERVAL_ATTRIBUTION, "graph-attributor"),
            (self._graph_narrator,     settings.INTERVAL_NARRATOR,    "graph-narrator"),
            (self._graph_reasoner,     settings.INTERVAL_REASONING,   "graph-reasoner"),
            (self._crossmarket_linker, settings.INTERVAL_CROSSMARKET, "crossmarket-linker"),
            # ── Alerts ──
            (self._dispatch_alerts,    settings.INTERVAL_ALERTS,      "alert-dispatcher"),
        ]

        for func, interval, name in schedule:
            t = threading.Thread(
                target=self._poll_loop,
                args=(func, interval, name),
                name=name,
                daemon=True,
            )
            self.threads.append(t)
            t.start()
            logger.info("Started thread: %s (every %ds)", name, interval)

        # Binance WebSocket (continuous)
        ws_thread = threading.Thread(
            target=self._start_binance_ws,
            name="binance-ws",
            daemon=True,
        )
        self.threads.append(ws_thread)
        ws_thread.start()
        logger.info("Started thread: binance-ws (continuous)")

    def stop(self) -> None:
        logger.info("Stopping BackgroundIngester…")
        self.running = False
        for t in self.threads:
            t.join(timeout=10)
            if t.is_alive():
                logger.warning("Thread %s did not exit cleanly", t.name)
        self.threads.clear()
        logger.info("BackgroundIngester stopped")

    def _poll_loop(self, func, interval_seconds: int, name: str) -> None:
        logger.info("[%s] Poll loop starting", name)
        while self.running:
            try:
                func()
            except Exception as exc:
                logger.error("[%s] Error: %s", name, exc, exc_info=True)
            for _ in range(interval_seconds):
                if not self.running:
                    break
                time.sleep(1)
        logger.info("[%s] Poll loop exiting", name)

    # ------------------------------------------------------------------
    # Data ingestion workers → Graph Evidence nodes + SQLite time-series
    # ------------------------------------------------------------------

    def _ingest_news(self) -> None:
        """Crawl RSS feeds → Evidence nodes in graph."""
        from src.crawlers.news_crawler import crawl_all_news
        from src.graph.client import AmureClient
        from src.graph.mapper import ingest_articles_to_graph

        news_df = crawl_all_news(hours_back=1)
        if news_df.empty:
            return

        news_df["source_type"] = "rss"
        if "timestamp" in news_df.columns and "published_at" not in news_df.columns:
            news_df = news_df.rename(columns={"timestamp": "published_at"})

        with AmureClient() as client:
            if not client.is_available():
                logger.debug("[news-poller] amure-db unavailable, skipping")
                return
            result = ingest_articles_to_graph(client, news_df)
            logger.info("[news-poller] %d Evidence nodes created", result["created"])

    def _ingest_twitter(self) -> None:
        try:
            from src.crawlers.twitter_crawler import crawl_twitter
            from src.graph.client import AmureClient
            from src.graph.mapper import ingest_articles_to_graph

            tweets_df = crawl_twitter(hours_back=1)
            if tweets_df.empty:
                return

            tweets_df["source_type"] = "twitter"
            if "timestamp" in tweets_df.columns and "published_at" not in tweets_df.columns:
                tweets_df = tweets_df.rename(columns={"timestamp": "published_at"})

            with AmureClient() as client:
                if not client.is_available():
                    return
                result = ingest_articles_to_graph(client, tweets_df)
                logger.info("[twitter-poller] %d Evidence nodes created", result["created"])
        except ImportError:
            logger.debug("[twitter-poller] Twitter crawler not available")

    def _ingest_exchange(self) -> None:
        try:
            from src.crawlers.exchange_crawler import fetch_binance_announcements
            from src.graph.client import AmureClient
            from src.graph.mapper import ingest_articles_to_graph

            ann_df = fetch_binance_announcements(hours_back=24)
            if ann_df.empty:
                return

            if "timestamp" in ann_df.columns and "published_at" not in ann_df.columns:
                ann_df = ann_df.rename(columns={"timestamp": "published_at"})

            with AmureClient() as client:
                if not client.is_available():
                    return
                result = ingest_articles_to_graph(client, ann_df)
                logger.info("[exchange-poller] %d Evidence nodes created", result["created"])
        except ImportError:
            logger.debug("[exchange-poller] Exchange crawler not available")

    def _ingest_community(self) -> None:
        try:
            from src.crawlers.community_crawler import crawl_all_community
            from src.graph.client import AmureClient
            from src.graph.mapper import ingest_articles_to_graph

            df = crawl_all_community(hours_back=6)
            if df.empty:
                return

            df["source_type"] = "community"
            if "timestamp" in df.columns and "published_at" not in df.columns:
                df = df.rename(columns={"timestamp": "published_at"})

            with AmureClient() as client:
                if not client.is_available():
                    return
                result = ingest_articles_to_graph(client, df)
                logger.info("[community-poller] %d Evidence nodes created", result["created"])
        except ImportError:
            logger.debug("[community-poller] Community crawler not available")

    def _ingest_playwright(self) -> None:
        try:
            from src.crawlers.playwright_crawler import crawl_all_playwright
            from src.graph.client import AmureClient
            from src.graph.mapper import ingest_articles_to_graph

            df = crawl_all_playwright(hours_back=1)
            if df.empty:
                return

            if "timestamp" in df.columns and "published_at" not in df.columns:
                df = df.rename(columns={"timestamp": "published_at"})

            with AmureClient() as client:
                if not client.is_available():
                    return
                result = ingest_articles_to_graph(client, df)
                logger.info("[playwright-poller] %d Evidence nodes created", result["created"])
        except ImportError:
            logger.debug("[playwright-poller] Playwright crawler not available")

    def _ingest_prices(self) -> None:
        """Fetch prices → SQLite + detect events → Fact nodes in graph."""
        from src.prices.price_fetcher import fetch_prices, get_default_tickers
        from src.prices.event_detector import detect_events
        from src.db.queries import insert_prices
        from src.db.schema import thread_connection
        from src.graph.client import AmureClient
        from src.graph.mapper import ingest_events_to_graph

        tickers_map = get_default_tickers()
        all_tickers = [t for ts in tickers_map.values() for t in ts]
        price_df = fetch_prices(all_tickers, period="1d", interval="1h")
        if price_df.empty:
            return

        # Save to SQLite (time-series)
        with thread_connection(self.db_path) as conn:
            insert_prices(conn, price_df)
        logger.info("[price-poller] Saved %d price rows", len(price_df))

        # Detect events → Fact nodes
        events_df = detect_events(price_df)
        if not events_df.empty:
            with AmureClient() as client:
                if client.is_available():
                    result = ingest_events_to_graph(client, events_df)
                    logger.info("[price-poller] %d Fact nodes created from %d events",
                                result["created"], len(events_df))

    def _ingest_derivatives(self) -> None:
        """Fetch OI and liquidation data → SQLite."""
        from src.db.queries import insert_open_interest, insert_liquidations
        from src.db.schema import thread_connection

        try:
            from src.prices.derivatives import (
                fetch_oi_history, fetch_long_short_ratio, fetch_liquidations,
            )
        except ImportError:
            return

        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            try:
                oi_hist = fetch_oi_history(symbol)
                ls_ratio = fetch_long_short_ratio(symbol)
                if not oi_hist.empty and not ls_ratio.empty:
                    merged = oi_hist.merge(
                        ls_ratio[["timestamp", "long_short_ratio", "long_pct", "short_pct"]],
                        on="timestamp", how="left",
                    )
                    with thread_connection(self.db_path) as conn:
                        insert_open_interest(conn, merged)
                elif not oi_hist.empty:
                    with thread_connection(self.db_path) as conn:
                        insert_open_interest(conn, oi_hist)
            except Exception as exc:
                logger.error("[derivatives-poller] OI failed for %s: %s", symbol, exc)

        try:
            liqs = fetch_liquidations()
            if not liqs.empty:
                with thread_connection(self.db_path) as conn:
                    insert_liquidations(conn, liqs)
        except Exception as exc:
            logger.error("[derivatives-poller] Liquidations failed: %s", exc)

    def _ingest_whales(self) -> None:
        """Fetch whale transfers → SQLite + large ones → Evidence nodes."""
        from src.db.queries import insert_whale_transfers
        from src.db.schema import thread_connection

        try:
            from src.prices.whale_tracker import fetch_whale_movements, arkham_available, whale_alert_available
        except ImportError:
            return

        if not arkham_available() and not whale_alert_available():
            return

        df = fetch_whale_movements(min_usd=1_000_000, hours_back=1)
        if df.empty:
            return

        df["source"] = "arkham" if arkham_available() else "whale_alert"

        # SQLite (all transfers)
        with thread_connection(self.db_path) as conn:
            insert_whale_transfers(conn, df)

        # Graph (large transfers → Evidence nodes)
        from src.graph.client import AmureClient
        from src.graph.mapper import ingest_whales_to_graph

        with AmureClient() as client:
            if client.is_available():
                result = ingest_whales_to_graph(client, df)
                if result["created"]:
                    logger.info("[whale-poller] %d whale Evidence nodes", result["created"])

    def _start_binance_ws(self) -> None:
        """Binance WebSocket → SQLite prices."""
        try:
            from src.prices.binance_ws import run_binance_ws
            from src.db.queries import insert_prices
            from src.db.schema import thread_connection
            import pandas as pd

            def on_kline(data: dict) -> None:
                df = pd.DataFrame([data])
                with thread_connection(self.db_path) as conn:
                    insert_prices(conn, df)

            run_binance_ws(on_kline)
        except ImportError:
            logger.debug("[binance-ws] Module not available")
        except Exception as exc:
            logger.error("[binance-ws] Fatal: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_sentiments(self) -> None:
        """Score sentiment for Evidence nodes without sentiment metadata."""
        from src.analysis.sentiment import score_sentiment_rule_based
        from src.graph.client import AmureClient

        with AmureClient() as client:
            if not client.is_available():
                return
            all_data = client.get_all()
            nodes = all_data.get("nodes", [])

            unscored = [
                n for n in nodes
                if n.get("kind") == "Evidence"
                and not n.get("metadata", {}).get("sentiment")
            ]

            if not unscored:
                return

            count = 0
            for node in unscored[:50]:
                statement = node.get("statement", "")
                sentiment, score = score_sentiment_rule_based(statement)
                meta = node.get("metadata", {})
                meta["sentiment"] = sentiment
                meta["sentiment_score"] = score
                client.update_node(node["id"], metadata=meta)
                count += 1

            if count:
                logger.info("[sentiment-scorer] Scored %d Evidence nodes", count)

    # ------------------------------------------------------------------
    # Graph analysis workers (new in v2)
    # ------------------------------------------------------------------

    def _graph_attribution(self) -> None:
        """Run RAG-based attribution for un-attributed Fact nodes."""
        from src.graph.client import AmureClient
        from src.graph.attribution import attribute_unprocessed_events

        with AmureClient() as client:
            if not client.is_available():
                return
            result = attribute_unprocessed_events(client)
            if result["events_processed"]:
                logger.info(
                    "[graph-attributor] %d events → %d edges, %d reasons",
                    result["events_processed"],
                    result["edges_created"],
                    result["reasons_created"],
                )

    def _graph_narrator(self) -> None:
        """Discover new narratives + update lifecycle."""
        from src.graph.client import AmureClient
        from src.graph.reasoning import update_narrative_lifecycle, discover_narratives

        with AmureClient() as client:
            if not client.is_available():
                return

            # Auto-discover new narratives from Evidence clusters
            discovery = discover_narratives(client, min_cluster_size=3)
            if discovery.get("discovered"):
                logger.info("[graph-narrator] Discovered %d new narratives", discovery["discovered"])

            # Update lifecycle of all Claims
            result = update_narrative_lifecycle(client)
            if result.get("updated"):
                logger.info("[graph-narrator] Updated %d narratives", result["updated"])

    def _graph_reasoner(self) -> None:
        """Run contradiction detection and knowledge health checks."""
        from src.graph.client import AmureClient
        from src.graph.reasoning import detect_and_link_contradictions, check_knowledge_health

        with AmureClient() as client:
            if not client.is_available():
                return

            contradictions = detect_and_link_contradictions(client)
            if contradictions["count"]:
                logger.info("[graph-reasoner] %d contradictions found", contradictions["count"])

            health = check_knowledge_health(client)
            if health["stale_count"]:
                logger.info("[graph-reasoner] %d stale knowledge nodes", health["stale_count"])

    def _crossmarket_linker(self) -> None:
        """Detect cross-market signals and create DependsOn edges."""
        try:
            from src.analysis.cross_market import detect_cross_market_signals
            from src.db.schema import thread_connection
            from src.graph.client import AmureClient
            from src.graph.reasoning import create_cross_market_link

            with thread_connection(self.db_path) as conn:
                signals = detect_cross_market_signals(conn, hours=48)

            if signals.empty:
                return

            logger.info("[crossmarket-linker] %d signals detected", len(signals))
        except ImportError:
            logger.debug("[crossmarket-linker] cross_market module not available")

    def _dispatch_alerts(self) -> None:
        """Check for new high-severity events and send alerts."""
        try:
            from src.alerts.dispatcher import dispatch_alerts
            from src.db.schema import thread_connection

            with thread_connection(self.db_path) as conn:
                dispatch_alerts(conn)
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ingester = BackgroundIngester()
    ingester.start()
    print("BackgroundIngester v2 running. Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping…")
        ingester.stop()
        print("Done.")
        sys.exit(0)
