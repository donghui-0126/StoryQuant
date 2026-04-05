"""
background.py - Parallel background data ingestion for StoryQuant.

Runs all data collection (news, prices, topics, attribution) in daemon threads
so the main process can start the dashboard while data flows in continuously.
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class BackgroundIngester:
    """
    Manages all background data collection threads.

    Thread schedule:
      - RSS news polling       every  5 min
      - Binance WebSocket      continuous (its own thread)
      - yfinance polling       every 15 min
      - Twitter/X polling      every 10 min
      - Exchange announcements every 10 min
      - Topic recomputation    every 30 min
    """

    def __init__(self, db_path: str = "data/storyquant.db"):
        from src.db.schema import get_connection, init_db

        self.db_path = db_path
        self.conn = get_connection(db_path)
        init_db(self.conn)
        self.running = False
        self.threads: list[threading.Thread] = []
        # Serialize all DB writes through a single lock
        self._db_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all background threads."""
        if self.running:
            logger.warning("BackgroundIngester is already running")
            return

        self.running = True
        logger.info("Starting BackgroundIngester…")

        schedule = [
            # (target_func, interval_seconds, thread_name)
            (self._ingest_news,                   5 * 60,  "news-poller"),
            (self._ingest_prices,                15 * 60,  "price-poller"),
            (self._ingest_twitter,               10 * 60,  "twitter-poller"),
            (self._ingest_exchange_announcements,10 * 60,  "exchange-poller"),
            (self._ingest_community,             10 * 60,  "community-poller"),
            (self._recompute_topics,             30 * 60,  "topic-recomputer"),
            (self._ingest_derivatives,            5 * 60,  "derivatives-poller"),
            (self._ingest_whale_data,            15 * 60,  "whale-poller"),
            (self._run_paper_trading,             5 * 60,  "paper-trader"),
            (self._dispatch_alerts,               60,       "alert-dispatcher"),
            (self._score_sentiments,              5 * 60,  "sentiment-scorer"),
            (self._ingest_playwright,            10 * 60,  "playwright-poller"),
            (self._detect_cross_signals,          5 * 60,  "cross-market-detector"),
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

        # Binance WebSocket runs in its own thread (no polling loop)
        ws_thread = threading.Thread(
            target=self._start_binance_ws,
            name="binance-ws",
            daemon=True,
        )
        self.threads.append(ws_thread)
        ws_thread.start()
        logger.info("Started thread: binance-ws (continuous)")

    def stop(self) -> None:
        """Signal all threads to stop and wait for them to exit."""
        logger.info("Stopping BackgroundIngester…")
        self.running = False
        for t in self.threads:
            t.join(timeout=10)
            if t.is_alive():
                logger.warning("Thread %s did not exit cleanly", t.name)
        self.threads.clear()
        logger.info("BackgroundIngester stopped")

    # ------------------------------------------------------------------
    # Generic polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self, func, interval_seconds: int, name: str) -> None:
        """Run *func* repeatedly, sleeping *interval_seconds* between calls.

        Sleeps in 1-second increments so the thread can react to stop()
        quickly without a long blocking sleep.
        """
        logger.info("[%s] Poll loop starting", name)
        while self.running:
            try:
                func()
            except Exception as exc:
                logger.error("[%s] Error: %s", name, exc, exc_info=True)
            # Interruptible sleep
            for _ in range(interval_seconds):
                if not self.running:
                    break
                time.sleep(1)
        logger.info("[%s] Poll loop exiting", name)

    # ------------------------------------------------------------------
    # Ingestion workers
    # ------------------------------------------------------------------

    def _ingest_news(self) -> None:
        """Crawl RSS feeds and save new articles to DB."""
        from src.crawlers.news_crawler import crawl_all_news
        from src.db.queries import insert_articles

        news_df = crawl_all_news(hours_back=1)
        if not news_df.empty:
            # Map crawler columns -> DB columns
            news_df = news_df.rename(columns={"timestamp": "published_at"})
            news_df["source_type"] = "rss"
            with self._db_lock:
                insert_articles(self.conn, news_df)
            logger.info("[news-poller] Ingested %d articles", len(news_df))
        else:
            logger.debug("[news-poller] No new articles")

    def _ingest_twitter(self) -> None:
        """Crawl Twitter/X and save tweets to DB."""
        try:
            from src.crawlers.twitter_crawler import crawl_twitter
            from src.db.queries import insert_articles

            tweets_df = crawl_twitter(hours_back=1)
            if not tweets_df.empty:
                tweets_df = tweets_df.rename(columns={"timestamp": "published_at"})
                tweets_df["source_type"] = "twitter"
                with self._db_lock:
                    insert_articles(self.conn, tweets_df)
                logger.info("[twitter-poller] Ingested %d tweets", len(tweets_df))
            else:
                logger.debug("[twitter-poller] No new tweets")
        except ImportError:
            logger.warning("[twitter-poller] Twitter crawler not available — skipping")

    def _ingest_exchange_announcements(self) -> None:
        """Fetch Binance announcements and save to DB."""
        try:
            from src.crawlers.exchange_crawler import fetch_binance_announcements
            from src.db.queries import insert_articles

            ann_df = fetch_binance_announcements(hours_back=24)
            if not ann_df.empty:
                ann_df = ann_df.rename(columns={"timestamp": "published_at"})
                with self._db_lock:
                    insert_articles(self.conn, ann_df)
                logger.info(
                    "[exchange-poller] Ingested %d announcements", len(ann_df)
                )
            else:
                logger.debug("[exchange-poller] No new announcements")
        except ImportError:
            logger.warning(
                "[exchange-poller] Exchange crawler not available — skipping"
            )

    def _ingest_community(self) -> None:
        """Crawl community/crypto news sources and save to DB."""
        try:
            from src.crawlers.community_crawler import crawl_all_community
            from src.db.queries import insert_articles

            community_df = crawl_all_community(hours_back=6)
            if not community_df.empty:
                community_df = community_df.rename(columns={"timestamp": "published_at"})
                with self._db_lock:
                    insert_articles(self.conn, community_df)
                logger.info(
                    "[community-poller] Ingested %d articles", len(community_df)
                )
            else:
                logger.debug("[community-poller] No new community articles")
        except ImportError:
            logger.warning(
                "[community-poller] Community crawler not available — skipping"
            )

    def _ingest_prices(self) -> None:
        """Fetch stock/crypto prices via yfinance, detect events, run attribution."""
        from src.prices.price_fetcher import fetch_prices, get_default_tickers
        from src.prices.event_detector import detect_events
        from src.db.queries import insert_prices, insert_events

        tickers_map = get_default_tickers()
        all_tickers = [t for ts in tickers_map.values() for t in ts]
        price_df = fetch_prices(all_tickers, period="1d", interval="1h")
        if price_df.empty:
            logger.debug("[price-poller] No price data returned")
            return

        with self._db_lock:
            insert_prices(self.conn, price_df)

        logger.info(
            "[price-poller] Saved %d price rows for %d tickers",
            len(price_df),
            price_df["ticker"].nunique(),
        )

        events_df = detect_events(price_df)
        if not events_df.empty:
            with self._db_lock:
                events_df = insert_events(self.conn, events_df)
            logger.info("[price-poller] Detected %d events", len(events_df))
            self._run_attribution(events_df)

    def _start_binance_ws(self) -> None:
        """Open a Binance WebSocket and stream kline data into the DB."""
        try:
            from src.prices.binance_ws import run_binance_ws
            from src.db.queries import insert_prices
            import pandas as pd

            def on_kline(data: dict) -> None:
                df = pd.DataFrame([data])
                with self._db_lock:
                    insert_prices(self.conn, df)

            logger.info("[binance-ws] Connecting…")
            run_binance_ws(on_kline)
        except ImportError:
            logger.warning("[binance-ws] Binance WebSocket module not available — skipping")
        except Exception as exc:
            logger.error("[binance-ws] Fatal error: %s", exc, exc_info=True)

    def _recompute_topics(self) -> None:
        """Recompute TF-IDF topics from the last 6 hours of articles."""
        from src.db.queries import get_recent_articles, insert_topics
        from src.topics.topic_extractor import extract_topics
        from datetime import datetime, timezone

        articles_df = get_recent_articles(self.conn, hours=6)
        if len(articles_df) < 3:
            logger.debug(
                "[topic-recomputer] Only %d articles — skipping (need ≥3)",
                len(articles_df),
            )
            return

        # Align column name for topic_extractor (expects 'timestamp')
        if "published_at" in articles_df.columns and "timestamp" not in articles_df.columns:
            articles_df = articles_df.rename(columns={"published_at": "timestamp"})

        topics_df = extract_topics(articles_df, n_topics=5)
        if topics_df.empty:
            return

        # Add window metadata expected by insert_topics
        now = datetime.now(timezone.utc)
        topics_df["window_end"] = now.isoformat()
        topics_df["window_start"] = (now.replace(hour=now.hour - 6) if now.hour >= 6 else now).isoformat()

        with self._db_lock:
            insert_topics(self.conn, topics_df)
        logger.info("[topic-recomputer] Saved %d topics", len(topics_df))

    def _ingest_derivatives(self) -> None:
        """Fetch OI and liquidation data from Binance Futures API."""
        from src.prices.derivatives import (
            fetch_oi_history,
            fetch_long_short_ratio,
            fetch_liquidations,
        )
        from src.db.queries import insert_open_interest, insert_liquidations

        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            try:
                oi_hist = fetch_oi_history(symbol)
                ls_ratio = fetch_long_short_ratio(symbol)
                if not oi_hist.empty and not ls_ratio.empty:
                    merged = oi_hist.merge(
                        ls_ratio[["timestamp", "long_short_ratio", "long_pct", "short_pct"]],
                        on="timestamp",
                        how="left",
                    )
                    with self._db_lock:
                        insert_open_interest(self.conn, merged)
                    logger.info("[derivatives-poller] Saved OI for %s (%d rows)", symbol, len(merged))
                elif not oi_hist.empty:
                    with self._db_lock:
                        insert_open_interest(self.conn, oi_hist)
                    logger.info("[derivatives-poller] Saved OI for %s (%d rows, no L/S)", symbol, len(oi_hist))
            except Exception as exc:
                logger.error("[derivatives-poller] OI fetch failed for %s: %s", symbol, exc)

        try:
            liqs = fetch_liquidations()
            if not liqs.empty:
                with self._db_lock:
                    insert_liquidations(self.conn, liqs)
                logger.info("[derivatives-poller] Saved %d liquidation rows", len(liqs))
        except Exception as exc:
            logger.error("[derivatives-poller] Liquidations fetch failed: %s", exc)

    def _ingest_whale_data(self) -> None:
        """Fetch whale transfers and save to DB."""
        try:
            from src.prices.whale_tracker import fetch_whale_movements, arkham_available, whale_alert_available
            from src.db.queries import insert_whale_transfers

            if not arkham_available() and not whale_alert_available():
                return  # No API keys configured, skip silently

            df = fetch_whale_movements(min_usd=1_000_000, hours_back=1)
            if not df.empty:
                df["source"] = "arkham" if arkham_available() else "whale_alert"
                with self._db_lock:
                    insert_whale_transfers(self.conn, df)
                logger.info("[whale-poller] Ingested %d whale transfers", len(df))
        except ImportError:
            logger.warning("[whale-poller] Whale tracker not available")

    def _run_paper_trading(self) -> None:
        """Run paper trading cycle."""
        try:
            from src.analysis.paper_trader import run_paper_trading_cycle
            with self._db_lock:
                run_paper_trading_cycle(self.conn)
        except ImportError:
            logger.warning("[paper-trader] Paper trader not available")

    def _dispatch_alerts(self) -> None:
        """Check for new events and send alerts."""
        try:
            from src.alerts.dispatcher import dispatch_alerts
            with self._db_lock:
                dispatch_alerts(self.conn)
        except ImportError:
            pass  # Silently skip if not available

    def _score_sentiments(self) -> None:
        """Score sentiment for new articles."""
        try:
            from src.analysis.sentiment import update_article_sentiments
            with self._db_lock:
                count = update_article_sentiments(self.conn, use_llm=False)  # Rule-based by default
                if count:
                    logger.info("[sentiment] Scored %d articles", count)
        except ImportError:
            pass

    def _ingest_playwright(self) -> None:
        """Crawl JS-rendered sites (Coinness, CoinMarketCap) via Playwright."""
        try:
            from src.crawlers.playwright_crawler import crawl_all_playwright
            from src.db.queries import insert_articles

            df = crawl_all_playwright(hours_back=1)
            if not df.empty:
                df = df.rename(columns={"timestamp": "published_at"})
                with self._db_lock:
                    insert_articles(self.conn, df)
                logger.info("[playwright-poller] Ingested %d articles", len(df))
            else:
                logger.debug("[playwright-poller] No new articles")
        except ImportError:
            logger.warning("[playwright-poller] Playwright crawler not available — skipping")
        except Exception as exc:
            logger.error("[playwright-poller] Error: %s", exc)

    def _detect_cross_signals(self) -> None:
        """Detect cross-market signals and log notable findings."""
        try:
            from src.analysis.cross_market import detect_cross_market_signals
            with self._db_lock:
                signals = detect_cross_market_signals(self.conn, hours=48)
            if not signals.empty:
                logger.info(
                    "[cross-market-detector] %d cross-market signals detected",
                    len(signals),
                )
                # Log the top 3 most significant signals
                for _, row in signals.head(3).iterrows():
                    logger.info(
                        "[cross-market-detector] %s (%s) -> %s (%s) | lag=%.0fh | src_ret=%.2f%% tgt_ret=%.2f%%",
                        row["source_ticker"], row["source_event"],
                        row["target_ticker"], row["target_event"],
                        row["lag_hours"],
                        row["source_return"] * 100,
                        row["target_return"] * 100,
                    )
            else:
                logger.debug("[cross-market-detector] No significant cross-market signals")
        except ImportError:
            logger.warning("[cross-market-detector] cross_market module not available — skipping")
        except Exception as exc:
            logger.error("[cross-market-detector] Error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Attribution helper
    # ------------------------------------------------------------------

    def _run_attribution(self, events_df) -> None:
        """Run attribution for freshly detected events and persist results."""
        from src.db.queries import get_recent_articles, insert_attributions
        from src.attribution.mapper import attribute_all_events

        articles_df = get_recent_articles(self.conn, hours=6)
        if articles_df.empty or events_df.empty:
            return

        # Align column names
        if "published_at" in articles_df.columns and "timestamp" not in articles_df.columns:
            articles_df = articles_df.rename(columns={"published_at": "timestamp"})

        attr_df = attribute_all_events(events_df, articles_df)
        if not attr_df.empty:
            with self._db_lock:
                insert_attributions(self.conn, attr_df)
            logger.info("[attribution] Saved %d attribution rows", len(attr_df))


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ingester = BackgroundIngester(db_path="data/storyquant.db")
    ingester.start()
    print("BackgroundIngester running. Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping…")
        ingester.stop()
        print("Done.")
        sys.exit(0)
