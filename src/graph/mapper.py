"""
Maps StoryQuant data structures to amure-db graph nodes and edges.

Concept mapping:
  News Article   → Evidence node
  Price Event    → Fact node
  Topic/Narrative → Claim node
  Attribution    → Support edge (Evidence → Fact)
  Causal link    → Reason node + Support edges
  Cross-market   → DependsOn edge (Fact → Fact)
  Whale transfer → Evidence node (if ≥ $10M)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.graph.client import AmureClient
from src.config.tickers import TICKERS, get_sector
from src.config.settings import WHALE_TRANSFER_EVIDENCE_MIN_USD

logger = logging.getLogger(__name__)


def article_to_evidence(client: AmureClient, row: dict) -> Optional[str]:
    """Convert a news article dict/row into an Evidence node."""
    title = row.get("title", "")
    if not title:
        return None

    summary = row.get("summary", "")
    source = row.get("source", "unknown")
    url = row.get("url", "")
    market = row.get("market", "")
    published_at = row.get("published_at", "")

    keywords = _extract_keywords_from_text(f"{title} {summary}", market)

    metadata = {
        "source": source,
        "source_type": row.get("source_type", "news"),
        "url": url,
        "market": market,
        "published_at": str(published_at),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    sentiment = row.get("sentiment")
    if sentiment:
        metadata["sentiment"] = sentiment
        metadata["sentiment_score"] = row.get("sentiment_score", 0.0)

    return client.create_node(
        kind="Evidence",
        statement=title if not summary else f"{title} — {summary[:200]}",
        keywords=keywords,
        metadata=metadata,
        status="Active",
    )


def event_to_fact(client: AmureClient, row: dict) -> Optional[str]:
    """Convert a price event dict/row into a Fact node."""
    ticker = row.get("ticker", "")
    event_type = row.get("event_type", "")
    return_1h = row.get("return_1h", 0.0)
    timestamp = row.get("timestamp", "")

    if not ticker or not event_type:
        return None

    ticker_cfg = TICKERS.get(ticker, {})
    name = ticker_cfg.get("name", ticker)
    market = ticker_cfg.get("market", "")
    sector = ticker_cfg.get("sector", "")

    direction = "상승" if return_1h > 0 else "하락"
    pct = abs(return_1h * 100) if return_1h else 0

    statement = f"{name} ({ticker}) {pct:.1f}% {direction} at {timestamp}"

    keywords = [
        ticker.lower().replace("-usd", ""),
        event_type,
        market,
    ]
    keywords.extend(ticker_cfg.get("keywords", []))
    if sector:
        keywords.append(sector.lower())

    metadata = {
        "ticker": ticker,
        "return_1h": float(return_1h) if return_1h else 0.0,
        "volume_ratio": float(row.get("volume_ratio", 0.0)),
        "event_type": event_type,
        "severity": row.get("severity", "low"),
        "market": market,
        "sector": sector,
        "timestamp": str(timestamp),
        "attributed": False,
    }

    return client.create_node(
        kind="Fact",
        statement=statement,
        keywords=list(set(keywords)),
        metadata=metadata,
        status="Active",
    )


def whale_to_evidence(client: AmureClient, row: dict) -> Optional[str]:
    """Convert a large whale transfer into an Evidence node."""
    usd_value = row.get("usd_value", 0)
    if usd_value < WHALE_TRANSFER_EVIDENCE_MIN_USD:
        return None

    from_entity = row.get("from_entity", "unknown")
    to_entity = row.get("to_entity", "unknown")
    token = row.get("token", "")
    chain = row.get("chain", "")
    usd_m = usd_value / 1_000_000

    statement = f"${usd_m:.0f}M {token} transfer: {from_entity} → {to_entity}"

    keywords = ["whale", "transfer", token.lower()]
    if from_entity and from_entity != "unknown":
        keywords.append(from_entity.lower())
    if to_entity and to_entity != "unknown":
        keywords.append(to_entity.lower())

    metadata = {
        "source_type": "whale",
        "usd_value": usd_value,
        "token": token,
        "chain": chain,
        "from_entity": from_entity,
        "to_entity": to_entity,
        "tx_hash": row.get("tx_hash", ""),
        "timestamp": str(row.get("timestamp", "")),
    }

    return client.create_node(
        kind="Evidence",
        statement=statement,
        keywords=list(set(keywords)),
        metadata=metadata,
        status="Active",
    )


def narrative_to_claim(
    client: AmureClient,
    label: str,
    keywords: list[str],
    market: str = "",
    direction: str = "",
    evidence_count: int = 0,
) -> Optional[str]:
    """Create or find a Claim node for a market narrative."""
    metadata = {
        "market": market,
        "direction": direction,
        "evidence_count": evidence_count,
        "lifecycle": "emerging",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return client.create_node(
        kind="Claim",
        statement=label,
        keywords=keywords,
        metadata=metadata,
        status="Draft",
    )


def ingest_articles_to_graph(
    client: AmureClient,
    articles_df: pd.DataFrame,
) -> dict:
    """Bulk ingest articles DataFrame into graph as Evidence nodes."""
    created = 0
    failed = 0
    for _, row in articles_df.iterrows():
        node_id = article_to_evidence(client, row.to_dict())
        if node_id:
            created += 1
        else:
            failed += 1

    logger.info("Ingested %d articles as Evidence nodes (%d failed)", created, failed)
    return {"created": created, "failed": failed}


def ingest_events_to_graph(
    client: AmureClient,
    events_df: pd.DataFrame,
) -> dict:
    """Bulk ingest price events DataFrame into graph as Fact nodes."""
    created = 0
    failed = 0
    node_ids = []
    for _, row in events_df.iterrows():
        node_id = event_to_fact(client, row.to_dict())
        if node_id:
            created += 1
            node_ids.append(node_id)
        else:
            failed += 1

    logger.info("Ingested %d events as Fact nodes (%d failed)", created, failed)
    return {"created": created, "failed": failed, "node_ids": node_ids}


def ingest_whales_to_graph(
    client: AmureClient,
    whales_df: pd.DataFrame,
) -> dict:
    """Ingest large whale transfers as Evidence nodes."""
    created = 0
    skipped = 0
    for _, row in whales_df.iterrows():
        node_id = whale_to_evidence(client, row.to_dict())
        if node_id:
            created += 1
        else:
            skipped += 1

    logger.info("Ingested %d whale transfers as Evidence (%d skipped)", created, skipped)
    return {"created": created, "skipped": skipped}


# ── Internal helpers ──

def _extract_keywords_from_text(text: str, market: str = "") -> list[str]:
    """Extract relevant keywords from article text by matching against known tickers."""
    text_lower = text.lower()
    keywords = []

    for ticker, cfg in TICKERS.items():
        for kw in cfg.get("keywords", []):
            if kw.lower() in text_lower:
                keywords.append(ticker.lower().replace("-usd", ""))
                keywords.extend(cfg.get("keywords", [])[:2])
                if cfg.get("sector"):
                    keywords.append(cfg["sector"].lower())
                break

    if market:
        keywords.append(market)

    return list(set(keywords))[:20]
