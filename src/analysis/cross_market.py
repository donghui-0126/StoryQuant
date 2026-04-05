"""
cross_market.py - Cross-market signal detection for StoryQuant.

Detects lead-lag relationships between events across crypto, US stocks,
and Korean stocks. Examples:
  - NVDA surge -> SK Hynix follows (US AI news -> KR semiconductor)
  - BTC crash  -> risk-off across all markets
  - Fed/macro news -> multi-asset impact

Public API
----------
detect_cross_market_signals(conn, hours=48)
    Real-time: events in one market followed by moves in another within 1-24h.

compute_cross_market_correlations(conn, lookback_days=90)
    Historical: lead-lag correlation strength per ticker pair.

generate_cross_market_report(conn)
    Human-readable dict combining both views.

format_cross_market_alert(signal)
    Telegram-ready string for a single signal row.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market map
# ---------------------------------------------------------------------------

MARKET_MAP: dict[str, str] = {
    "BTC-USD":   "crypto",
    "ETH-USD":   "crypto",
    "SOL-USD":   "crypto",
    "BTC-USDT":  "crypto",
    "ETH-USDT":  "crypto",
    "SOL-USDT":  "crypto",
    "NVDA":      "us",
    "AAPL":      "us",
    "TSLA":      "us",
    "SPY":       "us",
    "005930.KS": "kr",
    "000660.KS": "kr",
    "035420.KS": "kr",
}

# Ticker display names for reports
_DISPLAY: dict[str, str] = {
    "BTC-USD":   "Bitcoin",
    "ETH-USD":   "Ethereum",
    "SOL-USD":   "Solana",
    "BTC-USDT":  "Bitcoin",
    "ETH-USDT":  "Ethereum",
    "SOL-USDT":  "Solana",
    "NVDA":      "NVDA",
    "AAPL":      "AAPL",
    "TSLA":      "TSLA",
    "SPY":       "SPY",
    "005930.KS": "Samsung",
    "000660.KS": "SK Hynix",
    "035420.KS": "Naver",
}

# Output column contracts
_SIGNAL_COLS = [
    "source_ticker", "source_event", "source_return",
    "target_ticker", "target_event", "target_return",
    "lag_hours",
]
_CORR_COLS = [
    "leader", "follower", "correlation",
    "avg_lag_hours", "avg_follower_return", "sample_count",
]

# Cross-market lag window to search (hours)
_MIN_LAG = 1
_MAX_LAG = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_events(conn: sqlite3.Connection, cutoff_iso: str) -> pd.DataFrame:
    """Load events at or after cutoff, keeping only known tickers."""
    sql = """
        SELECT id, ticker, timestamp, event_type, severity, return_1h
        FROM events
        WHERE timestamp >= :cutoff
        ORDER BY timestamp
    """
    try:
        df = pd.read_sql_query(sql, conn, params={"cutoff": cutoff_iso})
    except Exception as exc:
        logger.warning("_load_events query failed: %s", exc)
        return pd.DataFrame()

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df[df["ticker"].isin(MARKET_MAP)]
    df["market"] = df["ticker"].map(MARKET_MAP)
    return df.reset_index(drop=True)


def _return_sign(r: float) -> str:
    if r > 0.01:
        return "surge"
    if r < -0.01:
        return "crash"
    return "flat"


# ---------------------------------------------------------------------------
# 1. Real-time cross-market signal detection
# ---------------------------------------------------------------------------

def detect_cross_market_signals(
    conn: sqlite3.Connection,
    hours: int = 48,
) -> pd.DataFrame:
    """
    Find cases where an event in one market is followed by a move in another
    market within _MIN_LAG.._MAX_LAG hours.

    Parameters
    ----------
    conn : sqlite3.Connection
    hours : int
        Look-back window for source events.

    Returns
    -------
    pd.DataFrame
        Columns: source_ticker, source_event, source_return,
                 target_ticker, target_event, target_return, lag_hours
        Sorted by abs(target_return) descending. Empty DataFrame if no data.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    events = _load_events(conn, cutoff)

    if events.empty or len(events["market"].unique()) < 2:
        return pd.DataFrame(columns=_SIGNAL_COLS)

    records = []
    for _, src in events.iterrows():
        src_market = src["market"]
        src_ts = src["timestamp"]
        src_ret = src["return_1h"] if src["return_1h"] is not None else 0.0

        # Only propagate significant moves (|return| > 1%)
        if abs(src_ret) < 0.01:
            continue

        window_start = src_ts + timedelta(hours=_MIN_LAG)
        window_end   = src_ts + timedelta(hours=_MAX_LAG)

        # Find events in *different* markets within the lag window
        mask = (
            (events["market"] != src_market) &
            (events["timestamp"] >= window_start) &
            (events["timestamp"] <= window_end)
        )
        targets = events[mask]

        for _, tgt in targets.iterrows():
            tgt_ret = tgt["return_1h"] if tgt["return_1h"] is not None else 0.0
            lag_h = (tgt["timestamp"] - src_ts).total_seconds() / 3600.0
            records.append({
                "source_ticker": src["ticker"],
                "source_event":  src["event_type"],
                "source_return": round(float(src_ret), 4),
                "target_ticker": tgt["ticker"],
                "target_event":  tgt["event_type"],
                "target_return": round(float(tgt_ret), 4),
                "lag_hours":     round(lag_h, 1),
            })

    if not records:
        return pd.DataFrame(columns=_SIGNAL_COLS)

    df = pd.DataFrame(records)[_SIGNAL_COLS]
    df = df.sort_values("target_return", key=abs, ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. Historical cross-market correlation (lead-lag)
# ---------------------------------------------------------------------------

def compute_cross_market_correlations(
    conn: sqlite3.Connection,
    lookback_days: int = 90,
) -> pd.DataFrame:
    """
    For each ordered (leader, follower) pair from *different* markets,
    compute lead-lag correlation across lags 1..12h and keep the best lag.

    Uses hourly price returns as the signal source (more stable than event
    counts over a 90-day window).

    Returns
    -------
    pd.DataFrame
        Columns: leader, follower, correlation, avg_lag_hours,
                 avg_follower_return, sample_count
        Only pairs with |correlation| >= 0.15 and sample_count >= 10.
        Sorted by abs(correlation) descending.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat()

    sql = """
        SELECT ticker, timestamp, close
        FROM prices
        WHERE timestamp >= :cutoff
        ORDER BY ticker, timestamp
    """
    try:
        prices = pd.read_sql_query(sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("compute_cross_market_correlations query failed: %s", exc)
        return pd.DataFrame(columns=_CORR_COLS)

    if prices.empty:
        return pd.DataFrame(columns=_CORR_COLS)

    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce")
    prices = prices.dropna(subset=["timestamp", "close"])
    prices = prices[prices["ticker"].isin(MARKET_MAP)]

    # Build wide hourly-return matrix
    pieces = []
    for ticker, grp in prices.groupby("ticker"):
        ts = grp.set_index("timestamp")["close"].sort_index()
        ts_1h = ts.resample("1h").last().dropna()
        if len(ts_1h) < 10:
            continue
        ret = ts_1h.pct_change().dropna()
        ret.name = ticker
        pieces.append(ret)

    if len(pieces) < 2:
        return pd.DataFrame(columns=_CORR_COLS)

    wide = pd.concat(pieces, axis=1, join="outer")
    tickers = wide.columns.tolist()

    # Also load events for avg_follower_return
    events_cutoff = cutoff
    events_sql = """
        SELECT ticker, timestamp, return_1h
        FROM events
        WHERE timestamp >= :cutoff
    """
    try:
        evdf = pd.read_sql_query(events_sql, conn, params={"cutoff": events_cutoff})
        evdf["timestamp"] = pd.to_datetime(evdf["timestamp"], utc=True, errors="coerce")
        evdf = evdf.dropna(subset=["timestamp"])
        evdf = evdf[evdf["ticker"].isin(MARKET_MAP)]
    except Exception:
        evdf = pd.DataFrame(columns=["ticker", "timestamp", "return_1h"])

    records = []
    for leader in tickers:
        for follower in tickers:
            if leader == follower:
                continue
            # Only cross-market pairs
            if MARKET_MAP.get(leader) == MARKET_MAP.get(follower):
                continue

            # Find best lag (1..12h) by abs(correlation)
            best_corr = 0.0
            best_lag = 1
            for lag in range(1, 13):
                x = wide[leader].dropna()
                y = wide[follower].dropna()
                # Align on overlapping index with lag shift
                aligned = pd.DataFrame({"x": x, "y": y.shift(-lag)}).dropna()
                if len(aligned) < 10:
                    continue
                c = float(np.corrcoef(aligned["x"].values, aligned["y"].values)[0, 1])
                if np.isnan(c):
                    continue
                if abs(c) > abs(best_corr):
                    best_corr = c
                    best_lag = lag

            if abs(best_corr) < 0.15:
                continue

            # avg_follower_return: mean return_1h of follower events
            foll_events = evdf[evdf["ticker"] == follower]["return_1h"].dropna()
            avg_foll_ret = float(foll_events.mean()) if len(foll_events) else 0.0
            sample_count = int(
                pd.DataFrame({
                    "x": wide[leader],
                    "y": wide[follower].shift(-best_lag),
                }).dropna().shape[0]
            )

            records.append({
                "leader":             leader,
                "follower":           follower,
                "correlation":        round(best_corr, 4),
                "avg_lag_hours":      float(best_lag),
                "avg_follower_return": round(avg_foll_ret, 4),
                "sample_count":       sample_count,
            })

    if not records:
        return pd.DataFrame(columns=_CORR_COLS)

    df = pd.DataFrame(records)[_CORR_COLS]
    df = df[df["sample_count"] >= 10]
    df = df.sort_values("correlation", key=abs, ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 3. Human-readable report
# ---------------------------------------------------------------------------

def generate_cross_market_report(conn: sqlite3.Connection) -> dict:
    """
    Combine real-time signals and historical patterns into a report dict.

    Returns
    -------
    dict with keys:
        "signals"      : pd.DataFrame  (recent cross-market events)
        "correlations" : pd.DataFrame  (historical lead-lag pairs)
        "summary"      : str           (plain-text narrative)
    """
    logger.info("Generating cross-market report...")

    signals = detect_cross_market_signals(conn, hours=48)
    correlations = compute_cross_market_correlations(conn, lookback_days=90)

    lines = ["=== Cross-Market Signal Report ===", ""]

    # --- Recent signals ---
    lines.append(f"[Real-time signals, last 48h]  {len(signals)} detected")
    if not signals.empty:
        top = signals.head(10)
        for _, row in top.iterrows():
            src_name = _DISPLAY.get(row["source_ticker"], row["source_ticker"])
            tgt_name = _DISPLAY.get(row["target_ticker"], row["target_ticker"])
            src_ret_pct = row["source_return"] * 100
            tgt_ret_pct = row["target_return"] * 100
            lines.append(
                f"  {src_name} ({row['source_event']}, {src_ret_pct:+.1f}%)"
                f" -> {tgt_name} ({row['target_event']}, {tgt_ret_pct:+.1f}%)"
                f"  [lag {row['lag_hours']:.0f}h]"
            )
    else:
        lines.append("  (no significant cross-market signals in window)")

    lines.append("")

    # --- Historical correlations ---
    lines.append(f"[Historical lead-lag, 90d]  {len(correlations)} pairs")
    if not correlations.empty:
        top_c = correlations.head(10)
        for _, row in top_c.iterrows():
            ldr = _DISPLAY.get(row["leader"], row["leader"])
            flw = _DISPLAY.get(row["follower"], row["follower"])
            lines.append(
                f"  {ldr} leads {flw}"
                f"  corr={row['correlation']:+.3f}"
                f"  lag~{row['avg_lag_hours']:.0f}h"
                f"  n={row['sample_count']}"
            )
    else:
        lines.append("  (insufficient data for historical analysis)")

    lines.append("")

    # --- Narrative summary ---
    narrative_parts = []
    if not signals.empty:
        biggest = signals.iloc[0]
        src_name = _DISPLAY.get(biggest["source_ticker"], biggest["source_ticker"])
        tgt_name = _DISPLAY.get(biggest["target_ticker"], biggest["target_ticker"])
        src_mkt = MARKET_MAP.get(biggest["source_ticker"], "")
        tgt_mkt = MARKET_MAP.get(biggest["target_ticker"], "")
        narrative_parts.append(
            f"Strongest recent signal: {src_name} ({src_mkt}) "
            f"-> {tgt_name} ({tgt_mkt}), "
            f"lag {biggest['lag_hours']:.0f}h, "
            f"target return {biggest['target_return']*100:+.1f}%."
        )
    if not correlations.empty:
        top_pair = correlations.iloc[0]
        ldr = _DISPLAY.get(top_pair["leader"], top_pair["leader"])
        flw = _DISPLAY.get(top_pair["follower"], top_pair["follower"])
        narrative_parts.append(
            f"Strongest historical pair: {ldr} leads {flw} "
            f"(corr={top_pair['correlation']:+.3f}, ~{top_pair['avg_lag_hours']:.0f}h lag)."
        )

    summary = "  ".join(narrative_parts) if narrative_parts else "No cross-market patterns detected."
    lines.append("Summary: " + summary)

    for key, df in [("signals", signals), ("correlations", correlations)]:
        logger.info("  %s: %d rows", key, len(df))

    return {
        "signals":      signals,
        "correlations": correlations,
        "summary":      "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# 4. Telegram alert formatter
# ---------------------------------------------------------------------------

def format_cross_market_alert(signal: dict | pd.Series) -> str:
    """
    Format a single signal row as a Telegram-ready message.

    Parameters
    ----------
    signal : dict or pd.Series
        Must have keys: source_ticker, source_event, source_return,
                        target_ticker, target_event, target_return, lag_hours

    Returns
    -------
    str
        Multi-line Telegram message (plain text, no HTML/Markdown).
    """
    src = signal["source_ticker"]
    tgt = signal["target_ticker"]
    src_name = _DISPLAY.get(src, src)
    tgt_name = _DISPLAY.get(tgt, tgt)
    src_mkt = MARKET_MAP.get(src, "?").upper()
    tgt_mkt = MARKET_MAP.get(tgt, "?").upper()
    src_ret_pct = float(signal["source_return"]) * 100
    tgt_ret_pct = float(signal["target_return"]) * 100
    lag = float(signal["lag_hours"])

    sign_src = "+" if src_ret_pct >= 0 else ""
    sign_tgt = "+" if tgt_ret_pct >= 0 else ""

    direction = "BULLISH" if tgt_ret_pct > 0 else "BEARISH"
    emoji = "green_circle" if tgt_ret_pct > 0 else "red_circle"

    lines = [
        f"[Cross-Market Signal] [{emoji}] {direction}",
        f"",
        f"Source  : {src_name} ({src_mkt}) - {signal['source_event']} {sign_src}{src_ret_pct:.1f}%",
        f"Target  : {tgt_name} ({tgt_mkt}) - {signal['target_event']} {sign_tgt}{tgt_ret_pct:.1f}%",
        f"Lag     : ~{lag:.0f}h",
        f"",
        f"Pattern : {src_mkt} event --> {tgt_mkt} reaction",
    ]
    return "\n".join(lines)


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
        sys.exit(1)

    _conn = sqlite3.connect(db_path)
    _conn.execute("PRAGMA journal_mode=WAL")

    report = generate_cross_market_report(_conn)
    print(report["summary"])

    if not report["signals"].empty:
        print("\n--- Top signal alert preview ---")
        top_signal = report["signals"].iloc[0].to_dict()
        print(format_cross_market_alert(top_signal))

    _conn.close()
