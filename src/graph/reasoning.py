"""
Graph-based reasoning engine.
Handles narrative lifecycle, contradiction detection, causal analysis,
cross-market linking, and automatic narrative discovery via amure-db graph.
"""
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

from src.graph.client import AmureClient
from src.config.settings import NARRATIVE_STALE_HOURS, NARRATIVE_MIN_EVIDENCE

logger = logging.getLogger(__name__)


def update_narrative_lifecycle(client: AmureClient) -> dict:
    """Update lifecycle status of all Claim nodes based on evidence count/recency."""
    claims = client.get_nodes_by_kind("Claim")
    if not claims:
        return {"updated": 0}

    support_index = client.get_support_index()
    now = datetime.now(timezone.utc)
    updated = 0

    for claim in claims:
        claim_id = claim.get("id", "")
        metadata = claim.get("metadata", {})
        evidence_count = len(support_index.get(claim_id, []))

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


def discover_narratives(client: AmureClient, min_cluster_size: int = 3) -> dict:
    """
    Auto-discover narratives by clustering Evidence nodes by keyword co-occurrence.
    Creates new Claim nodes for emerging clusters not yet covered by existing Claims.
    """
    evidence = client.get_nodes_by_kind("Evidence")
    existing_claims = client.get_nodes_by_kind("Claim")

    if len(evidence) < min_cluster_size:
        return {"discovered": 0}

    # Collect keyword frequency across all Evidence
    keyword_pairs = Counter()
    keyword_to_nodes = {}
    for e in evidence:
        kws = [k.lower() for k in e.get("keywords", []) if len(k) > 1]
        for kw in kws:
            keyword_to_nodes.setdefault(kw, []).append(e.get("id", ""))
        # Count pairs for co-occurrence
        for i, k1 in enumerate(kws):
            for k2 in kws[i+1:]:
                pair = tuple(sorted([k1, k2]))
                keyword_pairs[pair] += 1

    # Find clusters: keyword pairs that co-occur >= min_cluster_size times
    existing_kw_sets = [set(c.get("keywords", [])) for c in existing_claims]

    discovered = 0
    seen_pairs = set()
    for (k1, k2), count in keyword_pairs.most_common(50):
        if count < min_cluster_size:
            break

        cluster_kws = {k1, k2}

        # Skip if already covered by existing Claim
        already_covered = False
        for ek in existing_kw_sets:
            if cluster_kws.issubset(ek):
                already_covered = True
                break
        if already_covered:
            continue

        # Skip if we already created a similar cluster this round
        pair_key = tuple(sorted(cluster_kws))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        # Find all evidence nodes matching this cluster
        matching_nodes = set(keyword_to_nodes.get(k1, [])) & set(keyword_to_nodes.get(k2, []))
        if len(matching_nodes) < min_cluster_size:
            continue

        # Determine market from matching evidence
        node_map = client.get_node_map()
        markets = Counter()
        for nid in matching_nodes:
            n = node_map.get(nid, {})
            m = n.get("metadata", {}).get("market", "")
            if m:
                markets[m] += 1
        market = markets.most_common(1)[0][0] if markets else ""

        # Create Claim
        statement = f"Emerging narrative: {k1} + {k2} ({count} evidence, {len(matching_nodes)} nodes)"
        keywords = list(cluster_kws)

        from src.graph.mapper import narrative_to_claim
        claim_id = narrative_to_claim(client, statement, keywords, market=market)

        if claim_id:
            # Link matching evidence
            for nid in list(matching_nodes)[:20]:
                client.create_edge(source=nid, target=claim_id, kind="Support",
                                   weight=0.5, note="auto-discovered")
            discovered += 1
            logger.info("Discovered narrative: %s (%d evidence)", statement[:50], len(matching_nodes))

    logger.info("Narrative discovery: %d new narratives", discovered)
    return {"discovered": discovered}


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
    edge_note = f"correlation={correlation:.3f}, lag={lag_hours}h"
    if note:
        edge_note += f", {note}"
    return client.create_edge(
        source=target_fact_id, target=source_fact_id,
        kind="DependsOn", weight=abs(correlation), note=edge_note,
    )


def get_causal_explanation(client: AmureClient, fact_node_id: str) -> dict:
    """Get full causal explanation for a price event."""
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
    """Get all active narratives with evidence count."""
    claims = client.get_nodes_by_kind("Claim")
    support_index = client.get_support_index()

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
            "evidence_count": len(support_index.get(cid, [])),
            "keywords": c.get("keywords", []),
            "created_at": meta.get("created_at", ""),
        })

    narratives.sort(key=lambda x: x["evidence_count"], reverse=True)
    return narratives


def get_recent_events_from_graph(client: AmureClient, limit: int = 50) -> list[dict]:
    """Get recent Fact (price event) nodes."""
    facts = client.get_nodes_by_kind("Fact")
    facts.sort(key=lambda x: x.get("metadata", {}).get("timestamp", ""), reverse=True)
    facts = facts[:limit]

    support_index = client.get_support_index()

    result = []
    for f in facts:
        fid = f.get("id", "")
        meta = f.get("metadata", {})
        attr_count = len(support_index.get(fid, []))
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
            "attribution_count": attr_count,
        })

    return result


def get_recent_evidence(client: AmureClient, market: str = None, limit: int = 50) -> list[dict]:
    """Get recent Evidence (news) nodes."""
    evidence = client.get_nodes_by_kind("Evidence")

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
