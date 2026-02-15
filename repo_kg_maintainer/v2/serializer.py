from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Dict

from v2.ids import build_schema_hash
from v2.models import GRAPH_VERSION, GraphEdge, GraphNode, GraphSnapshot


_SCHEMA_SIGNATURE = {
    "graph_version": GRAPH_VERSION,
    "node_fields": [
        "id",
        "tenant_id",
        "repo_id",
        "commit_sha",
        "entity_kind",
        "symbol_path",
        "file_path",
        "name",
        "parent_name",
        "metadata",
    ],
    "edge_fields": [
        "id",
        "tenant_id",
        "repo_id",
        "commit_sha",
        "source_id",
        "target_id",
        "relation_type",
        "provenance",
        "metadata",
    ],
}


def get_schema_hash() -> str:
    signature_text = json.dumps(_SCHEMA_SIGNATURE, sort_keys=True, separators=(",", ":"))
    return build_schema_hash(signature_text)


def canonicalize_snapshot(snapshot: GraphSnapshot) -> GraphSnapshot:
    snapshot.nodes = sorted(snapshot.nodes, key=lambda node: node.id)
    snapshot.edges = sorted(
        snapshot.edges,
        key=lambda edge: (edge.source_id, edge.relation_type, edge.target_id, edge.id),
    )
    snapshot.schema_hash = get_schema_hash()
    snapshot.graph_version = GRAPH_VERSION
    return snapshot


def snapshot_to_dict(snapshot: GraphSnapshot) -> Dict[str, object]:
    canonicalize_snapshot(snapshot)
    return {
        "tenant_id": snapshot.tenant_id,
        "repo_id": snapshot.repo_id,
        "commit_sha": snapshot.commit_sha,
        "graph_version": snapshot.graph_version,
        "schema_hash": snapshot.schema_hash,
        "generated_at": snapshot.generated_at,
        "nodes": [asdict(node) for node in snapshot.nodes],
        "edges": [asdict(edge) for edge in snapshot.edges],
    }


def compute_snapshot_hash(snapshot: GraphSnapshot) -> str:
    payload = snapshot_to_dict(snapshot)
    payload.pop("generated_at", None)
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
