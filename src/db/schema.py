"""
StoryQuant v2 SQLite schema — time-series only.
Knowledge (articles, events, attributions, topics) lives in amure-db graph.
SQLite retains: prices, open_interest, liquidations, whale_transfers.
"""
import os
import sqlite3
from contextlib import contextmanager

from src.config.settings import SQLITE_DB_PATH


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode enabled."""
    db_path = db_path or SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_thread_connection(db_path: str = None) -> sqlite3.Connection:
    """Return a new per-call SQLite connection suitable for background threads."""
    db_path = db_path or SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def thread_connection(db_path: str = None):
    """Context manager for thread-local SQLite connection."""
    db_path = db_path or SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    """Create time-series tables. Knowledge tables removed — now in amure-db graph."""
    cur = conn.cursor()

    cur.executescript("""
        -- ── Price OHLCV (yfinance + Binance WS) ──
        CREATE TABLE IF NOT EXISTS prices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT,
            timestamp   TIMESTAMP,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            source      TEXT DEFAULT 'yfinance',
            UNIQUE (ticker, timestamp, source)
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_timestamp
            ON prices (ticker, timestamp);

        -- ── Open Interest (Binance Futures) ──
        CREATE TABLE IF NOT EXISTS open_interest (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT NOT NULL,
            timestamp       TIMESTAMP NOT NULL,
            open_interest   REAL,
            oi_value_usd    REAL,
            long_short_ratio REAL,
            long_pct        REAL,
            short_pct       REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, timestamp)
        );
        CREATE INDEX IF NOT EXISTS idx_oi_ticker_ts
            ON open_interest(ticker, timestamp);

        -- ── Liquidations (Binance Futures) ──
        CREATE TABLE IF NOT EXISTS liquidations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            timestamp   TIMESTAMP NOT NULL,
            side        TEXT NOT NULL,
            quantity    REAL,
            price       REAL,
            total_usd   REAL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_liq_ticker_ts
            ON liquidations(ticker, timestamp);

        -- ── Whale Transfers (Arkham / Whale Alert) ──
        CREATE TABLE IF NOT EXISTS whale_transfers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TIMESTAMP NOT NULL,
            from_entity     TEXT,
            from_address    TEXT,
            to_entity       TEXT,
            to_address      TEXT,
            usd_value       REAL,
            token           TEXT,
            chain           TEXT,
            tx_hash         TEXT,
            source          TEXT DEFAULT 'arkham',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_whale_ts  ON whale_transfers(timestamp);
        CREATE INDEX IF NOT EXISTS idx_whale_usd ON whale_transfers(usd_value);

        -- ── Paper Trades ──
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            narrative_id    TEXT,
            narrative       TEXT,
            ticker          TEXT NOT NULL,
            direction       TEXT NOT NULL,
            entry_price     REAL NOT NULL,
            entry_time      TIMESTAMP NOT NULL,
            exit_price      REAL,
            exit_time       TIMESTAMP,
            pnl_pct         REAL,
            status          TEXT DEFAULT 'open',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    """)

    conn.commit()
