import os
import sqlite3


def get_connection(db_path: str = "data/storyquant.db") -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode enabled."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not exist."""
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT,
            source_type     TEXT,
            market          TEXT,
            title           TEXT,
            summary         TEXT,
            url             TEXT UNIQUE,
            published_at    TIMESTAMP,
            ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            topic_id        INTEGER,
            topic_label     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_articles_published_at
            ON articles (published_at);
        CREATE INDEX IF NOT EXISTS idx_articles_source_type
            ON articles (source_type);
        CREATE INDEX IF NOT EXISTS idx_articles_market
            ON articles (market);

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

        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT,
            timestamp       TIMESTAMP,
            return_1h       REAL,
            volume_ratio    REAL,
            event_type      TEXT,
            severity        TEXT,
            detected_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (ticker, timestamp, event_type)
        );

        CREATE TABLE IF NOT EXISTS attributions (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id                INTEGER REFERENCES events (id),
            article_id              INTEGER REFERENCES articles (id),
            ticker_mention_score    REAL,
            sector_score            REAL,
            time_proximity_score    REAL,
            keyword_score           REAL,
            total_score             REAL,
            confidence              TEXT,
            rank                    INTEGER,
            created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topics (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_label     TEXT,
            keywords        TEXT,
            frequency       INTEGER,
            momentum_score  REAL,
            novelty_score   REAL,
            market          TEXT,
            window_start    TIMESTAMP,
            window_end      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS historical_patterns (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type        TEXT,
            ticker              TEXT,
            topic_label         TEXT,
            avg_return_1h       REAL,
            avg_return_24h      REAL,
            occurrence_count    INTEGER,
            last_seen           TIMESTAMP,
            notes               TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

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
        CREATE INDEX IF NOT EXISTS idx_oi_ticker_ts ON open_interest(ticker, timestamp);

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
        CREATE INDEX IF NOT EXISTS idx_liq_ticker_ts ON liquidations(ticker, timestamp);

        CREATE TABLE IF NOT EXISTS whale_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            from_entity TEXT,
            from_address TEXT,
            to_entity TEXT,
            to_address TEXT,
            usd_value REAL,
            token TEXT,
            chain TEXT,
            tx_hash TEXT,
            source TEXT DEFAULT 'arkham',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_whale_ts ON whale_transfers(timestamp);
        CREATE INDEX IF NOT EXISTS idx_whale_usd ON whale_transfers(usd_value);

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_type TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            exit_price REAL,
            exit_time TIMESTAMP,
            pnl_pct REAL,
            pnl_usd REAL,
            status TEXT DEFAULT 'open',
            signal_details TEXT,
            event_id INTEGER,
            attribution_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker, entry_time);
    """)

    # Add sentiment columns if not exists (migration)
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN sentiment TEXT")
    except Exception:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN sentiment_score REAL")
    except Exception:
        pass

    conn.commit()
