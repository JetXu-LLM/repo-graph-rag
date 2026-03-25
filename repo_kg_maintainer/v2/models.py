from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


GRAPH_VERSION = "2.0"


@dataclass(frozen=True)
class RelationProvenance:
    """Evidence metadata explaining which pass and rule created an edge."""

    extractor_pass: str
    rule_id: str
    source_span: Tuple[int, int]
    confidence: float = 1.0


@dataclass(frozen=True)
class GraphNode:
    """Canonical node shape used by the public v2 graph contract."""

    id: str
    tenant_id: str
    repo_id: str
    commit_sha: str
    entity_kind: str
    symbol_path: str
    file_path: str
    name: str
    parent_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """Canonical edge shape used by the public v2 graph contract."""

    id: str
    tenant_id: str
    repo_id: str
    commit_sha: str
    source_id: str
    target_id: str
    relation_type: str
    provenance: RelationProvenance
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphSnapshot:
    """Serializable snapshot containing deterministic graph state for one commit."""

    tenant_id: str
    repo_id: str
    commit_sha: str
    graph_version: str
    schema_hash: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class IndexJobStatus:
    """Worker-visible status record for asynchronous indexing jobs."""

    job_id: str
    tenant_id: str
    repo_id: str
    commit_sha: str
    status: str
    attempts: int = 0
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
