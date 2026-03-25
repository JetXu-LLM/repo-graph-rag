"""MCP-friendly query helpers over snapshot v2 graph stores."""

from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List


class GraphMCPToolsetV2:
    """Expose deterministic entity, relation, and subgraph lookup helpers."""

    def __init__(self, graph_store) -> None:
        self.graph_store = graph_store

    def find_entities(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        entity_kind: str | None = None,
        file_path: str | None = None,
        cursor: int = 0,
        limit: int = 50,
    ) -> Dict[str, object]:
        """Return a stable page of entities filtered by kind and/or file path."""
        snapshot = self.graph_store.get_snapshot(tenant_id, repo_id, commit_sha)
        nodes = snapshot.nodes
        if entity_kind:
            nodes = [node for node in nodes if node.entity_kind == entity_kind]
        if file_path:
            nodes = [node for node in nodes if node.file_path == file_path]
        nodes = sorted(nodes, key=lambda node: node.id)

        total = len(nodes)
        paged = nodes[cursor : cursor + limit]
        next_cursor = cursor + limit if cursor + limit < total else None
        return {
            "nodes": [asdict(node) for node in paged],
            "total": total,
            "next_cursor": next_cursor,
        }

    def find_relations(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        relation_type: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        cursor: int = 0,
        limit: int = 50,
    ) -> Dict[str, object]:
        """Return a stable page of relations filtered by edge attributes."""
        snapshot = self.graph_store.get_snapshot(tenant_id, repo_id, commit_sha)
        edges = snapshot.edges

        if relation_type:
            edges = [edge for edge in edges if edge.relation_type == relation_type]
        if source_id:
            edges = [edge for edge in edges if edge.source_id == source_id]
        if target_id:
            edges = [edge for edge in edges if edge.target_id == target_id]

        edges = sorted(
            edges,
            key=lambda edge: (edge.source_id, edge.relation_type, edge.target_id, edge.id),
        )

        total = len(edges)
        paged = edges[cursor : cursor + limit]
        next_cursor = cursor + limit if cursor + limit < total else None
        return {
            "edges": [asdict(edge) for edge in paged],
            "total": total,
            "next_cursor": next_cursor,
        }

    def get_subgraph(
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
        """Return a deterministic graph slice centered on file/symbol filters."""
        query = getattr(self.graph_store, "query_context", None)
        if query is None:
            snapshot = self.graph_store.get_snapshot(tenant_id, repo_id, commit_sha)
            return {
                "nodes": [asdict(node) for node in snapshot.nodes],
                "edges": [asdict(edge) for edge in snapshot.edges],
                "total": len(snapshot.nodes),
                "next_cursor": None,
            }

        return query(
            tenant_id=tenant_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            file_path=file_path,
            symbol_type=symbol_type,
            relation_type=relation_type,
            hop_limit=hop_limit,
            cursor=cursor,
            limit=limit,
        )

    def explain_relation(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        edge_id: str,
    ) -> Dict[str, object] | None:
        """Return the serialized edge payload for a specific relation id."""
        explain = getattr(self.graph_store, "explain_relation", None)
        if explain is None:
            snapshot = self.graph_store.get_snapshot(tenant_id, repo_id, commit_sha)
            for edge in snapshot.edges:
                if edge.id == edge_id:
                    return asdict(edge)
            return None
        return explain(tenant_id, repo_id, commit_sha, edge_id)
