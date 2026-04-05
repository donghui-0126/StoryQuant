"""
Cross-asset correlation analysis for StoryQuant.
Analyzes price correlations and lead-lag relationships between assets.
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sector mapping
# ---------------------------------------------------------------------------

SECTOR_MAP = {
    "BTC-USD":   "crypto",
    "ETH-USD":   "crypto",
    "SOL-USD":   "crypto",
    "NVDA":      "us_tech",
    "AAPL":      "us_tech",
    "TSLA":      "us_tech",
    "SPY":       "us_index",
    "005930.KS": "kr_semi",
    "000660.KS": "kr_semi",
    "035420.KS": "kr_tech",
}

# ---------------------------------------------------------------------------
# Column contracts for empty-DataFrame returns
# ---------------------------------------------------------------------------

_LEAD_LAG_COLS = ["leader", "follower", "lag_hours", "correlation", "direction"]
_SPILLOVER_COLS = [
    "source_ticker", "source_event_type", "target_ticker",
    "avg_target_return", "occurrence_count", "positive_rate",
]
_SECTOR_CORR_COLS = ["sector_a", "sector_b", "avg_correlation"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_hourly_returns(conn: sqlite3.Connection, hours: int) -> pd.DataFrame:
    """
    Load prices from DB, resample to 1h close, compute 1h returns.

    Returns a wide DataFrame: index=timestamp (hourly), columns=tickers.
    Returns empty DataFrame if fewer than 2 tickers have data.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sql = """
        SELECT ticker, timestamp, close
        FROM prices
        WHERE timestamp >= :cutoff
        ORDER BY ticker, timestamp
    """
    try:
        df = pd.read_sql_query(sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("_load_hourly_returns query failed: %s", exc)
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp", "close"])

    # Resample each ticker to 1h, take last close in each bucket
    pieces = []
    for ticker, group in df.groupby("ticker"):
        ts = group.set_index("timestamp")["close"].sort_index()
        ts_1h = ts.resample("1h").last().dropna()
        if len(ts_1h) < 2:
            continue
        ret = ts_1h.pct_change().dropna()
        ret.name = ticker
        pieces.append(ret)

    if len(pieces) < 2:
        return pd.DataFrame()

    wide = pd.concat(pieces, axis=1, join="outer")
    return wide


# ---------------------------------------------------------------------------
# 1. Return correlation matrix
# ---------------------------------------------------------------------------

def compute_return_correlation(conn: sqlite3.Connection, hours: int = 72) -> pd.DataFrame:
    """
    Compute pairwise return correlation matrix for all assets.

    Returns
    -------
    pd.DataFrame
        Symmetric correlation matrix with tickers as both index and columns.
        Empty DataFrame when insufficient data.
    """
    wide = _load_hourly_returns(conn, hours)
    if wide.empty or wide.shape[1] < 2:
        return pd.DataFrame()

    corr = wide.corr(min_periods=5)
    return corr


# ---------------------------------------------------------------------------
# 2. Lead-lag relationships
# ---------------------------------------------------------------------------

def compute_lead_lag(
    conn: sqlite3.Connection,
    hours: int = 72,
    max_lag: int = 3,
) -> pd.DataFrame:
    """
    Find lead-lag relationships between assets.

    For each ordered pair (A, B), compute the correlation of A's return at
    time t with B's return at time t+lag for lag in 1..max_lag.

    Returns
    -------
    pd.DataFrame
        Columns: leader, follower, lag_hours, correlation, direction
        Only rows where |correlation| > 0.3 are returned.
    """
    wide = _load_hourly_returns(conn, hours)
    if wide.empty or wide.shape[1] < 2:
        return pd.DataFrame(columns=_LEAD_LAG_COLS)

    tickers = wide.columns.tolist()
    records = []
    for lag in range(1, max_lag + 1):
        for leader in tickers:
            for follower in tickers:
                if leader == follower:
                    continue
                # leader at t vs follower at t+lag
                x = wide[leader].iloc[:-lag].values
                y = wide[follower].iloc[lag:].values
                if len(x) < 5:
                    continue
                corr = float(np.corrcoef(x, y)[0, 1])
                if np.isnan(corr) or abs(corr) <= 0.3:
                    continue
                records.append({
                    "leader":      leader,
                    "follower":    follower,
                    "lag_hours":   lag,
                    "correlation": round(corr, 4),
                    "direction":   "positive" if corr > 0 else "negative",
                })

    if not records:
        return pd.DataFrame(columns=_LEAD_LAG_COLS)

    result = pd.DataFrame(records)
    result = (
        result.sort_values("correlation", key=abs, ascending=False)
        .drop_duplicates(subset=["leader", "follower"])
        .reset_index(drop=True)
    )
    return result[_LEAD_LAG_COLS]


# ---------------------------------------------------------------------------
# 3. Event spillover
# ---------------------------------------------------------------------------

def compute_event_spillover(conn: sqlite3.Connection, hours: int = 72) -> pd.DataFrame:
    """
    When a price event happens on asset A, what happens to other assets?

    For each event, look at other assets' returns in the same 1-hour window
    and aggregate by (source_ticker, source_event_type, target_ticker).

    Returns
    -------
    pd.DataFrame
        Columns: source_ticker, source_event_type, target_ticker,
                 avg_target_return, occurrence_count, positive_rate
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    events_sql = """
        SELECT ticker, timestamp, event_type
        FROM events
        WHERE timestamp >= :cutoff
        ORDER BY timestamp
    """
    prices_sql = """
        SELECT ticker, timestamp, close
        FROM prices
        WHERE timestamp >= :cutoff
        ORDER BY ticker, timestamp
    """

    try:
        events = pd.read_sql_query(events_sql, conn, params={"cutoff": cutoff})
        prices = pd.read_sql_query(prices_sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("compute_event_spillover query failed: %s", exc)
        return pd.DataFrame(columns=_SPILLOVER_COLS)

    if events.empty or prices.empty:
        return pd.DataFrame(columns=_SPILLOVER_COLS)

    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True, errors="coerce")
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce")
    events = events.dropna(subset=["timestamp"])
    prices = prices.dropna(subset=["timestamp", "close"])

    # Build 1h returns per ticker from prices
    ret_pieces = []
    for ticker, group in prices.groupby("ticker"):
        ts = group.set_index("timestamp")["close"].sort_index()
        ts_1h = ts.resample("1h").last().dropna()
        ret = ts_1h.pct_change().dropna()
        ret_df = ret.reset_index()
        ret_df.columns = ["timestamp", "return_1h"]
        ret_df["ticker"] = ticker
        ret_pieces.append(ret_df)

    if not ret_pieces:
        return pd.DataFrame(columns=_SPILLOVER_COLS)

    returns = pd.concat(ret_pieces, ignore_index=True)

    records = []
    for _, ev in events.iterrows():
        src_ticker = ev["ticker"]
        ev_ts = ev["timestamp"]
        ev_type = ev["event_type"]

        # Find returns of other tickers in the same 1h bucket
        bucket_start = ev_ts.floor("1h")
        bucket_end = bucket_start + pd.Timedelta(hours=1)
        targets = returns[
            (returns["ticker"] != src_ticker) &
            (returns["timestamp"] >= bucket_start) &
            (returns["timestamp"] < bucket_end)
        ]

        for _, tgt in targets.iterrows():
            records.append({
                "source_ticker":     src_ticker,
                "source_event_type": ev_type,
                "target_ticker":     tgt["ticker"],
                "return":            tgt["return_1h"],
            })

    if not records:
        return pd.DataFrame(columns=_SPILLOVER_COLS)

    df = pd.DataFrame(records)
    agg = (
        df.groupby(["source_ticker", "source_event_type", "target_ticker"])
        .agg(
            avg_target_return=("return", "mean"),
            occurrence_count=("return", "count"),
            positive_rate=("return", lambda x: (x > 0).mean()),
        )
        .reset_index()
    )
    for col in ["avg_target_return", "positive_rate"]:
        agg[col] = agg[col].round(4)

    return agg[_SPILLOVER_COLS]


# ---------------------------------------------------------------------------
# 4. Sector correlation
# ---------------------------------------------------------------------------

def compute_sector_correlation(conn: sqlite3.Connection, hours: int = 72) -> pd.DataFrame:
    """
    Compute average pairwise return correlation within and between sectors.

    Returns
    -------
    pd.DataFrame
        Columns: sector_a, sector_b, avg_correlation
    """
    wide = _load_hourly_returns(conn, hours)
    if wide.empty or wide.shape[1] < 2:
        return pd.DataFrame(columns=_SECTOR_CORR_COLS)

    corr = wide.corr()

    # Map each ticker in the correlation matrix to a sector
    tickers_present = [t for t in corr.columns if t in SECTOR_MAP]
    if len(tickers_present) < 2:
        return pd.DataFrame(columns=_SECTOR_CORR_COLS)

    corr = corr.loc[tickers_present, tickers_present]
    sectors = {t: SECTOR_MAP[t] for t in tickers_present}

    sector_pairs: dict[tuple, list] = {}
    for i, t_a in enumerate(tickers_present):
        for j, t_b in enumerate(tickers_present):
            if i >= j:
                continue
            s_a = sectors[t_a]
            s_b = sectors[t_b]
            key = (min(s_a, s_b), max(s_a, s_b))
            sector_pairs.setdefault(key, []).append(corr.loc[t_a, t_b])

    if not sector_pairs:
        return pd.DataFrame(columns=_SECTOR_CORR_COLS)

    records = [
        {
            "sector_a":        k[0],
            "sector_b":        k[1],
            "avg_correlation": round(float(np.mean(vals)), 4),
        }
        for k, vals in sector_pairs.items()
    ]
    return pd.DataFrame(records)[_SECTOR_CORR_COLS]


# ---------------------------------------------------------------------------
# Report facade
# ---------------------------------------------------------------------------

def generate_correlation_report(conn: sqlite3.Connection) -> dict:
    """Run all analyses and return dict of DataFrames."""
    logger.info("Generating correlation report...")
    report = {
        "correlation_matrix": compute_return_correlation(conn),
        "lead_lag":           compute_lead_lag(conn),
        "event_spillover":    compute_event_spillover(conn),
        "sector_correlation": compute_sector_correlation(conn),
    }
    for key, df in report.items():
        logger.info("  %s: %d rows", key, len(df))
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/storyquant.db"

    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        print("Run the pipeline first to populate data.")
        sys.exit(1)

    import sqlite3 as _sqlite3
    _conn = _sqlite3.connect(db_path)
    _conn.execute("PRAGMA journal_mode=WAL")

    _report = generate_correlation_report(_conn)

    for section, df in _report.items():
        print(f"\n{'='*60}")
        print(f"  {section.upper().replace('_', ' ')}")
        print(f"{'='*60}")
        if df.empty:
            print("  (no data yet)")
        else:
            print(df.to_string(index=False))

    _conn.close()
