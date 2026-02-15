# AGENTS.md (repo-graph-rag)

## Mission for this repository

This repository is the Code Mesh graph-retrieval R&D workspace.

Primary objective:
- strengthen Jet Xu's reputation through deterministic, evidence-backed graph intelligence work.

Secondary objective:
- support monetization pathways only when they do not reduce trust, quality, reproducibility, or cost control.

## Scope and precedence

- Scope: everything under `repo-graph-rag/`.
- Precedence: this file overrides the workspace-level `AGENTS.md` for this subtree.
- If a deeper subdirectory later adds its own `AGENTS.md`, that deeper file takes precedence in that subtree.

## Current repo truth (treat as facts)

1. This repo is valuable but **legacy/experimental quality**, not production-hardened.
2. Python graph build path exists and works in controlled environments, but is not plug-and-play.
3. Go analyzer subsystem is substantial and useful, but only partially integrated with Python orchestration.
4. Environment-specific assumptions and artifact hygiene issues still exist.
5. There is no clean, single cross-language production entrypoint yet.

## Source of truth vs legacy zones

Treat these as active source of truth for behavior:
- `repo_kg_maintainer/repo_knowledge_graph.py`
- `repo_kg_maintainer/code_analyze/code_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_relation.py`
- `repo_kg_maintainer/code_analyze/go_analyzer/internal/`
- `repo_kg_maintainer/code_analyze/go_analyzer/cmd/`

Treat these as legacy/prototype artifacts unless task explicitly says otherwise:
- `repo_kg_maintainer/code_analyzer-ckm0-j4kq29y4nc.py`
- `repo_kg_maintainer/test_*.ipynb`
- committed caches (`__pycache__/`) and large generated JSON fixtures
- exploratory docs and snapshots that are not referenced by active code paths

## Strategic direction rules for this repo

1. Prioritize deterministic extraction quality and reproducibility over adding broad feature surface.
2. Prefer improvements that can be externally validated (benchmarks, fixtures, regression checks).
3. Keep MCP interoperability and embeddability in mind when changing Go analyzer interfaces.
4. Do not position this work as a generic review bot feature; keep focus on deterministic context precision.
5. Optimize for maintainability and clarity so this repo can be consolidated into a future dedicated graph engine home.

## Task routing inside this repo

- Python graph orchestration / Arango behavior:
  - `repo_kg_maintainer/repo_knowledge_graph.py`
  - `repo_kg_maintainer/main.py`

- Language entity/relation extraction:
  - `repo_kg_maintainer/code_analyze/*.py`

- Go parser / traversal / graph generation:
  - `repo_kg_maintainer/code_analyze/go_analyzer/internal/analyzer/`
  - `repo_kg_maintainer/code_analyze/go_analyzer/internal/parser/`

- Go product surfaces (CLI, MCP, service):
  - `repo_kg_maintainer/code_analyze/go_analyzer/cmd/`
  - `repo_kg_maintainer/code_analyze/go_analyzer/internal/mcp/`
  - `repo_kg_maintainer/code_analyze/go_analyzer/internal/handlers/`

- Document graph enrichment research:
  - `repo_kg_maintainer/repo_doc_maintainer.py`

- Documentation and strategic positioning for this repo:
  - `repo-graph-rag/README.md`
  - `repo-graph-rag/AGENTS.md`

## Non-negotiable safety and security guardrails

1. Never commit real secrets, tokens, credentials, or private `.env` values.
2. Never copy sensitive values from notebooks/logs into code or docs.
3. If a file appears to contain secret-like literals, treat as incident risk and avoid propagating values.
4. Keep local absolute paths out of new code unless explicitly unavoidable; prefer env/config-driven paths.
5. Do not add new runtime dependence on machine-specific directories.

## Engineering guardrails

1. Minimize scope: one subsystem per task unless multi-subsystem change is explicitly required.
2. Preserve backward compatibility of graph schemas/interfaces unless a breaking change is explicitly approved.
3. If production-like behavior changes, add or update meaningful automated checks where feasible.
4. Do not silently change graph semantics (node IDs, edge types, relation meaning) without documenting why.
5. Prefer deterministic logic over opaque heuristics; when heuristics are needed, document assumptions.
6. Avoid adding notebooks into core runtime paths.
7. Avoid committing generated artifacts by default unless task explicitly requests artifact publication.

## Known high-risk implementation traps

1. `main.py` currently hardcodes a user-specific `.env` path.
2. `requirements.txt` includes low-quality entries and typo risk.
3. `CodeAnalyzer` relation extraction path is Python-heavy; JS/TS/Java relation extraction is incomplete.
4. Go analyzer is not fully wired into Python extension routing (`go` support mismatch).
5. Some service surfaces are stubs (for example `kgserv` edge processing).
6. Duplicate command files exist (`cmd/kg/main.go` and `cmd/kg/kg.go`; `cmd/importance/main.go` and `cmd/importance/importance.go`).
7. Collection initialization behavior in Python graph layer can reset persisted graph state.

When touching these areas, explicitly call out risk and migration impact in final summary.

## Validation commands

Run only commands relevant to changed paths.

### Python-side changes
From `repo_kg_maintainer/`:
- Syntax smoke:
  - `python -m py_compile main.py repo_knowledge_graph.py utils.py`
  - `python -m py_compile code_analyze/code_analyzer.py code_analyze/python_analyzer.py code_analyze/python_relation.py code_analyze/java_analyzer.py code_analyze/jsts_analyzer.py`
- Integration smoke (requires credentials + Arango + llama-github installed):
  - `python main.py`

### Go analyzer changes
From `repo_kg_maintainer/code_analyze/go_analyzer/`:
- `make test`
- `make all`
- If parser/output logic changed, run:
  - `./build/kg <PROJECT_DIRECTORY>`
  - optional follow-up: `./build/dot`, `./build/pagerank`

### MCP/LLM surfaces
Run only when touched and credentials are available:
- `./build/mcp -kg enriched_kg_with_importance.json`
- `./build/importance -graph enriched_kg.json -apikey "$OPENAI_API_KEY"`
- `./build/tagging -graph enriched_kg_with_importance.json -apikey "$OPENAI_API_KEY"`

If a command cannot be run (missing credentials/services), explicitly state that in final output.

## Documentation requirements

Update docs when any of the following change:
- architecture, entrypoints, or execution workflow,
- schema semantics or relation definitions,
- required env vars, external services, or operational assumptions,
- ownership/routing expectations.

At minimum, reflect substantial behavior changes in:
- `repo-graph-rag/README.md`

## Definition of done for changes in this repo

- Correct subsystem chosen.
- No unrelated file churn.
- Relevant checks run (or clear reason they were not runnable).
- Security and portability implications noted.
- Documentation updated for user-facing/architectural changes.
- Final summary includes risk callouts and, for strategic work, explicit reputation impact (what reusable proof this enables).
