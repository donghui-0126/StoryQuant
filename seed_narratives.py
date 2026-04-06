"""Seed narrative Claims and link evidence via RAG search."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from src.graph.client import AmureClient
from src.graph.mapper import narrative_to_claim
from src.graph.reasoning import update_narrative_lifecycle

client = AmureClient()

narratives = [
    {"label": "Trump tariff policy triggers global market selloff",
     "keywords": ["trump", "tariff", "trade war", "crash", "selloff"],
     "market": "us", "direction": "bearish"},
    {"label": "AI semiconductor demand explosion - NVIDIA AMD TSMC earnings surprise",
     "keywords": ["ai", "semiconductor", "nvidia", "amd", "hbm", "tsmc"],
     "market": "us", "direction": "bullish"},
    {"label": "Bitcoin ETF institutional inflows accelerating",
     "keywords": ["bitcoin", "btc", "etf", "inflow", "institutional"],
     "market": "crypto", "direction": "bullish"},
    {"label": "Fed rate cut expectations rising - inflation cooling",
     "keywords": ["fed", "rate", "cut", "inflation", "dovish"],
     "market": "us", "direction": "bullish"},
    {"label": "Solana DeFi memecoin ecosystem surging - SOL TVL record",
     "keywords": ["solana", "sol", "defi", "memecoin", "tvl"],
     "market": "crypto", "direction": "bullish"},
    {"label": "Samsung HBM3E mass production for AI semiconductor",
     "keywords": ["samsung", "hbm", "ai", "semiconductor", "memory"],
     "market": "kr", "direction": "bullish"},
    {"label": "SK Hynix HBM revenue surge - AI memory dominance",
     "keywords": ["sk hynix", "hbm", "ai", "memory"],
     "market": "kr", "direction": "bullish"},
    {"label": "Ethereum L2 ecosystem expansion - ARB OP active addresses",
     "keywords": ["ethereum", "eth", "l2", "arbitrum", "optimism"],
     "market": "crypto", "direction": "bullish"},
    {"label": "Tesla autonomous driving robotaxi announcement",
     "keywords": ["tesla", "tsla", "autonomous", "robotaxi", "fsd"],
     "market": "us", "direction": "bullish"},
    {"label": "Global recession fears - employment data weakening",
     "keywords": ["recession", "unemployment", "consumer", "jobs"],
     "market": "us", "direction": "bearish"},
    {"label": "Crypto regulation easing - SEC policy shift",
     "keywords": ["regulation", "sec", "crypto", "policy"],
     "market": "crypto", "direction": "bullish"},
    {"label": "USD/KRW surge benefits Korean exporters",
     "keywords": ["usd", "krw", "exchange", "rate", "export"],
     "market": "kr", "direction": "bullish"},
]

created = 0
for n in narratives:
    nid = narrative_to_claim(client, n["label"], n["keywords"], n["market"], n["direction"])
    if nid:
        created += 1
        print(f"  Claim: {n['label'][:60]}")

print(f"\nCreated {created} Claims. Linking evidence via RAG...")

# Link evidence to claims
all_data = client.get_all()
claims = [n for n in all_data["nodes"] if n.get("kind") == "Claim"]

linked = 0
for claim in claims:
    query = " ".join(claim.get("keywords", [])[:5])
    results = client.search(query, top_k=10)
    for r in results:
        if r.kind in ("Evidence", "Fact") and r.score > 0.1:
            eid = client.create_edge(
                source=r.node_id, target=claim["id"],
                kind="Support", weight=r.score,
                note=f"auto-linked score={r.score:.3f}",
            )
            if eid:
                linked += 1

print(f"Linked {linked} Support edges to Claims")

# Update lifecycle
result = update_narrative_lifecycle(client)
print(f"Lifecycle: {result}")

client.save()
summary = client.graph_summary()
print(f"\nFinal: {summary}")
client.close()
