"""
event_detector.py - Detect significant price move events from OHLCV data.
"""

import os
from datetime import datetime

import numpy as np
import pandas as pd


def detect_events(
    price_df: pd.DataFrame,
    return_threshold: float = None,
    volume_threshold: float = 2.0,
    zscore_threshold: float = 2.0,
) -> pd.DataFrame:
    """
    Detect significant price move events from hourly OHLCV data.

    An event is flagged when:
      - |1h_return| > return_threshold  (if provided, fixed threshold)
      - OR |z-score of 1h_return| > zscore_threshold  (dynamic, if return_threshold is None)
      - OR volume > volume_threshold * rolling_24h_avg_volume  (volume spike)

    Args:
        price_df:         DataFrame with columns: ticker, timestamp, open, high,
                          low, close, volume (as returned by fetch_prices).
        return_threshold: Minimum absolute 1h return to flag. If None (default),
                          uses z-score based detection instead.
        volume_threshold: Volume multiplier vs 24h rolling average (default 2x).
        zscore_threshold: Z-score threshold for return events when return_threshold
                          is None (default 2.0 standard deviations).

    Returns:
        DataFrame with columns:
          ticker, timestamp, return_1h, volume_ratio, return_zscore,
          event_type (surge / crash / volume_spike),
          severity (low / medium / high)
    """
    if price_df.empty:
        return pd.DataFrame(
            columns=["ticker", "timestamp", "return_1h", "volume_ratio",
                     "return_zscore", "event_type", "severity"]
        )

    df = price_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    df = df.sort_values(["ticker", "timestamp"]).reset_index(drop=True)

    # --- Per-ticker calculations ---
    df["return_1h"] = df.groupby("ticker")["close"].pct_change()

    # 24-period (24h) rolling average volume, min 1 period to avoid NaN at start
    df["rolling_avg_volume"] = (
        df.groupby("ticker")["volume"]
        .transform(lambda s: s.rolling(window=24, min_periods=1).mean().shift(1))
    )
    df["volume_ratio"] = df["volume"] / df["rolling_avg_volume"].replace(0, np.nan)

    # --- Per-ticker z-score of returns (24h rolling window) ---
    df["return_zscore"] = np.nan
    for ticker in df["ticker"].unique():
        mask = df["ticker"] == ticker
        ticker_df = df[mask].copy()

        ticker_df["return_mean"] = ticker_df["return_1h"].rolling(24, min_periods=3).mean()
        ticker_df["return_std"] = ticker_df["return_1h"].rolling(24, min_periods=3).std()
        ticker_df["return_zscore"] = (
            (ticker_df["return_1h"] - ticker_df["return_mean"])
            / ticker_df["return_std"].clip(lower=0.001)
        )

        # Dynamic vs fixed threshold for price events
        if return_threshold is not None:
            ticker_df["is_return_event"] = ticker_df["return_1h"].abs() > return_threshold
        else:
            ticker_df["is_return_event"] = ticker_df["return_zscore"].abs() > zscore_threshold

        df.loc[mask, "return_zscore"] = ticker_df["return_zscore"]
        df.loc[mask, "is_return_event"] = ticker_df["is_return_event"]

    # --- Event flags ---
    vol_spike = df["volume_ratio"] > volume_threshold
    is_event = df["is_return_event"].fillna(False) | vol_spike

    events = df[is_event].copy()

    if events.empty:
        return pd.DataFrame(
            columns=["ticker", "timestamp", "return_1h", "volume_ratio",
                     "return_zscore", "event_type", "severity"]
        )

    # --- Event type (price takes priority over volume spike) ---
    def classify_type(row):
        if row["is_return_event"] and row["return_1h"] > 0:
            return "surge"
        if row["is_return_event"] and row["return_1h"] < 0:
            return "crash"
        return "volume_spike"

    events["event_type"] = events.apply(classify_type, axis=1)

    # --- Severity based on magnitude ---
    def classify_severity(row):
        abs_ret = abs(row["return_1h"]) if not np.isnan(row["return_1h"]) else 0.0
        vol_r   = row["volume_ratio"]   if not np.isnan(row["volume_ratio"])  else 1.0

        if row["event_type"] in ("surge", "crash"):
            if abs_ret >= 0.10:
                return "high"
            if abs_ret >= 0.05:
                return "medium"
            return "low"
        else:  # volume_spike
            if vol_r >= 5.0:
                return "high"
            if vol_r >= 3.0:
                return "medium"
            return "low"

    events["severity"] = events.apply(classify_severity, axis=1)

    result = (
        events[["ticker", "timestamp", "return_1h", "volume_ratio",
                "return_zscore", "event_type", "severity"]]
        .reset_index(drop=True)
    )
    return result


def save_events_csv(df: pd.DataFrame, data_dir: str = "data/events") -> str:
    """
    Save events DataFrame to a dated CSV file.

    Args:
        df:       DataFrame as returned by detect_events().
        data_dir: Directory to write CSV into (created if absent).

    Returns:
        Absolute path to the saved file.
    """
    os.makedirs(data_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"events_{date_str}.csv"
    path = os.path.join(data_dir, filename)
    df.to_csv(path, index=False)
    print(f"Saved {len(df)} events to {path}")
    return path


if __name__ == "__main__":
    # Quick smoke-test using live data
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    from src.prices.price_fetcher import fetch_prices, get_default_tickers

    tickers_map = get_default_tickers()
    all_tickers = [t for group in tickers_map.values() for t in group]

    print(f"Fetching prices for event detection ({len(all_tickers)} tickers)...")
    price_df = fetch_prices(all_tickers, period="5d", interval="1h")
    print(f"Price rows: {len(price_df)}")

    events = detect_events(price_df, return_threshold=0.02, volume_threshold=2.0)
    print(f"\nDetected {len(events)} events:")
    print(events.to_string(index=False))

    if not events.empty:
        path = save_events_csv(events)
        print(f"\nSaved to: {path}")
