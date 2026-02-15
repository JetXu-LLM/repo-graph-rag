from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Tuple

from v2.graph.migrations import EDGE_COLLECTION, JOB_COLLECTION, MigrationManagerV2, VERTEX_COLLECTION
from v2.models import GraphEdge, GraphNode, GraphSnapshot, IndexJobStatus, RelationProvenance
from v2.serializer import canonicalize_snapshot


def _safe_arango_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:48]


class ArangoGraphStoreV2:
    def __init__(self, db) -> None:
        self.db = db
        self.migrations = MigrationManagerV2()

    def bootstrap(self) -> Dict[str, List[str]]:
        return self.migrations.bootstrap(self.db)

    def save_snapshot(self, snapshot: GraphSnapshot) -> None:
        canonicalize_snapshot(snapshot)
        node_collection = self.db.collection(VERTEX_COLLECTION)
        edge_collection = self.db.collection(EDGE_COLLECTION)

        for node in snapshot.nodes:
            payload = asdict(node)
            payload["_key"] = _safe_arango_key(node.id)
            self._upsert(node_collection, payload)

        for edge in snapshot.edges:
            payload = asdict(edge)
            payload["_key"] = _safe_arango_key(edge.id)
            payload["_from"] = f"{VERTEX_COLLECTION}/{_safe_arango_key(edge.source_id)}"
            payload["_to"] = f"{VERTEX_COLLECTION}/{_safe_arango_key(edge.target_id)}"
            self._upsert(edge_collection, payload)

    def get_snapshot(self, tenant_id: str, repo_id: str, commit_sha: str) -> GraphSnapshot:
        node_query = (
            "FOR doc IN @@collection "
            "FILTER doc.tenant_id == @tenant_id "
            "FILTER doc.repo_id == @repo_id "
            "FILTER doc.commit_sha == @commit_sha "
            "RETURN doc"
        )
        edge_query = (
            "FOR doc IN @@collection "
            "FILTER doc.tenant_id == @tenant_id "
            "FILTER doc.repo_id == @repo_id "
            "FILTER doc.commit_sha == @commit_sha "
            "RETURN doc"
        )

        node_docs = list(
            self.db.aql.execute(
                node_query,
                bind_vars={
                    "@collection": VERTEX_COLLECTION,
                    "tenant_id": tenant_id,
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                },
            )
        )
        edge_docs = list(
            self.db.aql.execute(
                edge_query,
                bind_vars={
                    "@collection": EDGE_COLLECTION,
                    "tenant_id": tenant_id,
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                },
            )
        )

        nodes = [
            GraphNode(
                id=doc["id"],
                tenant_id=doc["tenant_id"],
                repo_id=doc["repo_id"],
                commit_sha=doc["commit_sha"],
                entity_kind=doc["entity_kind"],
                symbol_path=doc["symbol_path"],
                file_path=doc["file_path"],
                name=doc["name"],
                parent_name=doc.get("parent_name", ""),
                metadata=doc.get("metadata", {}),
            )
            for doc in node_docs
        ]

        edges = [
            GraphEdge(
                id=doc["id"],
                tenant_id=doc["tenant_id"],
                repo_id=doc["repo_id"],
                commit_sha=doc["commit_sha"],
                source_id=doc["source_id"],
                target_id=doc["target_id"],
                relation_type=doc["relation_type"],
                provenance=RelationProvenance(
                    extractor_pass=doc.get("provenance", {}).get("extractor_pass", "relation_extraction"),
                    rule_id=doc.get("provenance", {}).get("rule_id", "relation.unknown"),
                    source_span=tuple(doc.get("provenance", {}).get("source_span", (0, 0))),
                    confidence=float(doc.get("provenance", {}).get("confidence", 0.5)),
                ),
                metadata=doc.get("metadata", {}),
            )
            for doc in edge_docs
        ]

        snapshot = GraphSnapshot(
            tenant_id=tenant_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            graph_version="2.0",
            schema_hash="",
            nodes=nodes,
            edges=edges,
        )
        canonicalize_snapshot(snapshot)
        return snapshot

    def upsert_job_status(self, status: IndexJobStatus) -> None:
        collection = self.db.collection(JOB_COLLECTION)
        payload = asdict(status)
        payload["_key"] = _safe_arango_key(f"{status.tenant_id}:{status.job_id}")
        self._upsert(collection, payload)

    def get_job_status(self, tenant_id: str, job_id: str) -> Optional[IndexJobStatus]:
        collection = self.db.collection(JOB_COLLECTION)
        key = _safe_arango_key(f"{tenant_id}:{job_id}")
        if not collection.has(key):
            return None
        doc = collection.get(key)
        return IndexJobStatus(
            job_id=doc["job_id"],
            tenant_id=doc["tenant_id"],
            repo_id=doc["repo_id"],
            commit_sha=doc["commit_sha"],
            status=doc["status"],
            attempts=doc.get("attempts", 0),
            error=doc.get("error", ""),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
        )

    @staticmethod
    def _upsert(collection, payload: Dict[str, object]) -> None:
        if collection.has(payload["_key"]):
            collection.update(payload)
        else:
            collection.insert(payload)


class InMemoryGraphStoreV2:
    def __init__(self) -> None:
        self.snapshots: Dict[Tuple[str, str, str], GraphSnapshot] = {}
        self.jobs: Dict[Tuple[str, str], IndexJobStatus] = {}

    def bootstrap(self) -> Dict[str, List[str]]:
        return {"collections": [], "indexes": []}

    def save_snapshot(self, snapshot: GraphSnapshot) -> None:
        canonicalize_snapshot(snapshot)
        key = (snapshot.tenant_id, snapshot.repo_id, snapshot.commit_sha)
        self.snapshots[key] = snapshot

    def get_snapshot(self, tenant_id: str, repo_id: str, commit_sha: str) -> GraphSnapshot:
        key = (tenant_id, repo_id, commit_sha)
        if key not in self.snapshots:
            return GraphSnapshot(
                tenant_id=tenant_id,
                repo_id=repo_id,
                commit_sha=commit_sha,
                graph_version="2.0",
                schema_hash="",
                nodes=[],
                edges=[],
            )
        snapshot = self.snapshots[key]
        canonicalize_snapshot(snapshot)
        return snapshot

    def upsert_job_status(self, status: IndexJobStatus) -> None:
        self.jobs[(status.tenant_id, status.job_id)] = status

    def get_job_status(self, tenant_id: str, job_id: str) -> Optional[IndexJobStatus]:
        return self.jobs.get((tenant_id, job_id))

    def query_context(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        file_path: str | None = None,
        symbol_type: str | None = None,
        relation_type: str | None = None,
        hop_limit: int = 1,
        cursor: int = 0,
        limit: int = 50,
    ) -> Dict[str, object]:
        snapshot = self.get_snapshot(tenant_id, repo_id, commit_sha)
        nodes = [node for node in snapshot.nodes if (not file_path or node.file_path == file_path)]
        if symbol_type:
            nodes = [node for node in nodes if node.entity_kind == symbol_type]

        selected_ids = {node.id for node in nodes}
        edges = snapshot.edges
        if relation_type:
            edges = [edge for edge in edges if edge.relation_type == relation_type]

        frontier = set(selected_ids)
        included_edges: List[GraphEdge] = []
        for _ in range(max(hop_limit, 1)):
            step_edges = [
                edge
                for edge in edges
                if edge.source_id in frontier or edge.target_id in frontier
            ]
            if not step_edges:
                break
            included_edges.extend(step_edges)
            frontier = {edge.source_id for edge in step_edges} | {edge.target_id for edge in step_edges}
            selected_ids |= frontier

        selected_nodes = [node for node in snapshot.nodes if node.id in selected_ids]
        selected_nodes = sorted(selected_nodes, key=lambda node: node.id)
        included_edges = sorted(
            {edge.id: edge for edge in included_edges}.values(),
            key=lambda edge: (edge.source_id, edge.relation_type, edge.target_id, edge.id),
        )

        total = len(selected_nodes)
        page_nodes = selected_nodes[cursor : cursor + limit]
        next_cursor = cursor + limit if cursor + limit < total else None

        return {
            "nodes": [asdict(node) for node in page_nodes],
            "edges": [asdict(edge) for edge in included_edges],
            "total": total,
            "next_cursor": next_cursor,
        }

    def explain_relation(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        edge_id: str,
    ) -> Dict[str, object] | None:
        snapshot = self.get_snapshot(tenant_id, repo_id, commit_sha)
        for edge in snapshot.edges:
            if edge.id == edge_id:
                return asdict(edge)
        return None
