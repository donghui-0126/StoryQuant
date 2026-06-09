"""
Aggressively populate amure-db knowledge graph.
1. Auto-organize Yahoo Facts into Claims
2. Create Experiment nodes (backtest hypotheses)
3. Create Reason nodes linking Claims to Evidence
4. Detect contradictions
5. Build dependency chains
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from src.graph.client import AmureClient

client = AmureClient()
print(f"Connected. Current: {client.graph_summary()}\n")

# ============================================================
# 1. AUTO-ORGANIZE Yahoo Facts into Claims
# ============================================================
print("=" * 50)
print("Step 1: Auto-organize Yahoo Facts into Claims")
print("=" * 50)

import httpx
resp = httpx.post(f"{client.base_url}/api/yahoo/auto-organize", timeout=30)
if resp.status_code == 200:
    data = resp.json()
    print(f"  Groups created: {data.get('groups_created', data)}")
else:
    print(f"  Auto-organize: {resp.status_code}")

# ============================================================
# 2. Create EXPERIMENT nodes (testable hypotheses)
# ============================================================
print("\n" + "=" * 50)
print("Step 2: Create Experiment nodes")
print("=" * 50)

experiments = [
    {
        "statement": "BTC ETF inflow > $200M predicts +3% within 24h",
        "keywords": ["btc", "etf", "inflow", "momentum"],
        "metadata": {"method": "event_study", "threshold": "200M", "horizon": "24h", "expected_return": 0.03},
    },
    {
        "statement": "NVIDIA earnings beat > 10% predicts semiconductor sector rally within 1 week",
        "keywords": ["nvidia", "earnings", "semiconductor", "rally"],
        "metadata": {"method": "sector_momentum", "threshold": "10% beat", "horizon": "1w"},
    },
    {
        "statement": "Fed dovish signal predicts crypto rally within 48h",
        "keywords": ["fed", "dovish", "crypto", "rally", "rate"],
        "metadata": {"method": "macro_event", "trigger": "fed_dovish", "horizon": "48h"},
    },
    {
        "statement": "Volume spike > 3x on Korean stocks predicts continuation next session",
        "keywords": ["volume", "spike", "korean", "continuation"],
        "metadata": {"method": "volume_analysis", "threshold": "3x", "horizon": "1d"},
    },
    {
        "statement": "BTC-ETH correlation breakdown predicts altcoin rotation",
        "keywords": ["btc", "eth", "correlation", "altcoin", "rotation"],
        "metadata": {"method": "correlation_regime", "horizon": "1w"},
    },
    {
        "statement": "HBM demand news within 24h predicts Samsung/SK Hynix outperformance",
        "keywords": ["hbm", "samsung", "sk hynix", "semiconductor", "demand"],
        "metadata": {"method": "news_momentum", "horizon": "24h"},
    },
    {
        "statement": "SOL TVL increase > 10% weekly predicts SOL price +5%",
        "keywords": ["solana", "sol", "tvl", "defi", "momentum"],
        "metadata": {"method": "onchain_metric", "threshold": "10% tvl", "horizon": "1w"},
    },
    {
        "statement": "Trump tariff announcement predicts VIX spike > 20% within 2h",
        "keywords": ["trump", "tariff", "vix", "volatility"],
        "metadata": {"method": "event_study", "trigger": "tariff_news", "horizon": "2h"},
    },
    {
        "statement": "Whale transfer > $50M to exchange predicts sell pressure within 4h",
        "keywords": ["whale", "transfer", "exchange", "sell", "pressure"],
        "metadata": {"method": "onchain_flow", "threshold": "50M", "horizon": "4h"},
    },
    {
        "statement": "Cross-market: US tech selloff predicts Korean semiconductor dip next session",
        "keywords": ["cross-market", "us", "tech", "korean", "semiconductor", "lag"],
        "metadata": {"method": "lead_lag", "source": "us_tech", "target": "kr_semi", "lag": "1d"},
    },
]

exp_ids = []
for exp in experiments:
    eid = client.create_node(
        kind="Experiment",
        statement=exp["statement"],
        keywords=exp["keywords"],
        metadata=exp["metadata"],
        status="Draft",
    )
    if eid:
        exp_ids.append(eid)
        print(f"  Experiment: {exp['statement'][:60]}")

print(f"  Created {len(exp_ids)} Experiments")

# ============================================================
# 3. Create REASON nodes with causal logic
# ============================================================
print("\n" + "=" * 50)
print("Step 3: Create Reason nodes (causal logic)")
print("=" * 50)

reasons = [
    {
        "statement": "Institutional ETF buying creates sustained demand floor for BTC, reducing volatility and attracting more institutional allocators",
        "keywords": ["btc", "etf", "institutional", "demand", "volatility"],
    },
    {
        "statement": "AI training compute demand doubles every 6 months, creating structural shortage in HBM and advanced packaging capacity",
        "keywords": ["ai", "compute", "hbm", "shortage", "semiconductor"],
    },
    {
        "statement": "Fed rate cuts reduce USD strength, making risk assets (crypto, tech) relatively more attractive for global capital",
        "keywords": ["fed", "rate", "usd", "risk", "crypto", "tech"],
    },
    {
        "statement": "Trump tariff escalation disrupts global supply chains, hitting export-dependent Korean manufacturers hardest",
        "keywords": ["trump", "tariff", "supply chain", "korean", "export"],
    },
    {
        "statement": "Solana low fees enable memecoin speculation, driving TVL and active addresses but creating fragile liquidity",
        "keywords": ["solana", "fees", "memecoin", "tvl", "liquidity"],
    },
    {
        "statement": "Samsung HBM3E yield improvement reduces cost per GB, enabling AI server OEMs to increase order volumes",
        "keywords": ["samsung", "hbm", "yield", "cost", "ai", "server"],
    },
    {
        "statement": "Whale exchange deposits signal intent to sell, creating short-term supply pressure on BTC/ETH",
        "keywords": ["whale", "exchange", "deposit", "sell", "btc", "eth"],
    },
    {
        "statement": "US market leads Asian markets by 12-16 hours; tech selloffs propagate to Korean semiconductor stocks next session",
        "keywords": ["us", "asia", "lag", "tech", "semiconductor", "korean"],
    },
]

reason_ids = []
for r in reasons:
    rid = client.create_node(
        kind="Reason",
        statement=r["statement"],
        keywords=r["keywords"],
        metadata={"type": "causal_logic"},
        status="Active",
    )
    if rid:
        reason_ids.append(rid)
        print(f"  Reason: {r['statement'][:60]}")

print(f"  Created {len(reason_ids)} Reasons")

# ============================================================
# 4. Link Reasons to Claims via keyword matching
# ============================================================
print("\n" + "=" * 50)
print("Step 4: Link Reasons -> Claims")
print("=" * 50)

all_data = client.get_all()
claims = [n for n in all_data["nodes"] if n.get("kind") == "Claim"]
new_reasons = [n for n in all_data["nodes"] if n.get("kind") == "Reason" and n.get("metadata", {}).get("type") == "causal_logic"]

linked = 0
for reason in new_reasons:
    r_keywords = set(reason.get("keywords", []))
    for claim in claims:
        c_keywords = set(claim.get("keywords", []))
        overlap = r_keywords & c_keywords
        if len(overlap) >= 2:
            eid = client.create_edge(
                source=reason["id"], target=claim["id"],
                kind="Support", weight=len(overlap) / max(len(r_keywords), 1),
                note=f"keyword_overlap: {', '.join(overlap)}",
            )
            if eid:
                linked += 1

print(f"  Linked {linked} Reason->Claim edges")

# ============================================================
# 5. Link Experiments to Claims (DependsOn)
# ============================================================
print("\n" + "=" * 50)
print("Step 5: Link Experiments -> Claims (DependsOn)")
print("=" * 50)

all_data = client.get_all()
experiments_nodes = [n for n in all_data["nodes"] if n.get("kind") == "Experiment"]

dep_linked = 0
for exp in experiments_nodes:
    e_keywords = set(exp.get("keywords", []))
    for claim in claims:
        c_keywords = set(claim.get("keywords", []))
        overlap = e_keywords & c_keywords
        if len(overlap) >= 2:
            eid = client.create_edge(
                source=exp["id"], target=claim["id"],
                kind="DependsOn", weight=len(overlap) / max(len(e_keywords), 1),
                note=f"tests_claim: {', '.join(overlap)}",
            )
            if eid:
                dep_linked += 1

print(f"  Linked {dep_linked} Experiment->Claim DependsOn edges")

# ============================================================
# 6. Detect contradictions
# ============================================================
print("\n" + "=" * 50)
print("Step 6: Detect contradictions")
print("=" * 50)

contradictions = client.detect_contradictions()
print(f"  Found {len(contradictions)} contradictions")

# ============================================================
# 7. Detect dependencies between claims
# ============================================================
print("\n" + "=" * 50)
print("Step 7: Auto-detect claim dependencies")
print("=" * 50)

for claim in claims:
    result = client.detect_dependencies(claim["id"])
    deps = result.get("created", result.get("dependencies", 0))
    if deps:
        print(f"  {claim.get('statement', '')[:50]}: {deps} deps")

# ============================================================
# 8. Update lifecycle
# ============================================================
print("\n" + "=" * 50)
print("Step 8: Update narrative lifecycle")
print("=" * 50)

from src.graph.reasoning import update_narrative_lifecycle
result = update_narrative_lifecycle(client)
print(f"  Updated: {result}")

# ============================================================
# Final summary
# ============================================================
client.save()
summary = client.graph_summary()
print("\n" + "=" * 50)
print("FINAL GRAPH STATE")
print("=" * 50)
print(f"  Nodes: {summary.get('n_nodes', 0)}")
print(f"  Edges: {summary.get('n_edges', 0)}")
for kind, count in summary.get("node_kinds", {}).items():
    print(f"    {kind}: {count}")
for kind, count in summary.get("edge_kinds", {}).items():
    print(f"    {kind}: {count}")

client.close()
print("\nDone!")
