"""
community_crawler.py - Community and crypto news crawler for StoryQuant.

Crawls crypto community sources: CoinGecko, The Block, Decrypt,
and Korean crypto news (블록미디어, 토큰포스트, 코인데스크코리아).

Note: CoinMarketCap RSS feeds (headlines/feed, feed) return 404 as of 2026-03.
      Coinness (coinness.com) is a JS-only SPA with no RSS endpoint.
      Both have been replaced with working alternatives.
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

COMMUNITY_FEEDS = [
    # CoinMarketCap RSS removed: all known feed URLs return 404 as of 2026-03.
    {
        "name": "CoinGecko News",
        "url": "https://www.coingecko.com/en/news/rss",
        "market": "crypto",
        "source_type": "community",
    },
    {
        "name": "The Block",
        "url": "https://www.theblock.co/rss.xml",
        "market": "crypto",
        "source_type": "rss",
    },
    {
        "name": "Decrypt",
        "url": "https://decrypt.co/feed",
        "market": "crypto",
        "source_type": "rss",
    },
    # Korean crypto news (replacing Coinness which is a JS-only SPA)
    {
        "name": "블록미디어",
        "url": "https://www.blockmedia.co.kr/feed/",
        "market": "crypto",
        "source_type": "community",
    },
    {
        "name": "토큰포스트",
        "url": "https://www.tokenpost.kr/rss",
        "market": "crypto",
        "source_type": "community",
    },
    {
        "name": "코인데스크코리아",
        "url": "https://www.coindeskkorea.com/feed/",
        "market": "crypto",
        "source_type": "community",
    },
]

# Timeout for HTTP requests (seconds)
_REQUEST_TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 StoryQuant/1.0"
    )
}


def _parse_entry_timestamp(entry) -> datetime:
    """Extract a timezone-aware datetime from a feedparser entry.

    Falls back to the current UTC time when no date fields are present.
    """
    for field in ("published", "updated"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def _fetch_feed(feed_cfg: dict, cutoff: datetime) -> list[dict]:
    """Fetch and parse a single RSS feed, returning articles newer than cutoff."""
    name = feed_cfg["name"]
    market = feed_cfg["market"]
    source_type = feed_cfg["source_type"]
    url = feed_cfg["url"]

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch feed '%s' (%s): %s", name, url, exc)
        return []
    except Exception as exc:
        logger.warning("Unexpected error parsing feed '%s': %s", name, exc)
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
                "source": name,
                "market": market,
                "url": article_url,
                "summary": summary,
                "source_type": source_type,
            }
        )

    logger.info("Feed '%s': %d articles (since %s)", name, len(articles), cutoff.isoformat())
    return articles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl_community_news(hours_back: int = 6) -> pd.DataFrame:
    """Crawl all configured community RSS feeds and return a DataFrame.

    Parameters
    ----------
    hours_back:
        Only include articles published within this many hours from now.

    Returns
    -------
    pd.DataFrame with columns:
        timestamp, title, source, market, url, summary, source_type
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    logger.info(
        "Crawling %d community feeds, cutoff=%s", len(COMMUNITY_FEEDS), cutoff.isoformat()
    )

    all_articles: list[dict] = []
    for feed_cfg in COMMUNITY_FEEDS:
        articles = _fetch_feed(feed_cfg, cutoff)
        all_articles.extend(articles)

    _EMPTY_COLS = ["timestamp", "title", "source", "market", "url", "summary", "source_type"]

    if not all_articles:
        logger.warning("No community articles collected across all feeds.")
        return pd.DataFrame(columns=_EMPTY_COLS)

    df = pd.DataFrame(all_articles)
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    logger.info("Total community articles collected: %d", len(df))
    return df


def crawl_coinness(hours_back: int = 6) -> pd.DataFrame:
    """Return Korean crypto news headlines.

    Coinness (coinness.com) is a JavaScript-only SPA with no RSS feed, so it
    cannot be scraped with plain HTTP requests.  This function now returns an
    empty DataFrame and logs a warning; Korean crypto coverage is provided by
    the three RSS feeds in COMMUNITY_FEEDS (블록미디어, 토큰포스트,
    코인데스크코리아) which are fetched by ``crawl_community_news``.

    The function is kept for backwards-compatibility so existing callers do not
    break.
    """
    _EMPTY_COLS = ["timestamp", "title", "source", "market", "url", "summary", "source_type"]
    logger.info(
        "crawl_coinness: Coinness is a JS-only SPA; Korean news is covered by "
        "블록미디어/토큰포스트/코인데스크코리아 feeds in COMMUNITY_FEEDS."
    )
    return pd.DataFrame(columns=_EMPTY_COLS)


def crawl_all_community(hours_back: int = 6) -> pd.DataFrame:
    """Crawl all community sources (RSS feeds + Coinness) and return a combined DataFrame.

    Parameters
    ----------
    hours_back:
        Only include articles published within this many hours from now.

    Returns
    -------
    pd.DataFrame with columns:
        timestamp, title, source, market, url, summary, source_type
    """
    _EMPTY_COLS = ["timestamp", "title", "source", "market", "url", "summary", "source_type"]

    rss_df = crawl_community_news(hours_back=hours_back)
    coinness_df = crawl_coinness(hours_back=hours_back)

    frames = [df for df in (rss_df, coinness_df) if not df.empty]
    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["url"]).reset_index(drop=True)
    combined = combined.sort_values("timestamp", ascending=False).reset_index(drop=True)
    logger.info("crawl_all_community: %d total articles", len(combined))
    return combined


def save_community_csv(df: pd.DataFrame, data_dir: str = "data/news") -> str:
    """Save the community news DataFrame to a timestamped CSV file.

    Parameters
    ----------
    df:
        DataFrame returned by ``crawl_all_community`` or similar.
    data_dir:
        Directory where CSV files are written (created if needed).

    Returns
    -------
    Absolute path to the written CSV file.
    """
    os.makedirs(data_dir, exist_ok=True)
    filename = datetime.now().strftime("community_%Y%m%d_%H.csv")
    filepath = os.path.join(data_dir, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    logger.info("Saved %d community articles -> %s", len(df), filepath)
    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = crawl_all_community(hours_back=6)
    if not df.empty:
        print("\n=== Articles per source ===")
        for source, count in df.groupby("source").size().items():
            print(f"  {source}: {count}")
        print(f"\nTotal: {len(df)} articles\n")
        print(df[["timestamp", "source", "market", "title"]].to_string(index=False))
    else:
        print("No community articles collected.")
    path = save_community_csv(df)
    print(f"\nSaved to: {path}")
