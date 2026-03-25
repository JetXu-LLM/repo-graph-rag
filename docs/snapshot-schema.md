# Snapshot Schema

The public Python mainline emits a deterministic JSON snapshot.

This document describes the public data contract for that artifact.

## Top-Level Shape

Each snapshot contains:

| Field | Meaning |
| :--- | :--- |
| `tenant_id` | logical tenant namespace |
| `repo_id` | repository identifier |
| `commit_sha` | commit or revision identity supplied by the caller |
| `graph_version` | schema family, currently `2.0` |
| `schema_hash` | canonical hash of the schema signature |
| `generated_at` | serialization timestamp |
| `nodes` | canonical list of graph nodes |
| `edges` | canonical list of graph edges |

## `GraphNode`

Each node contains:

| Field | Meaning |
| :--- | :--- |
| `id` | deterministic node identifier |
| `tenant_id` | tenant namespace |
| `repo_id` | repository identity |
| `commit_sha` | commit identity |
| `entity_kind` | entity type such as `File`, `Class`, or `Method` |
| `symbol_path` | canonical symbol path used for identity |
| `file_path` | relative source file path |
| `name` | entity display name |
| `parent_name` | parent entity name when applicable |
| `metadata` | additional deterministic metadata |

## `GraphEdge`

Each edge contains:

| Field | Meaning |
| :--- | :--- |
| `id` | deterministic edge identifier |
| `tenant_id` | tenant namespace |
| `repo_id` | repository identity |
| `commit_sha` | commit identity |
| `source_id` | source node ID |
| `target_id` | target node ID |
| `relation_type` | relation label such as `CALLS` or `INSTANTIATES` |
| `provenance` | extraction evidence for the edge |
| `metadata` | relation metadata that is not part of provenance |

## `RelationProvenance`

Every edge carries provenance:

| Field | Meaning |
| :--- | :--- |
| `extractor_pass` | pass that created the edge |
| `rule_id` | rule responsible for the extraction |
| `source_span` | source-code span or location tuple |
| `confidence` | extraction confidence score |

This is a core design choice. The graph is not just a bag of relations; it
stores how those relations were produced.

## ID Semantics

### Node IDs

Node IDs are built from:

- `tenant_id`
- `repo_id`
- `commit_sha`
- `entity_kind`
- canonical `symbol_path`

That means the same symbol in the same repository state produces the same node
ID across repeated runs.

### Edge IDs

Edge IDs are built from:

- `source_id`
- `relation_type`
- `target_id`
- provenance `rule_id`

This allows the same source and target to still produce distinct edges when
they come from different extraction rules.

## Canonicalization Rules

Before serialization:

- nodes are sorted by `id`
- edges are sorted by `source_id`, `relation_type`, `target_id`, then `id`
- `graph_version` is normalized to `2.0`
- `schema_hash` is recomputed from the schema signature

`generated_at` is intentionally excluded from snapshot hashing so repeated runs
can still compare equal at the graph-content level.

## Example

```json
{
  "tenant_id": "tenant-demo",
  "repo_id": "examples/python-demo",
  "commit_sha": "demo-commit",
  "graph_version": "2.0",
  "schema_hash": "...",
  "generated_at": "2026-03-25T00:00:00+00:00",
  "nodes": [
    {
      "id": "tenant-demo|examples/python-demo|demo-commit|Method|service.py::TaskService.execute",
      "tenant_id": "tenant-demo",
      "repo_id": "examples/python-demo",
      "commit_sha": "demo-commit",
      "entity_kind": "Method",
      "symbol_path": "service.py::TaskService.execute",
      "file_path": "service.py",
      "name": "execute",
      "parent_name": "TaskService",
      "metadata": {
        "complexity": 1,
        "is_exported": true
      }
    }
  ],
  "edges": [
    {
      "id": "edge|...",
      "tenant_id": "tenant-demo",
      "repo_id": "examples/python-demo",
      "commit_sha": "demo-commit",
      "source_id": "tenant-demo|examples/python-demo|demo-commit|File|service.py::_file_",
      "target_id": "tenant-demo|examples/python-demo|demo-commit|Class|workers.py::Worker",
      "relation_type": "IMPORTS",
      "provenance": {
        "extractor_pass": "import_resolution",
        "rule_id": "imports.module.symbol",
        "source_span": [0, 0],
        "confidence": 0.98
      },
      "metadata": {
        "import_symbol": "Worker"
      }
    }
  ]
}
```

## Stability Promise

The repository is free to add internal implementation details, but the public
meaning of the current v2 fields should not change casually. If node identity,
edge identity, provenance semantics, or canonical ordering change, that is a
public-contract change and should be treated as such.
