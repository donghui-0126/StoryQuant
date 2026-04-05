"""
backtest.py - Historical backtest engine for StoryQuant.

Collects price data from 2024-H2 onward, runs event detection,
computes forward returns (1h, 4h, 24h), and generates backtest statistics.

Usage:
    python -m src.analysis.backtest              # Full backtest
    python -m src.analysis.backtest --summary    # Print summary only
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TICKERS = {
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
    "us": ["NVDA", "AAPL", "TSLA", "SPY"],
    "kr": ["005930.KS", "000660.KS", "035420.KS"],
}

ALL_TICKERS = [t for ts in TICKERS.values() for t in ts]

# Event detection thresholds (same as event_detector.py)
RETURN_THRESHOLD = 0.02   # ±2%
ZSCORE_THRESHOLD = 2.0    # 2 sigma
VOLUME_SPIKE_MULT = 2.0   # 2x average

# Forward return windows
FORWARD_WINDOWS = [1, 4, 24]  # hours


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def fetch_historical_prices(
    tickers: list[str] = None,
    start: str = "2024-07-01",
    end: str = None,
) -> pd.DataFrame:
    """Fetch hourly OHLCV data from yfinance for all tickers.

    yfinance limits 1h data to ~730 days, so we fetch in monthly chunks
    to maximize coverage.
    """
    if tickers is None:
        tickers = ALL_TICKERS
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    logger.info("Fetching prices for %d tickers: %s to %s", len(tickers), start, end)

    all_frames = []
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    # Fetch in 60-day chunks to avoid yfinance row limits
    chunk_days = 60
    for ticker in tickers:
        frames = []
        chunk_start = start_dt
        while chunk_start < end_dt:
            chunk_end = min(chunk_start + pd.Timedelta(days=chunk_days), end_dt)
            try:
                df = yf.download(
                    ticker,
                    start=chunk_start.strftime("%Y-%m-%d"),
                    end=chunk_end.strftime("%Y-%m-%d"),
                    interval="1h",
                    progress=False,
                )
                if not df.empty:
                    # Flatten multi-level columns from yfinance
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df = df.reset_index()
                    # Handle both 'Datetime' and 'Date' column names
                    ts_col = "Datetime" if "Datetime" in df.columns else "Date"
                    df = df.rename(columns={
                        ts_col: "timestamp",
                        "Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume",
                    })
                    df["ticker"] = ticker
                    frames.append(df[["timestamp", "ticker", "open", "high", "low", "close", "volume"]])
            except Exception as exc:
                logger.warning("Failed to fetch %s (%s - %s): %s", ticker, chunk_start, chunk_end, exc)
            chunk_start = chunk_end

        if frames:
            ticker_df = pd.concat(frames, ignore_index=True)
            ticker_df = ticker_df.drop_duplicates(subset=["timestamp", "ticker"]).sort_values("timestamp")
            all_frames.append(ticker_df)
            logger.info("  %s: %d rows", ticker, len(ticker_df))

    if not all_frames:
        return pd.DataFrame()

    result = pd.concat(all_frames, ignore_index=True)
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    logger.info("Total: %d price rows for %d tickers", len(result), result["ticker"].nunique())
    return result


# ---------------------------------------------------------------------------
# Event detection (vectorized)
# ---------------------------------------------------------------------------

def detect_events_backtest(prices_df: pd.DataFrame) -> pd.DataFrame:
    """Detect price events across all tickers using vectorized operations.

    Returns DataFrame with columns:
        timestamp, ticker, event_type, severity, return_1h, volume_ratio, zscore
    """
    events = []

    for ticker, group in prices_df.groupby("ticker"):
        g = group.sort_values("timestamp").copy()
        g["return_1h"] = g["close"].pct_change()
        g["vol_ma24"] = g["volume"].rolling(24, min_periods=6).mean()
        g["volume_ratio"] = g["volume"] / g["vol_ma24"]
        g["ret_mean"] = g["return_1h"].rolling(24, min_periods=6).mean()
        g["ret_std"] = g["return_1h"].rolling(24, min_periods=6).std()
        g["zscore"] = (g["return_1h"] - g["ret_mean"]) / g["ret_std"].replace(0, np.nan)

        # Price surge/crash
        surge = g[(g["return_1h"] >= RETURN_THRESHOLD) | (g["zscore"] >= ZSCORE_THRESHOLD)]
        for _, row in surge.iterrows():
            severity = "high" if abs(row["return_1h"]) >= 0.05 else "medium" if abs(row["return_1h"]) >= 0.03 else "low"
            events.append({
                "timestamp": row["timestamp"],
                "ticker": ticker,
                "event_type": "surge",
                "severity": severity,
                "return_1h": row["return_1h"],
                "volume_ratio": row.get("volume_ratio", 0),
                "zscore": row.get("zscore", 0),
            })

        crash = g[(g["return_1h"] <= -RETURN_THRESHOLD) | (g["zscore"] <= -ZSCORE_THRESHOLD)]
        for _, row in crash.iterrows():
            severity = "high" if abs(row["return_1h"]) >= 0.05 else "medium" if abs(row["return_1h"]) >= 0.03 else "low"
            events.append({
                "timestamp": row["timestamp"],
                "ticker": ticker,
                "event_type": "crash",
                "severity": severity,
                "return_1h": row["return_1h"],
                "volume_ratio": row.get("volume_ratio", 0),
                "zscore": row.get("zscore", 0),
            })

        # Volume spike
        vol_spike = g[g["volume_ratio"] >= VOLUME_SPIKE_MULT]
        for _, row in vol_spike.iterrows():
            severity = "high" if row["volume_ratio"] >= 5.0 else "medium" if row["volume_ratio"] >= 3.0 else "low"
            events.append({
                "timestamp": row["timestamp"],
                "ticker": ticker,
                "event_type": "volume_spike",
                "severity": severity,
                "return_1h": row["return_1h"],
                "volume_ratio": row["volume_ratio"],
                "zscore": row.get("zscore", 0),
            })

    if not events:
        return pd.DataFrame()

    events_df = pd.DataFrame(events)
    events_df = events_df.drop_duplicates(subset=["timestamp", "ticker", "event_type"])
    events_df = events_df.sort_values("timestamp").reset_index(drop=True)
    logger.info("Detected %d events across %d tickers", len(events_df), events_df["ticker"].nunique())
    return events_df


# ---------------------------------------------------------------------------
# Forward return computation
# ---------------------------------------------------------------------------

def compute_forward_returns(
    events_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    windows: list[int] = None,
) -> pd.DataFrame:
    """For each event, compute the price return N hours after the event.

    Returns the events DataFrame with additional columns:
        fwd_return_1h, fwd_return_4h, fwd_return_24h
    """
    if windows is None:
        windows = FORWARD_WINDOWS

    prices_df = prices_df.sort_values(["ticker", "timestamp"]).copy()
    result = events_df.copy()

    for window in windows:
        col = f"fwd_return_{window}h"
        result[col] = np.nan

    # Build price lookup per ticker
    price_lookup = {}
    for ticker, group in prices_df.groupby("ticker"):
        g = group.set_index("timestamp").sort_index()
        price_lookup[ticker] = g["close"]

    for idx, event in result.iterrows():
        ticker = event["ticker"]
        event_ts = event["timestamp"]
        if ticker not in price_lookup:
            continue

        closes = price_lookup[ticker]
        # Find closest price at event time
        try:
            # Get price at or just before event
            mask_at = closes.index <= event_ts
            if not mask_at.any():
                continue
            price_at = closes[mask_at].iloc[-1]

            for window in windows:
                target_ts = event_ts + pd.Timedelta(hours=window)
                mask_after = closes.index <= target_ts
                if not mask_after.any():
                    continue
                price_after = closes[mask_after].iloc[-1]

                # Only use if we actually have data near the target time
                actual_ts = closes[mask_after].index[-1]
                gap_hours = (target_ts - actual_ts).total_seconds() / 3600
                if gap_hours <= window * 0.5:  # Allow up to 50% gap tolerance
                    fwd_ret = (price_after - price_at) / price_at
                    result.at[idx, f"fwd_return_{window}h"] = fwd_ret
        except Exception:
            continue

    for window in windows:
        col = f"fwd_return_{window}h"
        filled = result[col].notna().sum()
        logger.info("Forward return %dh: %d/%d filled (%.0f%%)",
                     window, filled, len(result), filled / max(len(result), 1) * 100)

    return result


# ---------------------------------------------------------------------------
# Backtest statistics
# ---------------------------------------------------------------------------

def compute_backtest_stats(events_with_fwd: pd.DataFrame) -> dict:
    """Compute comprehensive backtest statistics from events with forward returns."""
    df = events_with_fwd.copy()
    stats = {}

    # Overall
    stats["total_events"] = len(df)
    stats["date_range"] = f"{df['timestamp'].min()} ~ {df['timestamp'].max()}"
    stats["tickers"] = sorted(df["ticker"].unique().tolist())

    # Per event type
    for event_type in ["surge", "crash", "volume_spike"]:
        subset = df[df["event_type"] == event_type]
        if subset.empty:
            continue

        type_stats = {"count": len(subset)}
        for window in FORWARD_WINDOWS:
            col = f"fwd_return_{window}h"
            valid = subset[col].dropna()
            if len(valid) < 2:
                continue
            type_stats[f"avg_fwd_{window}h"] = valid.mean()
            type_stats[f"median_fwd_{window}h"] = valid.median()
            type_stats[f"win_rate_{window}h"] = (
                (valid > 0).mean() if event_type == "surge"
                else (valid < 0).mean() if event_type == "crash"
                else (valid.abs() > 0.01).mean()
            )
            type_stats[f"sample_{window}h"] = len(valid)

        stats[event_type] = type_stats

    # Per ticker
    ticker_stats = {}
    for ticker, group in df.groupby("ticker"):
        t = {"total_events": len(group)}
        for event_type in ["surge", "crash", "volume_spike"]:
            t[f"{event_type}_count"] = len(group[group["event_type"] == event_type])
        valid_24h = group["fwd_return_24h"].dropna()
        if len(valid_24h) >= 2:
            t["avg_fwd_24h"] = valid_24h.mean()
            t["best_24h"] = valid_24h.max()
            t["worst_24h"] = valid_24h.min()
        ticker_stats[ticker] = t

    stats["per_ticker"] = ticker_stats

    # Severity analysis
    severity_stats = {}
    for severity in ["high", "medium", "low"]:
        subset = df[df["severity"] == severity]
        if subset.empty:
            continue
        valid_24h = subset["fwd_return_24h"].dropna()
        severity_stats[severity] = {
            "count": len(subset),
            "avg_fwd_24h": valid_24h.mean() if len(valid_24h) >= 2 else None,
            "win_rate": (valid_24h.abs() > 0.01).mean() if len(valid_24h) >= 2 else None,
        }
    stats["per_severity"] = severity_stats

    return stats


def print_backtest_report(stats: dict, events_df: pd.DataFrame = None):
    """Pretty-print backtest results."""
    print("\n" + "=" * 70)
    print("  StoryQuant BACKTEST REPORT")
    print("=" * 70)
    print(f"\n  Period: {stats.get('date_range', 'N/A')}")
    print(f"  Total events: {stats.get('total_events', 0)}")
    print(f"  Tickers: {', '.join(stats.get('tickers', []))}")

    # Event type breakdown
    print(f"\n{'─' * 70}")
    print("  EVENT TYPE ANALYSIS")
    print(f"{'─' * 70}")
    for event_type in ["surge", "crash", "volume_spike"]:
        t = stats.get(event_type, {})
        if not t:
            continue
        print(f"\n  [{event_type.upper()}] ({t.get('count', 0)} events)")
        for window in FORWARD_WINDOWS:
            avg = t.get(f"avg_fwd_{window}h")
            wr = t.get(f"win_rate_{window}h")
            n = t.get(f"sample_{window}h", 0)
            if avg is not None:
                print(f"    {window:2d}h forward: avg {avg:+.2%} | win rate {wr:.0%} | n={n}")

    # Per ticker
    print(f"\n{'─' * 70}")
    print("  PER TICKER")
    print(f"{'─' * 70}")
    print(f"  {'Ticker':<12} {'Events':>7} {'Surge':>7} {'Crash':>7} {'VolSpk':>7} {'Avg 24h':>10}")
    for ticker, t in sorted(stats.get("per_ticker", {}).items()):
        avg24 = t.get("avg_fwd_24h")
        avg24_str = f"{avg24:+.2%}" if avg24 is not None else "N/A"
        print(f"  {ticker:<12} {t['total_events']:>7} {t.get('surge_count',0):>7} "
              f"{t.get('crash_count',0):>7} {t.get('volume_spike_count',0):>7} {avg24_str:>10}")

    # Severity
    print(f"\n{'─' * 70}")
    print("  SEVERITY ANALYSIS")
    print(f"{'─' * 70}")
    for sev in ["high", "medium", "low"]:
        s = stats.get("per_severity", {}).get(sev, {})
        if not s:
            continue
        avg24 = s.get("avg_fwd_24h")
        avg24_str = f"{avg24:+.2%}" if avg24 is not None else "N/A"
        wr = s.get("win_rate")
        wr_str = f"{wr:.0%}" if wr is not None else "N/A"
        print(f"  {sev:>8}: {s.get('count',0):>5} events | avg 24h: {avg24_str} | signal rate: {wr_str}")

    # Top signals
    if events_df is not None and "fwd_return_24h" in events_df.columns:
        print(f"\n{'─' * 70}")
        print("  TOP 10 SIGNALS (by 24h forward return)")
        print(f"{'─' * 70}")
        top = events_df.dropna(subset=["fwd_return_24h"]).nlargest(10, "fwd_return_24h")
        for _, row in top.iterrows():
            print(f"  {str(row['timestamp'])[:16]} {row['ticker']:<12} "
                  f"{row['event_type']:<14} {row['return_1h']:+.2%} → 24h: {row['fwd_return_24h']:+.2%}")

        print(f"\n  WORST 10 SIGNALS")
        worst = events_df.dropna(subset=["fwd_return_24h"]).nsmallest(10, "fwd_return_24h")
        for _, row in worst.iterrows():
            print(f"  {str(row['timestamp'])[:16]} {row['ticker']:<12} "
                  f"{row['event_type']:<14} {row['return_1h']:+.2%} → 24h: {row['fwd_return_24h']:+.2%}")

    print(f"\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Save to DB
# ---------------------------------------------------------------------------

def save_backtest_to_db(
    conn: sqlite3.Connection,
    prices_df: pd.DataFrame,
    events_df: pd.DataFrame,
    batch_size: int = 500,
):
    """Save historical prices and events to the StoryQuant database in batches."""
    from src.db.queries import insert_prices, insert_events

    # Save prices in batches
    price_save = prices_df.copy()
    price_save["timestamp"] = price_save["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    price_save["source"] = "yfinance_backtest"
    saved_prices = 0
    for i in range(0, len(price_save), batch_size):
        batch = price_save.iloc[i:i + batch_size]
        try:
            insert_prices(conn, batch)
            saved_prices += len(batch)
        except Exception as exc:
            logger.warning("Price batch %d failed: %s", i, exc)
    logger.info("Saved %d/%d historical price rows to DB", saved_prices, len(price_save))

    # Save events in batches
    event_cols = ["timestamp", "ticker", "event_type", "severity", "return_1h", "volume_ratio", "zscore"]
    event_save = events_df[[c for c in event_cols if c in events_df.columns]].copy()
    event_save["timestamp"] = event_save["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    saved_events = 0
    for i in range(0, len(event_save), batch_size):
        batch = event_save.iloc[i:i + batch_size]
        try:
            insert_events(conn, batch)
            saved_events += len(batch)
        except Exception as exc:
            logger.warning("Event batch %d failed: %s", i, exc)
    logger.info("Saved %d/%d historical events to DB", saved_events, len(event_save))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_backtest(
    start: str = "2024-07-01",
    end: str = None,
    save_to_db: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Run full backtest pipeline and return (events_with_fwd, stats)."""
    # 1. Fetch prices
    prices_df = fetch_historical_prices(start=start, end=end)
    if prices_df.empty:
        logger.error("No price data fetched")
        return pd.DataFrame(), {}

    # 2. Detect events
    events_df = detect_events_backtest(prices_df)
    if events_df.empty:
        logger.error("No events detected")
        return pd.DataFrame(), {}

    # 3. Compute forward returns
    events_with_fwd = compute_forward_returns(events_df, prices_df)

    # 4. Compute stats
    stats = compute_backtest_stats(events_with_fwd)

    # 5. Save to DB
    if save_to_db:
        try:
            from src.db.schema import get_connection, init_db
            conn = get_connection()
            init_db(conn)
            save_backtest_to_db(conn, prices_df, events_df)
            conn.close()
        except Exception as exc:
            logger.warning("Failed to save to DB: %s", exc)

    return events_with_fwd, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    start = "2024-07-01"
    save = "--no-save" not in sys.argv

    print(f"Starting backtest from {start}...")
    events_df, stats = run_backtest(start=start, save_to_db=save)

    if stats:
        print_backtest_report(stats, events_df)

        # Save CSV
        if not events_df.empty:
            csv_path = "data/backtest_events.csv"
            Path("data").mkdir(exist_ok=True)
            events_df.to_csv(csv_path, index=False)
            print(f"\nEvents saved to: {csv_path}")
    else:
        print("Backtest produced no results.")
