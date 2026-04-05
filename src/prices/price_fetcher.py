"""
price_fetcher.py - Fetch OHLCV price data for crypto, US stocks, and Korean stocks.
"""

import os
from datetime import datetime

import pandas as pd
import yfinance as yf

from src.config.tickers import get_price_tickers


def get_default_tickers() -> dict[str, list[str]]:
    """Return a mapping of market name to list of tickers."""
    return get_price_tickers()


def fetch_prices(
    tickers: list[str], period: str = "5d", interval: str = "1h"
) -> pd.DataFrame:
    """
    Fetch OHLCV price data for the given tickers.

    Args:
        tickers: List of ticker symbols (e.g. ["BTC-USD", "NVDA"]).
        period:   yfinance period string (e.g. "5d", "1mo").
        interval: yfinance interval string (e.g. "1h", "1d").

    Returns:
        DataFrame with columns: ticker, timestamp, open, high, low, close, volume.
    """
    if not tickers:
        return pd.DataFrame(columns=["ticker", "timestamp", "open", "high", "low", "close", "volume"])

    raw = yf.download(
        tickers=tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    frames = []

    if len(tickers) == 1:
        # Single ticker: raw has flat columns (Open, High, Low, Close, Volume)
        df = raw.copy()
        df.columns = [c.lower() for c in df.columns]
        df = df.reset_index().rename(columns={"Datetime": "timestamp", "Date": "timestamp"})
        df["ticker"] = tickers[0]
        df = df[["ticker", "timestamp", "open", "high", "low", "close", "volume"]]
        df = df.dropna(subset=["close"])
        frames.append(df)
    else:
        for ticker in tickers:
            if ticker not in raw.columns.get_level_values(0):
                print(f"Warning: no data returned for {ticker}")
                continue
            df = raw[ticker].copy()
            df.columns = [c.lower() for c in df.columns]
            df = df.reset_index().rename(columns={"Datetime": "timestamp", "Date": "timestamp"})
            df["ticker"] = ticker
            df = df[["ticker", "timestamp", "open", "high", "low", "close", "volume"]]
            df = df.dropna(subset=["close"])
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["ticker", "timestamp", "open", "high", "low", "close", "volume"])

    result = pd.concat(frames, ignore_index=True)
    result["timestamp"] = pd.to_datetime(result["timestamp"])
    result = result.sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    return result


def save_prices_csv(df: pd.DataFrame, data_dir: str = "data/prices") -> str:
    """
    Save price DataFrame to a dated CSV file.

    Args:
        df:       DataFrame as returned by fetch_prices().
        data_dir: Directory to write CSV into (created if absent).

    Returns:
        Absolute path to the saved file.
    """
    os.makedirs(data_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"prices_{date_str}.csv"
    path = os.path.join(data_dir, filename)
    df.to_csv(path, index=False)
    print(f"Saved {len(df)} rows to {path}")
    return path


if __name__ == "__main__":
    tickers_map = get_default_tickers()
    all_tickers = [t for group in tickers_map.values() for t in group]

    print(f"Fetching prices for {len(all_tickers)} tickers...")
    df = fetch_prices(all_tickers, period="5d", interval="1h")
    print(df.head(10))
    print(f"\nShape: {df.shape}")
    print(f"Tickers in result: {df['ticker'].unique().tolist()}")

    path = save_prices_csv(df)
    print(f"Saved to: {path}")
