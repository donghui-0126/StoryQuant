"""
derivatives.py - Fetch Open Interest and liquidation data from Binance Futures API.

All endpoints are public (no API key required), except forceOrders which
requires auth - that call is handled gracefully with an empty DataFrame fallback.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FUTURES_BASE = "https://fapi.binance.com"
FUTURES_DATA_BASE = "https://fapi.binance.com/futures/data"
FUTURES_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
_TIMEOUT = 10


def _symbol_to_ticker(symbol: str) -> str:
    """Convert Binance symbol to ticker format: BTCUSDT -> BTC-USDT."""
    symbol = symbol.upper()
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB", "USDC"):
        if symbol.endswith(quote):
            base = symbol[: -len(quote)]
            return f"{base}-{quote}"
    return symbol


def fetch_open_interest(symbols: Optional[List[str]] = None) -> pd.DataFrame:
    """Fetch current Open Interest for each symbol.

    Returns DataFrame with columns:
        symbol, ticker, open_interest, oi_value_usd, timestamp
    """
    if symbols is None:
        symbols = FUTURES_SYMBOLS

    rows = []
    for sym in symbols:
        try:
            resp = requests.get(
                f"{FUTURES_BASE}/fapi/v1/openInterest",
                params={"symbol": sym},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            rows.append({
                "symbol": sym,
                "ticker": _symbol_to_ticker(sym),
                "open_interest": float(data.get("openInterest", 0)),
                "oi_value_usd": None,  # snapshot endpoint has no USD value
                "timestamp": datetime.fromtimestamp(
                    data["time"] / 1000, tz=timezone.utc
                ).isoformat(),
            })
        except Exception as exc:
            logger.warning("[derivatives] fetch_open_interest %s failed: %s", sym, exc)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_oi_history(
    symbol: str = "BTCUSDT", period: str = "1h", limit: int = 48
) -> pd.DataFrame:
    """Fetch OI history klines.

    Returns DataFrame with columns:
        symbol, ticker, timestamp, open_interest, oi_value_usd
    """
    try:
        resp = requests.get(
            f"{FUTURES_BASE}/futures/data/openInterestHist",
            params={"symbol": symbol, "period": period, "limit": limit},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[derivatives] fetch_oi_history %s failed: %s", symbol, exc)
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "symbol": symbol,
            "ticker": _symbol_to_ticker(symbol),
            "timestamp": datetime.fromtimestamp(
                item["timestamp"] / 1000, tz=timezone.utc
            ).isoformat(),
            "open_interest": float(item.get("sumOpenInterest", 0)),
            "oi_value_usd": float(item.get("sumOpenInterestValue", 0)),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_long_short_ratio(
    symbol: str = "BTCUSDT", period: str = "1h", limit: int = 48
) -> pd.DataFrame:
    """Fetch long/short account ratio history.

    Returns DataFrame with columns:
        symbol, ticker, timestamp, long_short_ratio, long_pct, short_pct
    """
    try:
        resp = requests.get(
            f"{FUTURES_BASE}/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": period, "limit": limit},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[derivatives] fetch_long_short_ratio %s failed: %s", symbol, exc)
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "symbol": symbol,
            "ticker": _symbol_to_ticker(symbol),
            "timestamp": datetime.fromtimestamp(
                item["timestamp"] / 1000, tz=timezone.utc
            ).isoformat(),
            "long_short_ratio": float(item.get("longShortRatio", 0)),
            "long_pct": float(item.get("longAccount", 0)),
            "short_pct": float(item.get("shortAccount", 0)),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_liquidations(
    symbols: Optional[List[str]] = None, limit: int = 100
) -> pd.DataFrame:
    """Fetch recent liquidation orders via REST API.

    Returns DataFrame with columns:
        symbol, ticker, side, quantity, price, total_usd, timestamp

    If the endpoint returns 401/403 (auth required), returns empty DataFrame.
    """
    if symbols is None:
        symbols = FUTURES_SYMBOLS

    rows = []
    for sym in symbols:
        try:
            resp = requests.get(
                f"{FUTURES_BASE}/fapi/v1/forceOrders",
                params={"symbol": sym, "limit": limit},
                timeout=_TIMEOUT,
            )
            if resp.status_code in (401, 403):
                logger.debug(
                    "[derivatives] forceOrders %s requires auth — skipping", sym
                )
                continue
            resp.raise_for_status()
            data = resp.json()
            for item in data:
                qty = float(item.get("origQty", 0))
                price = float(item.get("price", 0))
                rows.append({
                    "symbol": sym,
                    "ticker": _symbol_to_ticker(sym),
                    "side": item.get("side", ""),
                    "quantity": qty,
                    "price": price,
                    "total_usd": qty * price,
                    "timestamp": datetime.fromtimestamp(
                        item["time"] / 1000, tz=timezone.utc
                    ).isoformat(),
                })
        except Exception as exc:
            logger.warning("[derivatives] fetch_liquidations %s failed: %s", sym, exc)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def detect_oi_events(
    oi_history_df: pd.DataFrame, threshold: float = 0.05
) -> pd.DataFrame:
    """Detect significant OI changes (spikes > threshold pct).

    Returns DataFrame with columns:
        ticker, timestamp, oi_change_pct, event_type, oi_value
    """
    if oi_history_df.empty or "open_interest" not in oi_history_df.columns:
        return pd.DataFrame()

    results = []
    for ticker, grp in oi_history_df.groupby("ticker"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        grp["oi_change_pct"] = grp["open_interest"].pct_change()
        spikes = grp[grp["oi_change_pct"].abs() > threshold]
        for _, row in spikes.iterrows():
            event_type = (
                "oi_spike_up" if row["oi_change_pct"] > 0 else "oi_spike_down"
            )
            results.append({
                "ticker": ticker,
                "timestamp": row["timestamp"],
                "oi_change_pct": row["oi_change_pct"],
                "event_type": event_type,
                "oi_value": row.get("oi_value_usd", row.get("open_interest")),
            })

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)


def detect_liquidation_clusters(
    liq_df: pd.DataFrame, window_minutes: int = 5, min_count: int = 3
) -> pd.DataFrame:
    """Detect liquidation clusters (many liquidations in a short window).

    Returns DataFrame with columns:
        ticker, start_time, end_time, count, total_usd, dominant_side, severity
    """
    if liq_df.empty:
        return pd.DataFrame()

    liq_df = liq_df.copy()
    liq_df["timestamp"] = pd.to_datetime(liq_df["timestamp"], utc=True, errors="coerce")
    liq_df = liq_df.dropna(subset=["timestamp"])

    results = []
    for ticker, grp in liq_df.groupby("ticker"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        window = pd.Timedelta(minutes=window_minutes)
        used = [False] * len(grp)

        for i in range(len(grp)):
            if used[i]:
                continue
            t0 = grp.loc[i, "timestamp"]
            mask = (grp["timestamp"] >= t0) & (grp["timestamp"] <= t0 + window)
            cluster = grp[mask]
            if len(cluster) < min_count:
                continue
            for idx in cluster.index:
                used[idx] = True

            total_usd = cluster["total_usd"].sum()
            dominant_side = cluster["side"].value_counts().idxmax()
            severity = "high" if total_usd > 1_000_000 else "medium" if total_usd > 100_000 else "low"
            results.append({
                "ticker": ticker,
                "start_time": cluster["timestamp"].min().isoformat(),
                "end_time": cluster["timestamp"].max().isoformat(),
                "count": len(cluster),
                "total_usd": total_usd,
                "dominant_side": dominant_side,
                "severity": severity,
            })

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)


def save_derivatives_csv(
    df: pd.DataFrame, data_dir: str = "data/derivatives", prefix: str = "oi"
) -> str:
    """Save DataFrame to a timestamped CSV file. Returns the file path."""
    os.makedirs(data_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(data_dir, f"{prefix}_{ts}.csv")
    df.to_csv(path, index=False)
    return path
