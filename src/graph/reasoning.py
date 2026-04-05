"""
Graph-based reasoning engine.
Handles narrative lifecycle, contradiction detection, causal analysis,
and cross-market linking via amure-db graph.
"""
import logging
from datetime import datetime, timezone, timedelta

from src.graph.client import AmureClient
from src.config.settings import NARRATIVE_STALE_HOURS, NARRATIVE_MIN_EVIDENCE

logger = logging.getLogger(__name__)


def update_narrative_lifecycle(client: AmureClient) -> dict:
    """
    Update lifecycle status of all Claim (narrative) nodes based on
    connected Evidence count, recency, and verdict propagation.

    Lifecycle mapping:
      Draft     → EMERGING (few Evidence, recently created)
      Active    → BUILDING (growing Evidence support)
      Accepted  → PEAKING  (strong, confirmed narrative)
      Weakened  → FADING   (stale or contradicted)
    """
    all_data = client.get_all()
    nodes = all_data.get("nodes", [])
    edges = all_data.get("edges", [])

    claims = [n for n in nodes if n.get("kind") == "Claim"]
    if not claims:
        return {"updated": 0}

    edge_index = {}
    for e in edges:
        target = e.get("target", "")
        edge_index.setdefault(target, []).append(e)

    now = datetime.now(timezone.utc)
    updated = 0

    for claim in claims:
        claim_id = claim.get("id", "")
        metadata = claim.get("metadata", {})

        support_edges = [
            e for e in edge_index.get(claim_id, [])
            if e.get("kind") == "Support"
        ]
        evidence_count = len(support_edges)

        created_str = metadata.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now - created).total_seconds() / 3600
        except (ValueError, TypeError):
            age_hours = 0

        current_status = claim.get("status", "Draft")

        if evidence_count < NARRATIVE_MIN_EVIDENCE:
            new_status = "Draft"
            lifecycle = "emerging"
        elif age_hours > NARRATIVE_STALE_HOURS and evidence_count < NARRATIVE_MIN_EVIDENCE * 2:
            new_status = "Weakened"
            lifecycle = "fading"
        elif evidence_count >= NARRATIVE_MIN_EVIDENCE * 3:
            new_status = "Accepted"
            lifecycle = "peaking"
        else:
            new_status = "Active"
            lifecycle = "building"

        if new_status != current_status or metadata.get("lifecycle") != lifecycle:
            new_meta = {**metadata, "lifecycle": lifecycle, "evidence_count": evidence_count}
            client.update_node(claim_id, status=new_status, metadata=new_meta)
            updated += 1

            if new_status == "Accepted" and current_status != "Accepted":
                client.on_accept(claim_id)

    logger.info("Narrative lifecycle: updated %d/%d claims", updated, len(claims))
    return {"updated": updated, "total_claims": len(claims)}


def detect_and_link_contradictions(client: AmureClient) -> dict:
    """Run contradiction detection and return results."""
    contradictions = client.detect_contradictions()
    logger.info("Found %d contradictions", len(contradictions))
    return {"contradictions": contradictions, "count": len(contradictions)}


def check_knowledge_health(client: AmureClient) -> dict:
    """Check temporal health of accepted knowledge."""
    health = client.temporal_health()
    stale = [h for h in health if h.get("urgency") in ("SOON", "OVERDUE")]
    logger.info("Knowledge health: %d total, %d stale", len(health), len(stale))
    return {"total": len(health), "stale_count": len(stale), "stale_nodes": stale}


def create_cross_market_link(
    client: AmureClient,
    source_fact_id: str,
    target_fact_id: str,
    correlation: float,
    lag_hours: float = 0,
    note: str = "",
) -> str:
    """Create a DependsOn edge between two Fact nodes for cross-market signals."""
    edge_note = f"correlation={correlation:.3f}, lag={lag_hours}h"
    if note:
        edge_note += f", {note}"

    edge_id = client.create_edge(
        source=target_fact_id,
        target=source_fact_id,
        kind="DependsOn",
        weight=abs(correlation),
        note=edge_note,
    )
    return edge_id


def get_causal_explanation(client: AmureClient, fact_node_id: str) -> dict:
    """
    Get a full causal explanation for a price event by tracing
    the graph backwards through Support/DependsOn chains.
    """
    chains = client.causal_chains(fact_node_id)

    neighbors = client.walk(fact_node_id, hops=2)

    support_evidence = []
    reasons = []
    related_claims = []

    for n in neighbors:
        kind = n.get("kind", "")
        if kind == "Evidence":
            support_evidence.append(n)
        elif kind == "Reason":
            reasons.append(n)
        elif kind == "Claim":
            related_claims.append(n)

    return {
        "fact_id": fact_node_id,
        "causal_chains": chains,
        "evidence": support_evidence,
        "reasons": reasons,
        "narratives": related_claims,
        "chain_count": len(chains),
    }


def get_active_narratives(client: AmureClient) -> list[dict]:
    """
    Get all active narratives (Claims) with their lifecycle status
    and supporting evidence count.
    """
    all_data = client.get_all()
    nodes = all_data.get("nodes", [])
    edges = all_data.get("edges", [])

    claims = [n for n in nodes if n.get("kind") == "Claim"]

    support_count = {}
    for e in edges:
        if e.get("kind") == "Support":
            target = e.get("target", "")
            support_count[target] = support_count.get(target, 0) + 1

    narratives = []
    for c in claims:
        cid = c.get("id", "")
        meta = c.get("metadata", {})
        narratives.append({
            "id": cid,
            "statement": c.get("statement", ""),
            "status": c.get("status", "Draft"),
            "lifecycle": meta.get("lifecycle", "emerging"),
            "market": meta.get("market", ""),
            "direction": meta.get("direction", ""),
            "evidence_count": support_count.get(cid, 0),
            "keywords": c.get("keywords", []),
            "created_at": meta.get("created_at", ""),
        })

    narratives.sort(key=lambda x: x["evidence_count"], reverse=True)
    return narratives


def get_recent_events_from_graph(client: AmureClient, limit: int = 50) -> list[dict]:
    """Get recent Fact (price event) nodes from the graph."""
    all_data = client.get_all()
    nodes = all_data.get("nodes", [])
    edges = all_data.get("edges", [])

    facts = [n for n in nodes if n.get("kind") == "Fact"]
    facts.sort(key=lambda x: x.get("metadata", {}).get("timestamp", ""), reverse=True)
    facts = facts[:limit]

    support_map = {}
    for e in edges:
        if e.get("kind") == "Support":
            target = e.get("target", "")
            support_map.setdefault(target, []).append(e)

    result = []
    for f in facts:
        fid = f.get("id", "")
        meta = f.get("metadata", {})
        supports = support_map.get(fid, [])
        result.append({
            "id": fid,
            "statement": f.get("statement", ""),
            "ticker": meta.get("ticker", ""),
            "return_1h": meta.get("return_1h", 0),
            "event_type": meta.get("event_type", ""),
            "severity": meta.get("severity", "low"),
            "market": meta.get("market", ""),
            "timestamp": meta.get("timestamp", ""),
            "attributed": meta.get("attributed", False),
            "attribution_count": len(supports),
            "top_attribution": supports[0].get("note", "") if supports else "",
        })

    return result


def get_recent_evidence(client: AmureClient, market: str = None, limit: int = 50) -> list[dict]:
    """Get recent Evidence (news) nodes from the graph."""
    all_data = client.get_all()
    nodes = all_data.get("nodes", [])

    evidence = [n for n in nodes if n.get("kind") == "Evidence"]

    if market:
        evidence = [e for e in evidence if e.get("metadata", {}).get("market") == market]

    evidence.sort(key=lambda x: x.get("metadata", {}).get("published_at", ""), reverse=True)

    result = []
    for e in evidence[:limit]:
        meta = e.get("metadata", {})
        result.append({
            "id": e.get("id", ""),
            "statement": e.get("statement", ""),
            "source": meta.get("source", ""),
            "source_type": meta.get("source_type", ""),
            "market": meta.get("market", ""),
            "url": meta.get("url", ""),
            "published_at": meta.get("published_at", ""),
            "sentiment": meta.get("sentiment", "neutral"),
            "sentiment_score": meta.get("sentiment_score", 0.0),
            "keywords": e.get("keywords", []),
        })

    return result
