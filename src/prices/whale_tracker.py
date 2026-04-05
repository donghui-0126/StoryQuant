"""
Whale tracking via Arkham Intelligence API and Whale Alert.
Tracks large transfers, exchange inflows/outflows, and notable entity transactions.

API keys are loaded from environment variables:
  ARKHAM_API_KEY - Arkham Intelligence (apply at https://intel.arkm.com/api)
  WHALE_ALERT_API_KEY - Whale Alert (free dev tier at https://whale-alert.io)
"""

import os
import logging
import time
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests

logger = logging.getLogger(__name__)

ARKHAM_BASE = "https://api.arkhamintelligence.com"
WHALE_ALERT_BASE = "https://api.whale-alert.io/v1"

# Notable entities to track
TRACKED_ENTITIES = [
    "binance", "coinbase", "kraken", "bitfinex",
    "jump-trading", "wintermute", "alameda-research",
    "grayscale", "blackrock", "microstrategy",
]

def _get_arkham_key():
    return os.environ.get("ARKHAM_API_KEY", "")

def _get_whale_alert_key():
    return os.environ.get("WHALE_ALERT_API_KEY", "")


# ── Arkham Intelligence ──────────────────────────────────

def arkham_available() -> bool:
    return bool(_get_arkham_key())

def fetch_arkham_whale_transfers(
    entity: str = None,
    flow: str = "all",
    min_usd: int = 1_000_000,
    hours_back: int = 24,
    limit: int = 50,
) -> pd.DataFrame:
    """
    Fetch large transfers from Arkham Intelligence.

    Parameters:
        entity: Arkham entity slug (e.g., 'binance', 'jump-trading') or None for all
        flow: 'in', 'out', or 'all'
        min_usd: minimum USD value filter
        hours_back: time window
        limit: max results

    Returns DataFrame: timestamp, from_entity, from_address, to_entity, to_address,
                        usd_value, token, chain, tx_hash
    """
    key = _get_arkham_key()
    if not key:
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])

    headers = {"API-Key": key}
    params = {
        "flow": flow,
        "usdGte": min_usd,
        "timeLast": f"{hours_back}h" if hours_back <= 24 else f"{hours_back // 24}d",
        "limit": limit,
        "sortKey": "usd",
        "sortDir": "desc",
    }
    if entity:
        params["base"] = entity

    try:
        resp = requests.get(f"{ARKHAM_BASE}/transfers", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Arkham API error: %s", exc)
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])

    rows = []
    for tx in data.get("transfers", []):
        from_addr = tx.get("fromAddress", {})
        to_addr = tx.get("toAddress", {})
        rows.append({
            "timestamp": datetime.fromtimestamp(tx.get("blockTimestamp", 0), tz=timezone.utc).isoformat(timespec="seconds"),
            "from_entity": (from_addr.get("arkhamEntity") or {}).get("name", "Unknown"),
            "from_address": from_addr.get("address", "")[:10] + "...",
            "to_entity": (to_addr.get("arkhamEntity") or {}).get("name", "Unknown"),
            "to_address": to_addr.get("address", "")[:10] + "...",
            "usd_value": tx.get("historicalUSD", 0),
            "token": tx.get("tokenSymbol", tx.get("unitToken", {}).get("symbol", "?")),
            "chain": tx.get("chain", "unknown"),
            "tx_hash": tx.get("transactionHash", "")[:16] + "...",
        })

    return pd.DataFrame(rows)


def fetch_arkham_exchange_flows(
    exchange: str = "binance",
    hours_back: int = 24,
    min_usd: int = 500_000,
) -> dict:
    """
    Get exchange inflows and outflows summary.
    Returns dict: {inflows: DataFrame, outflows: DataFrame, net_flow_usd: float}
    """
    inflows = fetch_arkham_whale_transfers(entity=exchange, flow="in", min_usd=min_usd, hours_back=hours_back)
    time.sleep(1.1)  # Rate limit: 1 req/sec for /transfers
    outflows = fetch_arkham_whale_transfers(entity=exchange, flow="out", min_usd=min_usd, hours_back=hours_back)

    net = 0
    if not inflows.empty:
        net += inflows["usd_value"].sum()
    if not outflows.empty:
        net -= outflows["usd_value"].sum()

    return {"inflows": inflows, "outflows": outflows, "net_flow_usd": net}


def fetch_arkham_notable_movements(hours_back: int = 24, min_usd: int = 5_000_000) -> pd.DataFrame:
    """Fetch large movements from tracked entities (funds, institutions)."""
    all_transfers = []
    for entity in TRACKED_ENTITIES[:5]:  # Limit to avoid rate limits
        df = fetch_arkham_whale_transfers(entity=entity, min_usd=min_usd, hours_back=hours_back, limit=10)
        if not df.empty:
            all_transfers.append(df)
        time.sleep(1.1)

    if not all_transfers:
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])
    return pd.concat(all_transfers, ignore_index=True).sort_values("usd_value", ascending=False)


# ── Whale Alert (Free Fallback) ──────────────────────────

def whale_alert_available() -> bool:
    return bool(_get_whale_alert_key())

def fetch_whale_alert_transfers(min_usd: int = 1_000_000, hours_back: int = 1) -> pd.DataFrame:
    """
    Fetch recent large transfers from Whale Alert API.
    Free tier: last 1 hour, 10 req/min.

    Returns DataFrame: timestamp, from_entity, to_entity, usd_value, token, chain, tx_hash
    """
    key = _get_whale_alert_key()
    if not key:
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])

    start = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
    params = {
        "api_key": key,
        "min_value": min_usd,
        "start": start,
        "cursor": "",
    }

    try:
        resp = requests.get(f"{WHALE_ALERT_BASE}/transactions", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Whale Alert API error: %s", exc)
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])

    if data.get("result") != "success":
        logger.warning("Whale Alert returned: %s", data.get("message", "unknown error"))
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])

    rows = []
    for tx in data.get("transactions", []):
        rows.append({
            "timestamp": datetime.fromtimestamp(tx.get("timestamp", 0), tz=timezone.utc).isoformat(timespec="seconds"),
            "from_entity": tx.get("from", {}).get("owner", "Unknown"),
            "from_address": (tx.get("from", {}).get("address", "") or "")[:10] + "...",
            "to_entity": tx.get("to", {}).get("owner", "Unknown"),
            "to_address": (tx.get("to", {}).get("address", "") or "")[:10] + "...",
            "usd_value": tx.get("amount_usd", 0),
            "token": tx.get("symbol", "?").upper(),
            "chain": tx.get("blockchain", "unknown"),
            "tx_hash": (tx.get("hash", "") or "")[:16] + "...",
        })

    return pd.DataFrame(rows)


# ── Unified Interface ────────────────────────────────────

def fetch_whale_movements(min_usd: int = 1_000_000, hours_back: int = 24) -> pd.DataFrame:
    """
    Unified whale movement fetcher. Uses Arkham if key available, else Whale Alert.
    """
    if arkham_available():
        logger.info("Using Arkham Intelligence for whale tracking")
        return fetch_arkham_whale_transfers(min_usd=min_usd, hours_back=hours_back, limit=100)
    elif whale_alert_available():
        logger.info("Using Whale Alert for whale tracking")
        return fetch_whale_alert_transfers(min_usd=min_usd, hours_back=min(hours_back, 1))
    else:
        logger.info("No whale tracking API key configured. Set ARKHAM_API_KEY or WHALE_ALERT_API_KEY")
        return pd.DataFrame(columns=["timestamp","from_entity","from_address","to_entity","to_address","usd_value","token","chain","tx_hash"])


def get_whale_summary() -> dict:
    """Get a summary of available whale tracking capabilities."""
    return {
        "arkham_available": arkham_available(),
        "whale_alert_available": whale_alert_available(),
        "provider": "Arkham" if arkham_available() else ("Whale Alert" if whale_alert_available() else "None"),
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    summary = get_whale_summary()
    print(f"Arkham Intelligence available: {summary['arkham_available']}")
    print(f"Whale Alert available:         {summary['whale_alert_available']}")
    print(f"Active provider:               {summary['provider']}")
    print()

    if summary["arkham_available"]:
        print("Fetching whale transfers from Arkham Intelligence (last 24h, min $1M)...")
        df = fetch_arkham_whale_transfers(min_usd=1_000_000, hours_back=24, limit=10)
        if df.empty:
            print("  No transfers returned (check API key permissions or try again later).")
        else:
            print(df.to_string(index=False))

    if summary["whale_alert_available"]:
        print("Fetching whale transfers from Whale Alert (last 1h, min $1M)...")
        df = fetch_whale_alert_transfers(min_usd=1_000_000, hours_back=1)
        if df.empty:
            print("  No transfers returned (check API key or free tier limits).")
        else:
            print(df.to_string(index=False))

    if not summary["arkham_available"] and not summary["whale_alert_available"]:
        print("No whale tracking API keys configured.")
        print()
        print("To enable whale tracking, set one of the following environment variables:")
        print()
        print("  Arkham Intelligence (recommended — entity labels, exchange flows):")
        print("    1. Apply for API access at https://intel.arkm.com/api")
        print("    2. export ARKHAM_API_KEY=your_key_here")
        print()
        print("  Whale Alert (free fallback — last 1h, basic tx data):")
        print("    1. Sign up at https://whale-alert.io")
        print("    2. export WHALE_ALERT_API_KEY=your_key_here")
        sys.exit(0)
