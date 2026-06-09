"""
news_crawler.py - RSS-based news crawler for StoryQuant PoC.

Crawls crypto, US stocks, and Korean stocks news from RSS feeds.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feed definitions
# ---------------------------------------------------------------------------

FEEDS = [
    # --- Crypto ---
    {
        "source": "CoinDesk",
        "market": "crypto",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
    {
        "source": "CoinTelegraph",
        "market": "crypto",
        "url": "https://cointelegraph.com/rss",
    },
    # --- US Stocks ---
    {
        "source": "CNBC",
        "market": "us",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
    # Reuters legacy feed died → swap in fresher US-market RSS sources
    {
        "source": "MarketWatch Top",
        "market": "us",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    },
    {
        "source": "Bloomberg Markets",
        "market": "us",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
    },
    {
        "source": "SeekingAlpha Market",
        "market": "us",
        "url": "https://seekingalpha.com/market_currents.xml",
    },
    {
        "source": "Yahoo Finance",
        "market": "us",
        "url": "https://finance.yahoo.com/news/rssindex",
    },
    # --- Korean Domestic Stocks (KOSPI/KOSDAQ) ---
    # 한국경제 - 전체/증권/경제
    {
        "source": "한국경제",
        "market": "kr",
        "url": "https://www.hankyung.com/feed/all-news",
    },
    {
        "source": "한국경제 증권",
        "market": "kr",
        "url": "https://www.hankyung.com/feed/finance",
    },
    {
        "source": "한국경제 경제",
        "market": "kr",
        "url": "https://www.hankyung.com/feed/economy",
    },
    # 매일경제 - 증권/경제/기업/증시
    {
        "source": "매일경제 증권",
        "market": "kr",
        "url": "https://www.mk.co.kr/rss/50200011/",
    },
    {
        "source": "매일경제 경제",
        "market": "kr",
        "url": "https://www.mk.co.kr/rss/30100041/",
    },
    {
        "source": "매일경제 기업",
        "market": "kr",
        "url": "https://www.mk.co.kr/rss/50100032/",
    },
    {
        "source": "매일경제 증시",
        "market": "kr",
        "url": "https://www.mk.co.kr/rss/50300009/",
    },
    # 이데일리 - SSL 깨짐 → http 사용
    {
        "source": "이데일리 증권",
        "market": "kr",
        "url": "http://rss.edaily.co.kr/stock_news.xml",
    },
    # 연합뉴스 경제
    {
        "source": "연합뉴스 경제",
        "market": "kr",
        "url": "https://www.yna.co.kr/rss/economy.xml",
    },
    # 데일리안 경제
    {
        "source": "데일리안 경제",
        "market": "kr",
        "url": "https://www.dailian.co.kr/rss/economy",
    },
]

# Timeout for HTTP requests (seconds)
_REQUEST_TIMEOUT = 15


def _parse_entry_timestamp(entry) -> datetime:
    """Extract a timezone-aware datetime from a feedparser entry.

    Falls back to the current UTC time when no date fields are present.
    """
    for field in ("published", "updated"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                # Ensure tz-aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def _fetch_feed(feed_cfg: dict, cutoff: datetime) -> list[dict]:
    """Fetch and parse a single RSS feed, returning articles newer than cutoff."""
    source = feed_cfg["source"]
    market = feed_cfg["market"]
    url = feed_cfg["url"]

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT, headers={"User-Agent": "StoryQuant/1.0"})
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch feed '%s' (%s): %s", source, url, exc)
        return []
    except Exception as exc:
        logger.warning("Unexpected error parsing feed '%s': %s", source, exc)
        return []

    articles = []
    for entry in parsed.entries:
        ts = _parse_entry_timestamp(entry)
        if ts < cutoff:
            continue

        title = getattr(entry, "title", "").strip()
        article_url = getattr(entry, "link", "").strip()
        summary = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
        ).strip()

        articles.append(
            {
                "timestamp": ts.isoformat(),
                "title": title,
                "source": source,
                "market": market,
                "url": article_url,
                "summary": summary,
            }
        )

    logger.info("Feed '%s': %d articles (since %s)", source, len(articles), cutoff.isoformat())
    return articles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl_all_news(hours_back: int = 1) -> pd.DataFrame:
    """Crawl all configured RSS feeds and return a DataFrame.

    Parameters
    ----------
    hours_back:
        Only include articles published within this many hours from now.

    Returns
    -------
    pd.DataFrame with columns:
        timestamp, title, source, market, url, summary
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    logger.info("Crawling %d feeds, cutoff=%s", len(FEEDS), cutoff.isoformat())

    all_articles: list[dict] = []
    for feed_cfg in FEEDS:
        articles = _fetch_feed(feed_cfg, cutoff)
        all_articles.extend(articles)

    if not all_articles:
        logger.warning("No articles collected across all feeds.")
        return pd.DataFrame(columns=["timestamp", "title", "source", "market", "url", "summary"])

    df = pd.DataFrame(all_articles)
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    logger.info("Total articles collected: %d", len(df))
    return df


def save_news_csv(df: pd.DataFrame, data_dir: str = "data/news") -> str:
    """Save the news DataFrame to a timestamped CSV file.

    Parameters
    ----------
    df:
        DataFrame returned by ``crawl_all_news``.
    data_dir:
        Directory where CSV files are written (created if needed).

    Returns
    -------
    Absolute path to the written CSV file.
    """
    os.makedirs(data_dir, exist_ok=True)
    filename = datetime.now().strftime("news_%Y%m%d_%H.csv")
    filepath = os.path.join(data_dir, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    logger.info("Saved %d articles -> %s", len(df), filepath)
    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = crawl_all_news(hours_back=1)
    print(df[["timestamp", "source", "market", "title"]].to_string(index=False))
    path = save_news_csv(df)
    print(f"\nSaved to: {path}")
