"""
StoryQuant v2 queries — time-series only.
Knowledge queries (articles, events, attributions, topics) now go through
src.graph.reasoning module → amure-db API.
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Price queries
# ---------------------------------------------------------------------------

def get_recent_prices(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    hours: int = 72,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM prices WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker)
    sql += " ORDER BY ticker, timestamp"
    return pd.read_sql_query(sql, conn, params=params)


def insert_prices(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert/replace price rows (upsert on ticker+timestamp+source)."""
    if df.empty:
        return
    cols = ["ticker", "timestamp", "open", "high", "low", "close", "volume", "source"]
    _insert_df(conn, "prices", df, cols, on_conflict="REPLACE")


# ---------------------------------------------------------------------------
# Open Interest queries
# ---------------------------------------------------------------------------

def get_recent_oi(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    hours: int = 48,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM open_interest WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker)
    sql += " ORDER BY ticker, timestamp"
    return pd.read_sql_query(sql, conn, params=params)


def insert_open_interest(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = [
        "ticker", "timestamp", "open_interest", "oi_value_usd",
        "long_short_ratio", "long_pct", "short_pct",
    ]
    _insert_df(conn, "open_interest", df, cols, on_conflict="REPLACE")


# ---------------------------------------------------------------------------
# Liquidation queries
# ---------------------------------------------------------------------------

def get_recent_liquidations(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    hours: int = 24,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM liquidations WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker)
    sql += " ORDER BY ticker, timestamp DESC"
    return pd.read_sql_query(sql, conn, params=params)


def insert_liquidations(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = ["ticker", "timestamp", "side", "quantity", "price", "total_usd"]
    _insert_df(conn, "liquidations", df, cols, on_conflict="IGNORE")


# ---------------------------------------------------------------------------
# Whale transfer queries
# ---------------------------------------------------------------------------

def get_recent_whale_transfers(
    conn: sqlite3.Connection,
    hours: int = 24,
    min_usd: Optional[float] = None,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM whale_transfers WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if min_usd:
        sql += " AND usd_value >= ?"
        params.append(min_usd)
    sql += " ORDER BY usd_value DESC"
    return pd.read_sql_query(sql, conn, params=params)


def insert_whale_transfers(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = ["timestamp", "from_entity", "from_address", "to_entity", "to_address",
            "usd_value", "token", "chain", "tx_hash", "source"]
    _insert_df(conn, "whale_transfers", df, cols, on_conflict="IGNORE")


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _insert_df(
    conn: sqlite3.Connection,
    table: str,
    df: pd.DataFrame,
    cols: List[str],
    on_conflict: str = "IGNORE",
) -> None:
    present = [c for c in cols if c in df.columns]
    if not present:
        return
    placeholders = ",".join("?" * len(present))
    col_list = ",".join(present)
    sql = f"INSERT OR {on_conflict} INTO {table} ({col_list}) VALUES ({placeholders})"

    def _convert(val):
        if isinstance(val, list):
            return json.dumps(val, ensure_ascii=False)
        if hasattr(val, 'isoformat'):
            return val.isoformat()
        if isinstance(val, pd.Timestamp):
            return str(val)
        return val

    rows = [
        tuple(_convert(v) for v in row)
        for row in df[present].itertuples(index=False, name=None)
    ]
    conn.executemany(sql, rows)
    conn.commit()
