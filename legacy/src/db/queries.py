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

# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------

def open_trade(conn: sqlite3.Connection, narrative_id: str, narrative: str,
               ticker: str, direction: str, entry_price: float, entry_time: str) -> int:
    cur = conn.execute(
        "INSERT INTO trades (narrative_id, narrative, ticker, direction, entry_price, entry_time, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'open')",
        [narrative_id, narrative, ticker, direction, entry_price, entry_time],
    )
    conn.commit()
    return cur.lastrowid


def close_trade(conn: sqlite3.Connection, trade_id: int, exit_price: float, exit_time: str) -> float:
    trade = conn.execute("SELECT entry_price, direction FROM trades WHERE id = ?", [trade_id]).fetchone()
    if not trade:
        return 0.0
    entry_price, direction = trade
    if direction == "long":
        pnl = (exit_price - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - exit_price) / entry_price * 100
    conn.execute(
        "UPDATE trades SET exit_price=?, exit_time=?, pnl_pct=?, status='closed' WHERE id=?",
        [exit_price, exit_time, round(pnl, 4), trade_id],
    )
    conn.commit()
    return pnl


def get_open_trades(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM trades WHERE status='open' ORDER BY entry_time DESC", conn)


def get_trade_history(conn: sqlite3.Connection, limit: int = 100) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", conn, params=[limit])


def get_trade_stats(conn: sqlite3.Connection) -> dict:
    closed = pd.read_sql_query("SELECT * FROM trades WHERE status='closed'", conn)
    if closed.empty:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0}
    wins = len(closed[closed["pnl_pct"] > 0])
    return {
        "total": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "win_rate": round(wins / len(closed) * 100, 1),
        "avg_pnl": round(closed["pnl_pct"].mean(), 2),
        "total_pnl": round(closed["pnl_pct"].sum(), 2),
    }


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
