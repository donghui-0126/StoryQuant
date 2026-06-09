"""
Synchronous HTTP client for amure-db graph API.
Uses httpx with connection pooling. Each background thread should
create its own AmureClient instance.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import httpx

from src.config.settings import AMURE_DB_URL, AMURE_DB_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    id: str
    kind: str
    statement: str
    keywords: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    status: str = "Draft"


@dataclass
class SearchResult:
    node_id: str
    kind: str
    statement: str
    keywords: list[str]
    score: float
    hop_distance: int = 0
    failed_path: bool = False
    status: str = "Active"
    metadata: dict = field(default_factory=dict)


class AmureClient:
    """Synchronous HTTP client for amure-db graph API (port 8081)."""

    def __init__(self, base_url: str = None, timeout: float = None):
        self.base_url = base_url or AMURE_DB_URL
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout or AMURE_DB_TIMEOUT,
        )
        self._cache = None
        self._cache_time = 0

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Health check ──

    def is_available(self) -> bool:
        try:
            resp = self._client.get("/api/graph/summary")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Node CRUD ──

    def create_node(
        self,
        kind: str,
        statement: str,
        keywords: list[str],
        metadata: dict = None,
        status: str = "Active",
    ) -> Optional[str]:
        try:
            resp = self._client.post("/api/graph/node", json={
                "kind": kind,
                "statement": statement,
                "keywords": keywords,
                "metadata": metadata or {},
                "status": status,
            })
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as e:
            logger.error("Failed to create node: %s", e)
            return None

    def get_node(self, node_id: str) -> Optional[dict]:
        try:
            resp = self._client.get(f"/api/graph/node/{node_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("Failed to get node %s: %s", node_id, e)
            return None

    def update_node(
        self,
        node_id: str,
        status: str = None,
        metadata: dict = None,
        keywords: list[str] = None,
    ) -> bool:
        payload = {}
        if status is not None:
            payload["status"] = status
        if metadata is not None:
            payload["metadata"] = metadata
        if keywords is not None:
            payload["keywords"] = keywords
        try:
            resp = self._client.patch(f"/api/graph/node/{node_id}", json=payload)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to update node %s: %s", node_id, e)
            return False

    def delete_node(self, node_id: str) -> bool:
        try:
            resp = self._client.delete(f"/api/graph/node/{node_id}")
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to delete node %s: %s", node_id, e)
            return False

    # ── Edge CRUD ──

    def create_edge(
        self,
        source: str,
        target: str,
        kind: str,
        weight: float = 1.0,
        note: str = "",
    ) -> Optional[str]:
        try:
            resp = self._client.post("/api/graph/edge", json={
                "source": source,
                "target": target,
                "kind": kind,
                "weight": weight,
                "note": note,
            })
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as e:
            logger.error("Failed to create edge: %s", e)
            return None

    def delete_edge(self, edge_id: str) -> bool:
        try:
            resp = self._client.delete(f"/api/graph/edge/{edge_id}")
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to delete edge %s: %s", edge_id, e)
            return False

    # ── Search (core RAG) ──

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        try:
            resp = self._client.get("/api/graph/search", params={
                "q": query,
                "top_k": top_k,
            })
            resp.raise_for_status()
            data = resp.json()
            results = data if isinstance(data, list) else data.get("results", [])
            return [
                SearchResult(
                    node_id=r.get("node_id", r.get("id", "")),
                    kind=r.get("kind", ""),
                    statement=r.get("statement", ""),
                    keywords=r.get("keywords", []),
                    score=r.get("score", 0.0),
                    hop_distance=r.get("hop_distance", 0),
                    failed_path=r.get("failed_path", False),
                    status=r.get("status", "Active"),
                    metadata=r.get("metadata", {}),
                )
                for r in results
            ]
        except Exception as e:
            logger.error("Search failed for query '%s': %s", query, e)
            return []

    # ── Graph traversal ──

    def walk(self, node_id: str, hops: int = 2) -> list[dict]:
        try:
            resp = self._client.get(f"/api/graph/walk/{node_id}", params={"hops": hops})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("nodes", [])
        except Exception as e:
            logger.debug("Walk failed for %s: %s", node_id, e)
            return []

    def causal_chains(self, node_id: str) -> list[dict]:
        try:
            resp = self._client.get(f"/api/graph/causal-chains/{node_id}")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("chains", [])
        except Exception as e:
            logger.debug("Causal chains failed for %s: %s", node_id, e)
            return []

    def subgraph(self, node_id: str) -> dict:
        try:
            resp = self._client.get(f"/api/graph/subgraph/{node_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("Subgraph failed for %s: %s", node_id, e)
            return {}

    # ── Knowledge analysis ──

    def check_failures(self, statement: str, keywords: list[str]) -> list[dict]:
        try:
            resp = self._client.post("/api/check-failures", json={
                "statement": statement,
                "keywords": keywords,
            })
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("warnings", [])
        except Exception as e:
            logger.debug("Check failures failed: %s", e)
            return []

    def detect_contradictions(self) -> list[dict]:
        try:
            resp = self._client.post("/api/detect-contradictions")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("contradictions", [])
        except Exception as e:
            logger.debug("Detect contradictions failed: %s", e)
            return []

    def propagate_verdict(self, experiment_id: str) -> dict:
        try:
            resp = self._client.post(f"/api/graph/propagate-verdict/{experiment_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("Propagate verdict failed: %s", e)
            return {}

    def temporal_health(self) -> list[dict]:
        try:
            resp = self._client.get("/api/check-revalidation")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("nodes", [])
        except Exception as e:
            logger.debug("Temporal health failed: %s", e)
            return []

    def detect_dependencies(self, node_id: str) -> dict:
        try:
            resp = self._client.post(f"/api/graph/detect-dependencies/{node_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("Detect dependencies failed: %s", e)
            return {}

    def on_accept(self, node_id: str) -> dict:
        try:
            resp = self._client.post(f"/api/graph/on-accept/{node_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("On-accept failed for %s: %s", node_id, e)
            return {}

    def graph_summary(self) -> dict:
        try:
            resp = self._client.get("/api/graph/summary")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug("Graph summary failed: %s", e)
            return {}

    def get_all(self, max_age: float = 15.0) -> dict:
        """Get all nodes and edges, cached for max_age seconds."""
        import time
        now = time.time()
        if self._cache and (now - self._cache_time) < max_age:
            return self._cache
        try:
            resp = self._client.get("/api/graph/all")
            resp.raise_for_status()
            self._cache = resp.json()
            self._cache_time = now
            return self._cache
        except Exception as e:
            logger.debug("Get all failed: %s", e)
            return self._cache or {"nodes": [], "edges": []}

    def invalidate_cache(self):
        self._cache = None
        self._cache_time = 0

    def get_nodes_by_kind(self, kind: str, max_age: float = 15.0) -> list[dict]:
        """Get nodes filtered by kind, using cached get_all."""
        data = self.get_all(max_age=max_age)
        return [n for n in data.get("nodes", []) if n.get("kind") == kind]

    def get_edges_by_kind(self, kind: str, max_age: float = 15.0) -> list[dict]:
        """Get edges filtered by kind, using cached get_all."""
        data = self.get_all(max_age=max_age)
        return [e for e in data.get("edges", []) if e.get("kind") == kind]

    def get_unattributed_facts(self, max_age: float = 15.0) -> list[dict]:
        """Get Fact nodes that haven't been attributed yet."""
        facts = self.get_nodes_by_kind("Fact", max_age=max_age)
        return [f for f in facts if not f.get("metadata", {}).get("attributed", False)]

    def get_node_map(self, max_age: float = 15.0) -> dict:
        """Get a {node_id: node} lookup dict."""
        data = self.get_all(max_age=max_age)
        return {n.get("id", ""): n for n in data.get("nodes", [])}

    def get_support_index(self, max_age: float = 15.0) -> dict:
        """Get {target_id: [source_ids]} for Support edges."""
        edges = self.get_edges_by_kind("Support", max_age=max_age)
        index = {}
        for e in edges:
            t = e.get("target", "")
            index.setdefault(t, []).append(e.get("source", ""))
        return index

    def save(self) -> bool:
        try:
            resp = self._client.post("/api/save")
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.debug("Save failed: %s", e)
            return False

    def impact_analysis(self, node_id: str) -> list[str]:
        try:
            resp = self._client.get(f"/api/graph/impact/{node_id}")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("impacted", [])
        except Exception as e:
            logger.debug("Impact analysis failed: %s", e)
            return []
