"""
RAG-based attribution engine.
Replaces the old rule-based 4-factor mapper with amure-db graph search.

Flow:
  1. For each un-attributed Fact (price event), build a query string
  2. Call amure-db RAG search (token match + synonym + BFS + MMR)
  3. Apply time proximity decay to RAG scores
  4. Create Support edges from matching Evidence → Fact
  5. Synthesize a Reason node for high-confidence clusters
"""
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.graph.client import AmureClient, SearchResult
from src.config.tickers import TICKERS
from src.config.settings import ATTRIBUTION_TOP_K, ATTRIBUTION_TIME_DECAY_HOURS

logger = logging.getLogger(__name__)


def attribute_event(
    client: AmureClient,
    fact_node_id: str,
    top_k: int = None,
) -> dict:
    """
    Run RAG-based attribution for a single Fact (price event) node.

    Returns:
        {"edges_created": int, "reason_id": str|None, "top_match": str|None}
    """
    top_k = top_k or ATTRIBUTION_TOP_K

    fact = client.get_node(fact_node_id)
    if not fact:
        return {"edges_created": 0, "reason_id": None, "top_match": None}

    node_data = fact.get("node", fact)
    metadata = node_data.get("metadata", {})
    ticker = metadata.get("ticker", "")
    event_type = metadata.get("event_type", "")
    event_ts = metadata.get("timestamp", "")

    query = _build_attribution_query(ticker, event_type, metadata)

    results = client.search(query, top_k=top_k * 2)

    if not results:
        return {"edges_created": 0, "reason_id": None, "top_match": None}

    evidence_results = [r for r in results if r.kind == "Evidence"]

    scored = _apply_time_decay(evidence_results, event_ts)

    scored.sort(key=lambda x: x[1], reverse=True)
    top_results = scored[:top_k]

    edges_created = 0
    for result, final_score in top_results:
        if final_score < 0.05:
            continue
        confidence = "high" if final_score >= 0.6 else ("medium" if final_score >= 0.3 else "low")
        edge_id = client.create_edge(
            source=result.node_id,
            target=fact_node_id,
            kind="Support",
            weight=final_score,
            note=f"confidence={confidence}, rag_score={result.score:.3f}",
        )
        if edge_id:
            edges_created += 1

    reason_id = None
    if top_results and top_results[0][1] >= 0.5:
        reason_id = _synthesize_reason(client, fact_node_id, top_results[:3], metadata)

    client.update_node(fact_node_id, metadata={**metadata, "attributed": True})

    top_match = top_results[0][0].statement if top_results else None

    logger.info(
        "Attributed event %s: %d edges, top='%s'",
        fact_node_id[:8], edges_created, (top_match or "")[:60],
    )

    return {
        "edges_created": edges_created,
        "reason_id": reason_id,
        "top_match": top_match,
    }


def attribute_unprocessed_events(client: AmureClient) -> dict:
    """
    Find all Fact nodes that haven't been attributed yet and run attribution.
    """
    unattributed = client.get_unattributed_facts()

    total_edges = 0
    total_reasons = 0
    for node in unattributed:
        node_id = node.get("id", "")
        if not node_id:
            continue
        result = attribute_event(client, node_id)
        total_edges += result["edges_created"]
        if result["reason_id"]:
            total_reasons += 1

    logger.info(
        "Attribution batch: %d events processed, %d edges, %d reasons",
        len(unattributed), total_edges, total_reasons,
    )
    return {
        "events_processed": len(unattributed),
        "edges_created": total_edges,
        "reasons_created": total_reasons,
    }


# ── Internal helpers ──

def _build_attribution_query(ticker: str, event_type: str, metadata: dict) -> str:
    """Build a search query string from event metadata."""
    parts = []

    ticker_cfg = TICKERS.get(ticker, {})
    if ticker_cfg:
        parts.append(ticker_cfg.get("name", ticker))
        parts.extend(ticker_cfg.get("keywords", [])[:2])
        if ticker_cfg.get("sector"):
            parts.append(ticker_cfg["sector"])
    else:
        parts.append(ticker)

    if event_type in ("surge", "crash"):
        parts.append(event_type)
    market = metadata.get("market", "")
    if market:
        parts.append(market)

    return " ".join(parts)


def _apply_time_decay(
    results: list[SearchResult],
    event_ts: str,
) -> list[tuple[SearchResult, float]]:
    """Apply exponential time decay to RAG scores based on news freshness.

    Formula: final_score = rag_score * exp(-hours_diff / DECAY_HOURS)
    News published closer to the event gets higher weight.
    """
    try:
        event_time = datetime.fromisoformat(str(event_ts).replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        event_time = datetime.now(timezone.utc)

    scored = []
    for r in results:
        # Get publication time from metadata
        pub_str = r.metadata.get("published_at", "") or r.metadata.get("timestamp", "")
        if pub_str:
            try:
                pub_time = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                if pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=timezone.utc)
                hours_diff = abs((event_time - pub_time).total_seconds()) / 3600
            except (ValueError, TypeError):
                hours_diff = ATTRIBUTION_TIME_DECAY_HOURS
        else:
            hours_diff = ATTRIBUTION_TIME_DECAY_HOURS

        # Exponential decay: closer news = higher weight
        decay = math.exp(-hours_diff / ATTRIBUTION_TIME_DECAY_HOURS)
        final_score = r.score * decay
        scored.append((r, final_score))

    return scored


def _synthesize_reason(
    client: AmureClient,
    fact_id: str,
    top_matches: list[tuple[SearchResult, float]],
    event_metadata: dict,
) -> Optional[str]:
    """
    Create a Reason node that summarizes why the top evidence supports
    the price event. Links: Reason --Support--> Fact.
    """
    ticker = event_metadata.get("ticker", "")
    event_type = event_metadata.get("event_type", "")
    ticker_name = TICKERS.get(ticker, {}).get("name", ticker)

    headlines = [m[0].statement[:100] for m in top_matches]
    summary = " | ".join(headlines)
    direction = "상승" if event_type == "surge" else ("하락" if event_type == "crash" else event_type)

    statement = f"{ticker_name} {direction} 원인: {summary}"

    keywords = list(set(
        kw
        for m, _ in top_matches
        for kw in m.keywords[:3]
    ))
    keywords.append(ticker.lower().replace("-usd", ""))

    reason_id = client.create_node(
        kind="Reason",
        statement=statement[:500],
        keywords=keywords[:15],
        metadata={
            "ticker": ticker,
            "event_fact_id": fact_id,
            "evidence_count": len(top_matches),
            "avg_confidence": sum(s for _, s in top_matches) / len(top_matches),
        },
        status="Active",
    )

    if reason_id:
        client.create_edge(
            source=reason_id,
            target=fact_id,
            kind="Support",
            weight=1.0,
            note="synthesized_reason",
        )

    return reason_id
