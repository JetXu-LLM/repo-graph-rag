from __future__ import annotations

from v2.ids import build_edge_id, build_node_id, canonical_symbol_path
from v2.models import GraphEdge, GraphNode, GraphSnapshot, RelationProvenance
from v2.serializer import canonicalize_snapshot, compute_snapshot_hash, get_schema_hash


def test_node_id_and_symbol_path_include_required_dimensions() -> None:
    symbol = canonical_symbol_path("src/mod.py", "Service", "run")
    node_id = build_node_id("tenant-a", "repo-x", "abc123", "Method", symbol)

    assert symbol == "src/mod.py::Service.run"
    assert node_id == "tenant-a|repo-x|abc123|Method|src/mod.py::Service.run"


def test_edge_id_is_deterministic() -> None:
    first = build_edge_id("node-a", "CALLS", "node-b", "calls.function.dispatch")
    second = build_edge_id("node-a", "CALLS", "node-b", "calls.function.dispatch")

    assert first == second
    assert first.startswith("edge|")


def test_snapshot_canonicalization_and_hash_are_stable() -> None:
    provenance = RelationProvenance(
        extractor_pass="relation_extraction",
        rule_id="calls.function.dispatch",
        source_span=(10, 2),
        confidence=0.91,
    )
    snapshot = GraphSnapshot(
        tenant_id="tenant-a",
        repo_id="repo-x",
        commit_sha="abc123",
        graph_version="2.0",
        schema_hash="",
        nodes=[
            GraphNode(
                id="n2",
                tenant_id="tenant-a",
                repo_id="repo-x",
                commit_sha="abc123",
                entity_kind="Method",
                symbol_path="src/b.py::B.run",
                file_path="src/b.py",
                name="run",
            ),
            GraphNode(
                id="n1",
                tenant_id="tenant-a",
                repo_id="repo-x",
                commit_sha="abc123",
                entity_kind="Class",
                symbol_path="src/a.py::A",
                file_path="src/a.py",
                name="A",
            ),
        ],
        edges=[
            GraphEdge(
                id="e2",
                tenant_id="tenant-a",
                repo_id="repo-x",
                commit_sha="abc123",
                source_id="n2",
                target_id="n1",
                relation_type="CALLS",
                provenance=provenance,
            ),
            GraphEdge(
                id="e1",
                tenant_id="tenant-a",
                repo_id="repo-x",
                commit_sha="abc123",
                source_id="n1",
                target_id="n2",
                relation_type="INSTANTIATES",
                provenance=provenance,
            ),
        ],
    )

    canonicalize_snapshot(snapshot)
    first_hash = compute_snapshot_hash(snapshot)
    second_hash = compute_snapshot_hash(snapshot)

    assert snapshot.schema_hash == get_schema_hash()
    assert [node.id for node in snapshot.nodes] == ["n1", "n2"]
    assert [edge.id for edge in snapshot.edges] == ["e1", "e2"]
    assert first_hash == second_hash
