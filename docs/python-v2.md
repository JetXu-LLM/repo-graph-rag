# Python v2

This document describes the supported public path for `repo-graph-rag`.

## Scope

The Python `v2` path is the supported contract for this repository:

- deterministic graph snapshot generation
- canonical node and edge identity
- provenance-bearing relations
- in-memory query and MCP parity foundations

It is the path that the top-level README, tests, and CI are centered around.

## Entry Points

| File | Role |
| :--- | :--- |
| `repo_kg_maintainer/main_v2.py` | CLI for local snapshot generation |
| `repo_kg_maintainer/v2/analyzer/pipeline.py` | deterministic analysis pipeline |
| `repo_kg_maintainer/v2/api/service.py` | indexing and query service contract |
| `repo_kg_maintainer/v2/graph/store.py` | snapshot persistence backends |
| `repo_kg_maintainer/v2/mcp/toolset.py` | deterministic entity and relation browsing |

## Quickstart

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r repo_kg_maintainer/requirements.txt
PYTHONPATH=repo_kg_maintainer .venv/bin/python repo_kg_maintainer/main_v2.py \
  --tenant tenant-demo \
  --repo examples/python-demo \
  --commit demo-commit \
  --source examples/python_demo_repo \
  --output /tmp/python_demo_snapshot_v2.json
```

The CLI prints a JSON summary with:

- `output`
- `graph_version`
- `schema_hash`
- `snapshot_hash`
- `nodes`
- `edges`

For the committed demo, the stable snapshot hash is:

- `1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`

## What The CLI Collects

`main_v2.py` walks the local repository root and collects Python files with
stable relative-path ordering.

It intentionally skips hidden or generated directories such as:

- `.git`
- `.venv`
- `venv`
- `node_modules`
- `build`
- `dist`
- `__pycache__`

That means the documented quickstart is safe even when the virtual environment
is created inside the repository.

## Pass Structure

The current pass pipeline is:

1. parse and normalize source files
2. build the symbol table and file/entity inventory
3. resolve imports
4. infer types needed for relation resolution
5. extract relations
6. validate and canonicalize the resulting graph

The implementation is intentionally pass-based rather than prompt-driven. This
keeps the extraction logic inspectable and testable.

## Deterministic Guarantees

The current public contract guarantees:

- `graph_version = "2.0"`
- stable node IDs for the same tenant / repo / commit / symbol path
- stable edge IDs for the same source / relation / target / provenance rule
- canonical sorting of nodes and edges before serialization
- explicit relation provenance on every edge

It does not claim semantic completeness across all languages.

## Query And Service Surfaces

Two deterministic query layers are part of the public Python surface:

### `GraphServiceV2`

- queue indexing jobs
- retrieve stored snapshots
- query graph context deterministically
- inspect job status

### `GraphMCPToolsetV2`

- page entities
- page relations
- request filtered subgraphs
- explain a single relation by edge ID

Both operate over snapshot state rather than over ad hoc retrieval output.

## Tests

The supported regression suite lives under `repo_kg_maintainer/tests/`.

Key coverage areas:

- analyzer behavior
- serializer and ID determinism
- pipeline determinism
- ingestion and service behavior
- MCP and evidence helpers
- legacy helper behavior that still matters for compatibility

Run it with:

```bash
PYTHONPATH=repo_kg_maintainer .venv/bin/python -m pytest repo_kg_maintainer/tests -q
```

## Known Limits

- public extraction support is Python-first
- Java / JS / TS entity extraction exists but is not positioned as complete
- the mainline is a research runtime, not a hardened deployment product
- the legacy path is intentionally separate from the public v2 contract
