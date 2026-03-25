# AGENTS.md (repo-graph-rag)

## Scope

- Applies to everything under `repo-graph-rag/`
- If a deeper directory later adds its own `AGENTS.md`, the deeper file wins in
  that subtree

## Repo Truth

1. This repository is a **public research artifact**, not a production-hardened
   service.
2. The supported public path is the Python `v2` deterministic snapshot pipeline.
3. The legacy Python + Arango path is kept for **full-build only** historical
   compatibility.
4. The Go analyzer subtree is **experimental** and outside the default support
   surface.
5. Broken or environment-coupled research modules were removed from the runtime
   tip and are preserved only in history or the archive boundary.

## Source Of Truth

Treat these as the active public surfaces:

- `repo_kg_maintainer/main_v2.py`
- `repo_kg_maintainer/v2/`
- `repo_kg_maintainer/code_analyze/code_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_relation.py`

Treat these as legacy:

- `repo_kg_maintainer/main.py`
- `repo_kg_maintainer/repo_knowledge_graph.py`

Treat these as experimental:

- `repo_kg_maintainer/code_analyze/go_analyzer/`

Treat these as archived references:

- `repo_kg_maintainer/archive/`
- removed historical modules discoverable through git history

## Direction

Optimize for:

- deterministic extraction quality
- reproducibility
- explicit evidence and validation
- clarity of support boundaries
- maintainability of the Python `v2` path

Do not widen support claims casually. If graph semantics, IDs, or public
behavior change, document why and update tests/docs accordingly.

## Security And Hygiene

1. Never commit real secrets, tokens, credentials, or private `.env` values.
2. Do not copy sensitive values from notebooks, logs, or local config into code
   or docs.
3. Keep local absolute paths out of new code and documentation.
4. Do not reintroduce large generated graph artifacts into tracked `HEAD`.
5. Treat legacy and experimental paths with the same secret-hygiene standard as
   the supported path.

## Validation

Run only the checks relevant to the changed area.

### Python public surface

From `repo_kg_maintainer/`:

- `python -m py_compile main.py main_v2.py repo_knowledge_graph.py utils.py`
- `python -m py_compile code_analyze/code_analyzer.py code_analyze/python_analyzer.py code_analyze/python_relation.py code_analyze/java_analyzer.py code_analyze/jsts_analyzer.py`
- `python -m py_compile v2/api/rest.py v2/api/service.py v2/analyzer/pipeline.py v2/graph/store.py v2/mcp/toolset.py v2/evidence/benchmark.py v2/runtime.py`
- `PYTHONPATH=. python -m pytest tests -q`

### Python demo proof surface

From repo root:

- `PYTHONPATH=repo_kg_maintainer python repo_kg_maintainer/main_v2.py --tenant tenant-demo --repo examples/python-demo --commit demo-commit --source examples/python_demo_repo --output /tmp/python_demo_snapshot_v2.json`

### Legacy local smoke

Requires credentials, ArangoDB, and `requirements-legacy.txt`:

- `python main.py --repo <OWNER/REPO> --reset-collections`

### Go subtree

From `repo_kg_maintainer/code_analyze/go_analyzer/` when Go is available:

- `make test`
- `make all`

## Documentation Expectations

Update docs when changing:

- architecture or execution workflow
- schema or relation semantics
- public entrypoints or runtime assumptions
- support boundaries

At minimum reflect substantial behavior changes in:

- `README.md`
- `repo_kg_maintainer/README.md`
- relevant files under `docs/`
