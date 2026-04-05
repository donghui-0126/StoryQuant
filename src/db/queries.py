import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_recent_articles(
    conn: sqlite3.Connection,
    hours: int = 6,
    market: Optional[str] = None,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM articles WHERE published_at >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if market is not None:
        sql += " AND market = ?"
        params.append(market)
    sql += " ORDER BY published_at DESC"
    return pd.read_sql_query(sql, conn, params=params)


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


def get_recent_events(
    conn: sqlite3.Connection,
    hours: int = 24,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM events WHERE timestamp >= ? ORDER BY timestamp DESC"
    return pd.read_sql_query(sql, conn, params=[cutoff.isoformat(timespec='seconds')])


def get_recent_topics(
    conn: sqlite3.Connection,
    hours: int = 6,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM topics WHERE created_at >= ? ORDER BY created_at DESC"
    return pd.read_sql_query(sql, conn, params=[cutoff.isoformat(timespec='seconds')])


def get_attributions_for_events(
    conn: sqlite3.Connection,
    event_ids: List[int],
) -> pd.DataFrame:
    if not event_ids:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(event_ids))
    sql = f"SELECT * FROM attributions WHERE event_id IN ({placeholders}) ORDER BY event_id, rank"
    return pd.read_sql_query(sql, conn, params=event_ids)


def get_historical_patterns(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
) -> pd.DataFrame:
    sql = "SELECT * FROM historical_patterns"
    params: list = []
    if ticker is not None:
        sql += " WHERE ticker = ?"
        params.append(ticker)
    sql += " ORDER BY last_seen DESC"
    return pd.read_sql_query(sql, conn, params=params)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def insert_articles(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert articles, silently skipping duplicates (by url)."""
    if df.empty:
        return
    cols = [
        "source", "source_type", "market", "title", "summary",
        "url", "published_at", "ingested_at", "topic_id", "topic_label",
    ]
    _insert_df(conn, "articles", df, cols, on_conflict="IGNORE")


def insert_prices(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Insert/replace price rows (upsert on ticker+timestamp+source)."""
    if df.empty:
        return
    cols = ["ticker", "timestamp", "open", "high", "low", "close", "volume", "source"]
    _insert_df(conn, "prices", df, cols, on_conflict="REPLACE")


def insert_events(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Insert events and return the DataFrame with a populated 'id' column."""
    if df.empty:
        return df
    cols = ["ticker", "timestamp", "return_1h", "volume_ratio", "event_type", "severity"]
    _insert_df(conn, "events", df, cols, on_conflict="IGNORE")

    # Re-fetch inserted IDs by matching on the unique key
    keys = df[["ticker", "timestamp", "event_type"]].drop_duplicates()
    placeholders = " OR ".join(
        ["(ticker=? AND timestamp=? AND event_type=?)"] * len(keys)
    )
    params = []
    for _, row in keys.iterrows():
        params.extend([row["ticker"], str(row["timestamp"]), row["event_type"]])
    id_df = pd.read_sql_query(
        f"SELECT id, ticker, timestamp, event_type FROM events WHERE {placeholders}",
        conn,
        params=params,
    )
    # Normalize timestamp types before merge
    df = df.copy()
    df["timestamp"] = df["timestamp"].astype(str)
    id_df["timestamp"] = id_df["timestamp"].astype(str)
    df = df.merge(id_df, on=["ticker", "timestamp", "event_type"], how="left")
    return df


def insert_topics(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = [
        "topic_label", "keywords", "frequency", "momentum_score",
        "novelty_score", "market", "window_start", "window_end",
    ]
    _insert_df(conn, "topics", df, cols, on_conflict="IGNORE")


def insert_attributions(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = [
        "event_id", "article_id", "ticker_mention_score", "sector_score",
        "time_proximity_score", "keyword_score", "total_score", "confidence", "rank",
    ]
    _insert_df(conn, "attributions", df, cols, on_conflict="IGNORE")


def insert_open_interest(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """INSERT OR REPLACE open interest data."""
    if df.empty:
        return
    cols = [
        "ticker", "timestamp", "open_interest", "oi_value_usd",
        "long_short_ratio", "long_pct", "short_pct",
    ]
    _insert_df(conn, "open_interest", df, cols, on_conflict="REPLACE")


def insert_liquidations(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """INSERT liquidation data."""
    if df.empty:
        return
    cols = ["ticker", "timestamp", "side", "quantity", "price", "total_usd"]
    _insert_df(conn, "liquidations", df, cols, on_conflict="IGNORE")


def get_recent_oi(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    hours: int = 48,
) -> pd.DataFrame:
    """Get recent open interest data."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM open_interest WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker)
    sql += " ORDER BY ticker, timestamp"
    return pd.read_sql_query(sql, conn, params=params)


def get_recent_liquidations(
    conn: sqlite3.Connection,
    ticker: Optional[str] = None,
    hours: int = 24,
) -> pd.DataFrame:
    """Get recent liquidation data."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = "SELECT * FROM liquidations WHERE timestamp >= ?"
    params: list = [cutoff.isoformat(timespec='seconds')]
    if ticker is not None:
        sql += " AND ticker = ?"
        params.append(ticker)
    sql += " ORDER BY ticker, timestamp DESC"
    return pd.read_sql_query(sql, conn, params=params)


def insert_whale_transfers(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = ["timestamp", "from_entity", "from_address", "to_entity", "to_address",
            "usd_value", "token", "chain", "tx_hash", "source"]
    _insert_df(conn, "whale_transfers", df, cols, on_conflict="IGNORE")


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


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def insert_trade(conn: sqlite3.Connection, trade: dict) -> int:
    """Insert a new trade and return its ID."""
    cols = ["signal_type", "ticker", "direction", "entry_price", "entry_time", "status", "signal_details", "event_id", "attribution_id"]
    present = {k: v for k, v in trade.items() if k in cols and v is not None}
    col_str = ",".join(present.keys())
    placeholders = ",".join("?" * len(present))
    cursor = conn.execute(f"INSERT INTO trades ({col_str}) VALUES ({placeholders})", list(present.values()))
    conn.commit()
    return cursor.lastrowid


def close_trade(conn: sqlite3.Connection, trade_id: int, exit_price: float, exit_time: str):
    """Close an open trade with exit price and calculate PnL."""
    trade = conn.execute("SELECT entry_price, direction FROM trades WHERE id = ?", [trade_id]).fetchone()
    if not trade:
        return
    entry_price, direction = trade
    if direction == "long":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    conn.execute(
        "UPDATE trades SET exit_price=?, exit_time=?, pnl_pct=?, status='closed' WHERE id=?",
        [exit_price, exit_time, round(pnl_pct, 4), trade_id]
    )
    conn.commit()


def get_open_trades(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC", conn)


def get_trade_history(conn: sqlite3.Connection, limit: int = 100) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", conn, params=[limit])


def get_trade_stats(conn: sqlite3.Connection) -> dict:
    """Compute overall trading statistics."""
    closed = pd.read_sql_query("SELECT * FROM trades WHERE status = 'closed'", conn)
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
        "best": round(closed["pnl_pct"].max(), 2),
        "worst": round(closed["pnl_pct"].min(), 2),
    }


def _insert_df(
    conn: sqlite3.Connection,
    table: str,
    df: pd.DataFrame,
    cols: List[str],
    on_conflict: str = "IGNORE",
) -> None:
    present = [c for c in cols if c in df.columns]
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
