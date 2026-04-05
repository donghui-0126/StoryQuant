"""
Crawl exchange announcements from Binance's public CMS API.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BINANCE_API_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
)
_BINANCE_ARTICLE_BASE = "https://www.binance.com/en/support/announcement"

# Multiple catalog IDs to cover key announcement types
_CATALOG_IDS = {
    48: "New Cryptocurrency Listing",
    49: "Latest Binance News",
    161: "Delisting",
    128: "Crypto Airdrop",
}

# Keyword -> label mapping (checked in order; first match wins)
_TITLE_LABELS = [
    (["new listing", "will list", "will launch"], "[NEW LISTING]"),
    (["delist", "removal of spot"], "[DELISTING]"),
    (["maintenance", "system upgrade"], "[MAINTENANCE]"),
    (["trading pair", "new pairs"], "[NEW PAIR]"),
    (["airdrop", "hodler"], "[AIRDROP]"),
    (["futures", "perpetual"], "[FUTURES]"),
]


def _classify_title(title: str) -> Optional[str]:
    """Return a label prefix if the title matches a known keyword, else None."""
    lower = title.lower()
    for keywords, label in _TITLE_LABELS:
        if any(kw in lower for kw in keywords):
            return label
    return None


def fetch_binance_announcements(hours_back: int = 6) -> pd.DataFrame:
    """
    Fetch recent Binance announcements from the public CMS API.

    Parameters
    ----------
    hours_back : int
        Only include articles published within this many hours.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, title, source, market, url, summary, source_type
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; StoryQuant/1.0; +https://github.com/storyquant)"
        )
    }

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    rows = []
    seen_urls = set()

    for catalog_id, catalog_name in _CATALOG_IDS.items():
        params = {
            "type": 1,
            "catalogId": catalog_id,
            "pageNo": 1,
            "pageSize": 20,
        }

        try:
            resp = requests.get(
                _BINANCE_API_URL, params=params, headers=headers, timeout=10
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            logger.warning("Failed to fetch Binance catalog %s: %s", catalog_name, exc)
            continue

        try:
            data = payload.get("data", {})
            catalogs = data.get("catalogs", [])
            if catalogs:
                articles_raw = catalogs[0].get("articles", [])
            else:
                articles_raw = data.get("articles", [])
        except (AttributeError, IndexError, KeyError) as exc:
            logger.warning("Unexpected response for catalog %s: %s", catalog_name, exc)
            continue

        for article in articles_raw:
            try:
                release_ms = article.get("releaseDate", 0)
                published_at = datetime.fromtimestamp(release_ms / 1000, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                logger.debug("Could not parse releaseDate for article: %s", article)
                continue

            if published_at < cutoff:
                continue

            title = str(article.get("title", "")).strip()
            code = str(article.get("code", "")).strip()
            url = f"{_BINANCE_ARTICLE_BASE}/{code}" if code else ""

            if url in seen_urls:
                continue
            seen_urls.add(url)

            body = str(article.get("body", "") or "").strip()
            summary = body[:200] if body else f"[{catalog_name}]"

            label = _classify_title(title)
            if label and summary:
                summary = f"{label} {summary}"
            elif label:
                summary = label

            rows.append(
                {
                    "timestamp": published_at,
                    "title": title,
                    "source": "Binance",
                    "market": "crypto",
                    "url": url,
                    "summary": summary,
                    "source_type": "exchange_announcement",
                }
            )

    df = pd.DataFrame(
        rows,
        columns=["timestamp", "title", "source", "market", "url", "summary", "source_type"],
    )
    logger.info("Fetched %d Binance announcements (last %dh)", len(df), hours_back)
    return df


def save_announcements_csv(df: pd.DataFrame, data_dir: str = "data/news") -> str:
    """
    Save announcements DataFrame to a CSV file.

    Parameters
    ----------
    df : pd.DataFrame
    data_dir : str
        Directory to write into.

    Returns
    -------
    str
        Path of the written file.
    """
    os.makedirs(data_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(data_dir, f"binance_announcements_{date_str}.csv")
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("Saved announcements to %s", path)
    return path


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    df = fetch_binance_announcements(hours_back=24)
    if df.empty:
        print("No announcements found in the last 24 hours.")
    else:
        print(df[["timestamp", "title", "source_type"]].to_string(index=False))
        out = save_announcements_csv(df)
        print(f"\nSaved to: {out}")
