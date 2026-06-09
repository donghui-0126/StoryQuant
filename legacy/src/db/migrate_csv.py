"""
One-time migration: read all CSVs from data/{news,prices,events,topics}/
and insert them into the SQLite database.

Usage:
    python -m src.db.migrate_csv
    # or
    python src/db/migrate_csv.py
"""

import glob
import os
import sys

import pandas as pd

# Allow running as a script from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db.schema import get_connection, init_db
from src.db.queries import (
    insert_articles,
    insert_prices,
    insert_events,
    insert_topics,
)


# ---------------------------------------------------------------------------
# Per-table loaders
# ---------------------------------------------------------------------------

def _load_news(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # CSV columns: timestamp, title, source, market, url, summary
    rename = {"timestamp": "published_at"}
    df = df.rename(columns=rename)
    # Ensure expected columns exist; fill missing ones with None
    for col in ["source_type", "topic_id", "topic_label"]:
        if col not in df.columns:
            df[col] = None
    return df


def _load_prices(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # CSV columns: ticker, timestamp, open, high, low, close, volume
    if "source" not in df.columns:
        df["source"] = "yfinance"
    return df


def _load_events(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # CSV columns: ticker, timestamp, return_1h, volume_ratio, event_type, severity
    return df


def _load_topics(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # CSV columns: topic_id, topic_label, keywords, frequency,
    #              momentum_score, novelty_score, market, representative_headlines
    # Map to schema columns; drop columns not in schema
    rename = {}
    df = df.rename(columns=rename)
    for col in ["window_start", "window_end"]:
        if col not in df.columns:
            df[col] = None
    return df


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def migrate(db_path: str = "data/storyquant.db") -> None:
    conn = get_connection(db_path)
    init_db(conn)
    print(f"Database initialised at {db_path}")

    # --- News / articles ---
    news_files = sorted(glob.glob("data/news/*.csv"))
    if news_files:
        frames = [_load_news(f) for f in news_files]
        df = pd.concat(frames, ignore_index=True)
        insert_articles(conn, df)
        print(f"  articles: inserted up to {len(df)} rows from {len(news_files)} file(s)")
    else:
        print("  articles: no CSV files found in data/news/")

    # --- Prices ---
    price_files = sorted(glob.glob("data/prices/*.csv"))
    if price_files:
        frames = [_load_prices(f) for f in price_files]
        df = pd.concat(frames, ignore_index=True)
        insert_prices(conn, df)
        print(f"  prices:   inserted up to {len(df)} rows from {len(price_files)} file(s)")
    else:
        print("  prices: no CSV files found in data/prices/")

    # --- Events ---
    event_files = sorted(glob.glob("data/events/*.csv"))
    if event_files:
        frames = [_load_events(f) for f in event_files]
        df = pd.concat(frames, ignore_index=True)
        insert_events(conn, df)
        print(f"  events:   inserted up to {len(df)} rows from {len(event_files)} file(s)")
    else:
        print("  events: no CSV files found in data/events/")

    # --- Topics ---
    topic_files = sorted(glob.glob("data/topics/*.csv"))
    if topic_files:
        frames = [_load_topics(f) for f in topic_files]
        df = pd.concat(frames, ignore_index=True)
        insert_topics(conn, df)
        print(f"  topics:   inserted up to {len(df)} rows from {len(topic_files)} file(s)")
    else:
        print("  topics: no CSV files found in data/topics/")

    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/storyquant.db"
    migrate(db_path)
