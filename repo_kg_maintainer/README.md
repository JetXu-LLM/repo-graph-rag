# repo_kg_maintainer

Public Python runtime for the supported deterministic `v2` graph snapshot path.

This directory contains the Python-first support surface that is intended to be
run by other people:

- deterministic analyzer passes
- canonical snapshot serialization
- in-memory query / MCP parity foundations
- a legacy Arango full-build path kept for historical compatibility

## Start With The Public Demo

From `repo_kg_maintainer/`:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python main_v2.py \
  --tenant tenant-demo \
  --repo examples/python-demo \
  --commit demo-commit \
  --source ../examples/python_demo_repo \
  --output /tmp/python_demo_snapshot_v2.json
```

Expected stable result for the committed demo:

- `graph_version = "2.0"`
- `nodes = 14`
- `edges = 11`
- `snapshot_hash = 1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`

The committed expected snapshot is:

- `../examples/python_demo_snapshot_v2.json`

Comparison instructions live in:

- [../docs/validation.md](../docs/validation.md)

## What `main_v2.py` Actually Does

The public CLI:

- walks a local repository directory
- collects Python source files with stable ordering
- skips hidden and generated directories such as `.git`, `.venv`, `venv`,
  `node_modules`, `build`, `dist`, and `__pycache__`
- runs the pass-based analyzer pipeline
- writes a canonical graph snapshot JSON file
- prints a summary with graph version, schema hash, snapshot hash, node count,
  and edge count

## Public Python Contract

Important public-facing interfaces:

- `main_v2.py`
- `v2/analyzer/pipeline.py`
- `v2/api/service.py`
- `v2/graph/store.py`
- `v2/mcp/toolset.py`
- `v2/serializer.py`
- `v2/models.py`

These files define the public research contract more accurately than the legacy
Arango path.

## Determinism Guarantees

The current v2 contract is narrow but deliberate:

- node IDs are derived from tenant / repo / commit / entity kind / symbol path
- edge IDs are derived from source / relation type / target / provenance rule
- snapshots are canonicalized before serialization
- snapshot hashes intentionally ignore `generated_at`
- every edge includes provenance with extractor pass, rule ID, source span, and
  confidence

## Install

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Legacy extras for the Arango path:

```bash
.venv/bin/pip install -r requirements-legacy.txt
```

`requirements-legacy.txt` is the legacy dependency add-on for the historical
`llama-github` integration. It now stays small on purpose: ArangoDB support,
dotenv loading, and published `llama-github==0.4.0`. The LangChain provider
packages are resolved from `llama-github`'s own metadata instead of being
re-pinned here.

## Tests And Validation

Run the supported regression suite:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

Useful manual checks:

- run `main_v2.py` on `../examples/python_demo_repo`
- compare the output against `../examples/python_demo_snapshot_v2.json`
- run `main_v2.py` on this directory for a larger local smoke
- use the in-memory service/toolset surfaces in `v2/api/service.py` and
  `v2/mcp/toolset.py`

More detailed validation notes live in:

- [../docs/python-v2.md](../docs/python-v2.md)
- [../docs/demo-walkthrough.md](../docs/demo-walkthrough.md)
- [../docs/snapshot-schema.md](../docs/snapshot-schema.md)
- [../docs/validation.md](../docs/validation.md)

## Legacy Path

`main.py` and `repo_knowledge_graph.py` remain available as a legacy,
Arango-backed full-build workflow.

Important constraints:

- full-build only
- incremental updates are not a supported public capability
- destructive collection reset requires explicit opt-in
- legacy install depends on published `llama-github==0.4.0` and its declared
  modern LangChain provider dependencies
- legacy repository discovery and filtering intentionally continue to come from
  `llama-github`

If you use the legacy path against an existing database, prefer a fresh
database name or explicit `--reset-collections` when you need a clean rebuild.

## Documentation

- [../docs/README.md](../docs/README.md)
- [../docs/architecture.md](../docs/architecture.md)
- [../docs/python-v2.md](../docs/python-v2.md)
- [../docs/demo-walkthrough.md](../docs/demo-walkthrough.md)
- [../docs/legacy-arango.md](../docs/legacy-arango.md)
- [../docs/go-experimental.md](../docs/go-experimental.md)

## Archived Research

Historical, non-supported research components were removed from the runtime tip.
See [archive/README.md](archive/README.md).
