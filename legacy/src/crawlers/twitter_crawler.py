"""
twitter_crawler.py - RSS-based Twitter/X crawler for StoryQuant PoC.

Fetches tweets from curated crypto/finance accounts via free RSS sources
(Nitter instances, RSSHub) with graceful fallback between providers.
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
# Account definitions
# ---------------------------------------------------------------------------

CRYPTO_ACCOUNTS = [
    {"handle": "whale_alert", "name": "Whale Alert", "market": "crypto"},
    {"handle": "WatcherGuru", "name": "Watcher Guru", "market": "crypto"},
    {"handle": "CryptoQuant_com", "name": "CryptoQuant", "market": "crypto"},
    {"handle": "binance", "name": "Binance", "market": "crypto"},
    {"handle": "caborhedge", "name": "Zerohedge", "market": "us"},
]

FINANCE_ACCOUNTS = [
    {"handle": "DeItaone", "name": "Walter Bloomberg", "market": "us"},
    {"handle": "FirstSquawk", "name": "First Squawk", "market": "us"},
]

# ---------------------------------------------------------------------------
# RSS provider instances
# ---------------------------------------------------------------------------

NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.net",
]

RSSHUB_INSTANCES = [
    "https://rsshub.app",
]

# Timeout per HTTP attempt (seconds)
_REQUEST_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _fetch_rss(url: str, label: str) -> feedparser.FeedParserDict | None:
    """Attempt to fetch and parse an RSS URL.

    Returns the parsed feed on success, None on any failure.
    """
    try:
        response = requests.get(
            url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "StoryQuant/1.0"},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        # feedparser never raises; check that we got actual entries
        if parsed.bozo and not parsed.entries:
            logger.warning("Malformed feed from %s (%s)", label, url)
            return None
        return parsed
    except requests.RequestException as exc:
        logger.warning("Request failed for %s (%s): %s", label, url, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error for %s (%s): %s", label, url, exc)
        return None


def _try_fetch_twitter_rss(handle: str, market: str, hours_back: int = 6) -> list[dict]:
    """Try each Nitter instance then RSSHub until one returns usable data.

    Parameters
    ----------
    handle:
        Twitter/X handle (no @).
    market:
        Market tag, e.g. "crypto" or "us".
    hours_back:
        Discard tweets older than this many hours.

    Returns
    -------
    List of dicts with keys: timestamp, title, source, market, url, summary.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    source_label = f"X/@{handle}"

    # Build candidate URLs: Nitter first, then RSSHub
    candidates: list[tuple[str, str]] = []
    for instance in NITTER_INSTANCES:
        candidates.append((f"{instance}/{handle}/rss", f"nitter({instance})"))
    for instance in RSSHUB_INSTANCES:
        candidates.append((f"{instance}/twitter/user/{handle}", f"rsshub({instance})"))

    for url, provider in candidates:
        parsed = _fetch_rss(url, f"{handle} via {provider}")
        if parsed is None or not parsed.entries:
            continue

        logger.info("Success: %s -> %s (%d entries total)", handle, provider, len(parsed.entries))
        tweets = []
        for entry in parsed.entries:
            ts = _parse_entry_timestamp(entry)
            if ts < cutoff:
                continue

            # Use title as the short tweet text (Nitter puts the tweet body here)
            raw_title = getattr(entry, "title", "").strip()
            title = raw_title[:280]

            raw_summary = (
                getattr(entry, "summary", "") or getattr(entry, "description", "")
            ).strip()
            tweet_url = getattr(entry, "link", "").strip()

            tweets.append(
                {
                    "timestamp": ts.isoformat(),
                    "title": title,
                    "source": source_label,
                    "market": market,
                    "url": tweet_url,
                    "summary": raw_summary,
                }
            )

        logger.info("@%s: %d tweets in last %dh", handle, len(tweets), hours_back)
        return tweets

    logger.warning("All RSS sources failed for @%s — skipping.", handle)
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl_twitter(
    hours_back: int = 6,
    accounts: list[dict] | None = None,
) -> pd.DataFrame:
    """Crawl Twitter/X accounts via RSS and return a combined DataFrame.

    Parameters
    ----------
    hours_back:
        Only include tweets published within this many hours from now.
    accounts:
        List of account dicts with keys ``handle``, ``name``, ``market``.
        Defaults to CRYPTO_ACCOUNTS + FINANCE_ACCOUNTS.

    Returns
    -------
    pd.DataFrame with columns:
        timestamp, title, source, market, url, summary, source_type
    """
    if accounts is None:
        accounts = CRYPTO_ACCOUNTS + FINANCE_ACCOUNTS

    logger.info("Crawling %d Twitter accounts, hours_back=%d", len(accounts), hours_back)

    all_tweets: list[dict] = []
    for account in accounts:
        handle = account["handle"]
        market = account["market"]
        tweets = _try_fetch_twitter_rss(handle, market, hours_back=hours_back)
        all_tweets.extend(tweets)

    _columns = ["timestamp", "title", "source", "market", "url", "summary", "source_type"]

    if not all_tweets:
        logger.warning("No tweets collected across all accounts.")
        return pd.DataFrame(columns=_columns)

    df = pd.DataFrame(all_tweets)
    df["source_type"] = "twitter"
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    df = df[_columns]
    logger.info("Total tweets collected: %d", len(df))
    return df


def save_twitter_csv(df: pd.DataFrame, data_dir: str = "data/news") -> str:
    """Save the tweets DataFrame to a timestamped CSV file.

    Parameters
    ----------
    df:
        DataFrame returned by ``crawl_twitter``.
    data_dir:
        Directory where CSV files are written (created if needed).

    Returns
    -------
    Absolute path to the written CSV file.
    """
    os.makedirs(data_dir, exist_ok=True)
    filename = datetime.now().strftime("twitter_%Y%m%d_%H.csv")
    filepath = os.path.join(data_dir, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    logger.info("Saved %d tweets -> %s", len(df), filepath)
    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = crawl_twitter(hours_back=6)
    if df.empty:
        print("No tweets found.")
    else:
        print(df[["timestamp", "source", "market", "title"]].to_string(index=False))
    path = save_twitter_csv(df)
    print(f"\nSaved to: {path}")
