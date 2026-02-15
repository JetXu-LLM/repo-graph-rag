# repo-graph-rag

Deterministic repository graph research workspace for Code Mesh.

This repository is a **legacy/experimental prototype**, not a production-ready service. It contains:
- a Python pipeline that builds a repository knowledge graph in ArangoDB,
- language analyzers powered by tree-sitter,
- an independent Go graph analyzer toolchain (including MCP tooling),
- exploratory notebooks and generated fixture artifacts.

## Why this repo exists

In the wider Code Mesh strategy, this repository serves as the **graph parser/traversal R&D home** while the production runtime remains in `llamapreview-core-lambda`.

Strategic intent for this repo:
- build deterministic context infrastructure that can be embedded by agents,
- prioritize reproducible graph quality over broad feature claims,
- support reputation-first evidence (benchmarks, transparent failure modes),
- move toward MCP-native interoperability.

## Current status (important)

- **State**: useful for experiments and architecture consolidation, but not cleanly productized.
- **Reliability**: mixed; some paths are robust, others are environment-coupled.
- **Source-of-truth runtime path**: `repo_kg_maintainer/repo_knowledge_graph.py` + `repo_kg_maintainer/code_analyze/`.
- **Known debt**: hardcoded local paths, incomplete relation coverage by language, duplicated files, committed generated artifacts, and notebook hygiene issues.

## Repository layout

```text
repo-graph-rag/
  .env.example
  repo_kg_maintainer/
    main.py
    repo_knowledge_graph.py
    repo_doc_maintainer.py
    utils.py
    requirements.txt
    repo_kg_schema_1.2.yaml
    LANGUAGE_NODE_MAPPINGS
    code_analyze/
      code_analyzer.py
      python_analyzer.py
      python_relation.py
      java_analyzer.py
      jsts_analyzer.py
      docs/
      go_analyzer/
        cmd/
        internal/
        knowledge_graph_examples/
        Makefile
        go.mod
    test_*.ipynb
```

## Python architecture deep dive

### 1) Orchestration entrypoint

- `repo_kg_maintainer/main.py`
  - loads env vars,
  - instantiates `GithubRAG`,
  - fetches a target repository and structure,
  - creates `RepoKnowledgeGraph`,
  - runs `build_knowledge_graph`.

### Critical caveat
`main.py` hardcodes:
- `load_dotenv('/Users/xujiantong/Code/repos/repo-graph-rag/.env')`

This path is machine-specific and does not match this workspace path by default.

### 2) Graph persistence and update engine

- `repo_kg_maintainer/repo_knowledge_graph.py` is the main persistence layer.
- Backing DB: ArangoDB collections per entity/edge type.
- Core responsibilities:
  - create/upsert Repository, Module, File, Class, Method, Interface, Enum, Variable documents,
  - build `CONTAINS` hierarchy,
  - derive and upsert semantic relations (`CALLS`, `INHERITS`, `USES`, `IMPORTS`, etc.),
  - support full builds and incremental updates.

### Build modes
- **Full build** (`incremental=False`):
  1. `process_repo_structure` extracts entities + containment,
  2. `process_repo_relations` extracts semantic edges.
- **Incremental** (`incremental=True`):
  1. file-level diff detection by timestamp/hash,
  2. entity-level change detection,
  3. selective relation reprocessing including reverse dependencies.

### Important behavior
`_init_collections()` currently deletes and recreates collections when initializing. This effectively resets DB state and limits practical incremental reuse unless changed.

### 3) Analyzer abstraction

- `repo_kg_maintainer/code_analyze/code_analyzer.py`
  - defines canonical dataclasses/enums (`EntityInfo`, `RelationInfo`, `EntityType`, `RelationType`),
  - routes by file extension to language analyzers,
  - exposes:
    - `get_file_entities(...)`
    - `get_file_relations(...)`

### Implemented coverage
- Entity extraction:
  - Python (`python_analyzer.py`)
  - Java (`java_analyzer.py`)
  - JavaScript/TypeScript/TSX (`jsts_analyzer.py`)
- Relation extraction:
  - Python only (`python_relation.py`) is actively wired.
  - Java/JS/TS relation paths are not wired in `get_file_relations`.

### Additional caveat
- `SUPPORTED_EXTENSIONS` in `CodeAnalyzer` omits `go`, so Python pipeline does not invoke the Go analyzer.
- `get_file_relations(...)` returns a dict for unsupported files, while callers expect list-like relation objects.

### 4) Python relation engine

- `repo_kg_maintainer/code_analyze/python_relation.py`
- Scope:
  - inheritance,
  - instantiation,
  - direct/attribute/chained calls,
  - `super()` handling,
  - import alias resolution,
  - parameter/variable/object type inference,
  - global variable/function relations,
  - relation dedup and validation.

This file is large and heuristic-heavy; it is the most complex Python analysis component in the repo.

### 5) Documentation graph augmentation

- `repo_kg_maintainer/repo_doc_maintainer.py`
- Adds document nodes/edges into ArangoDB by:
  - crawling markdown files,
  - chunking documents,
  - candidate entity matching,
  - LLM-assisted mention detection and documentation generation.

Dependencies include Gemini + BeautifulSoup + markdown parsing. This workflow is powerful but currently strongly environment-dependent.

## Go analyzer subsystem deep dive

Located at `repo_kg_maintainer/code_analyze/go_analyzer/`.

This is an independent Go toolchain, not yet fully integrated into the Python orchestration path.

### Core packages

- `internal/analyzer/`
  - graph model definitions (`StructuredKnowledgeGraph`, `WeightedKnowledgeGraph`, node/edge types),
  - AST node/edge construction,
  - call graph extraction (`func_callgraph.go`),
  - utility algorithms (DFS path discovery, common path counting, graph persistence).

- `internal/parser/`
  - tree-sitter parsing wrapper,
  - staged AST processing pipeline (`package -> types -> other nodes`).

- `internal/llm/`
  - LLM client interface,
  - OpenAI client,
  - hierarchical importance analyzer for package/struct/function scoring.

- `internal/mcp/`
  - MCP tool handlers for package/function/struct/interface browsing and importance retrieval.

- `internal/handlers/`
  - Gin HTTP handler stubs used by `kgserv`.

### CLI binaries in `cmd/`

- `kg`: parse Go repository -> emit `knowledge_graph.json`.
- `callgraph`: print function call relationships.
- `dot`: convert `knowledge_graph.json` -> `output.dot` for Graphviz.
- `pagerank`: compute weighted/enriched graph -> `enriched_kg.json`.
- `importance`: LLM-based importance scoring -> `enriched_kg_with_importance.json`.
- `tagging`: LLM tag assignment + path mining outputs.
- `mcp`: stdio MCP server over weighted graph.
- `kgserv`: HTTP server (currently partial; edges endpoint TODO).

### Duplicate command files

`cmd/kg/main.go` and `cmd/kg/kg.go` are duplicated.
`cmd/importance/main.go` and `cmd/importance/importance.go` are duplicated.

## Setup and execution

### Prerequisites

- Python 3.10+ recommended
- ArangoDB reachable from local machine
- Go (for `go_analyzer`)
- Access to `llama-github` package in local environment

### Environment variables

Use `.env.example` as reference:
- `GITHUB_ACCESS_TOKEN`
- `OPENAI_API_KEY` (used by some workflows)
- `HUGGINGFACE_TOKEN`
- `MISTRAL_API_KEY`
- `JINA_API_KEY`
- `ARANGODB_HOST`
- `ARANGODB_USERNAME`
- `ARANGODB_PASSWORD`

### Python install

From `repo_kg_maintainer/`:

```bash
pip install -r requirements.txt
```

Note: `requirements.txt` currently includes typos/weak pins (for example `tree-sitte`) and may require manual correction.

### Python unit tests (deterministic graph extraction)

From `repo_kg_maintainer/`:

```bash
python -m pytest tests -q
```

The Python unit suite focuses on reproducible graph extraction behavior, including:
- analyzer dispatch and extension routing (`code_analyzer.py`),
- Python entity extraction robustness (docstrings, decorators, nesting, complexity),
- Python relation extraction coverage (imports, inheritance, instantiation, call resolution),
- knowledge-graph helper regressions for change detection and key generation.

### Production v2 foundation (managed-service-first)

The repository now includes a v2 production foundation under `repo_kg_maintainer/v2/`:
- deterministic modular Python analysis passes (parse/symbol/import/type/relation/validation),
- graph schema v2 IDs (`tenant_id|repo_id|commit_sha|entity_kind|symbol_path`),
- relation provenance (`extractor_pass`, `rule_id`, `source_span`, `confidence`),
- non-destructive schema bootstrap and tenant-scoped graph storage adapters,
- webhook normalization + delivery dedup + queue worker + retry/idempotency flow,
- REST contract service methods and MCP parity tools.

Build a local deterministic v2 snapshot:

```bash
cd repo_kg_maintainer
python main_v2.py --tenant tenant-a --repo demo/repo --commit local --source . --output output/graph_snapshot_v2.json
```

### Build KG with Python orchestrator

```bash
cd repo_kg_maintainer
python main.py
```

If it fails immediately, first fix:
- hardcoded `.env` path in `main.py`,
- local availability of `llama_github` module,
- ArangoDB credentials.

### Go analyzer build and run

```bash
cd repo_kg_maintainer/code_analyze/go_analyzer
make all

# Build a graph from a Go project
./build/kg <PROJECT_DIRECTORY>

# Generate dot
./build/dot

# Compute weights
./build/pagerank

# MCP server on stdio
./build/mcp -kg enriched_kg_with_importance.json
```

Optional LLM-powered steps:

```bash
./build/importance -graph enriched_kg.json -apikey "$OPENAI_API_KEY"
./build/tagging -graph enriched_kg_with_importance.json -apikey "$OPENAI_API_KEY"
```

### Artifacts and outputs

Common generated files:
- `knowledge_graph.json`
- `output.dot`
- `enriched_kg.json`
- `enriched_kg_with_importance.json`
- `enriched_kg_with_importance_with_tags.json`
- path mining outputs (`paths.json`, `common_paths.json`)

Example artifacts are committed under:
- `repo_kg_maintainer/code_analyze/go_analyzer/knowledge_graph_examples/`

These examples currently include machine-specific absolute file paths.

## Known issues and maintenance traps

1. Hardcoded local paths in Python entrypoints make setup brittle.
2. `requirements.txt` quality is not production-grade.
3. Python relation extraction is strong for Python but incomplete for Java/JS/TS.
4. Go analyzer is not wired into Python `CodeAnalyzer` extension routing.
5. Some service surfaces are stubs (`kgserv` edge handling).
6. Legacy files coexist with active code (`code_analyzer-ckm0-*.py`, notebook variants).
7. Generated/derived artifacts (`__pycache__`, large JSON fixtures) are tracked in repo.
8. Historical notebooks include sensitive token-style literals and should be treated as unsafe historical artifacts.

## Source of truth vs legacy guidance

Treat as source-of-truth for active graph behavior:
- `repo_kg_maintainer/repo_knowledge_graph.py`
- `repo_kg_maintainer/code_analyze/code_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_analyzer.py`
- `repo_kg_maintainer/code_analyze/python_relation.py`
- `repo_kg_maintainer/code_analyze/go_analyzer/internal/*`

Treat as legacy/prototype artifacts unless explicitly revived:
- `repo_kg_maintainer/code_analyzer-ckm0-j4kq29y4nc.py`
- most `test_*.ipynb` notebooks
- massive fixture output dumps and local caches

## Suggested next hardening milestones

1. Remove hardcoded paths and move all runtime config to env/config files.
2. Clean dependency definitions and add reproducible lock strategy.
3. Define one canonical CLI for Python pipeline (full + incremental modes).
4. Integrate Go analyzer pathway into main orchestration (or explicitly decouple as standalone).
5. Add CI smoke checks for both Python and Go subpaths.
6. Sanitize notebooks and remove committed secret-like literals.
7. Reduce duplicate command files and generated artifact churn.

## Reputation-first note

For strategic alignment, prioritize work that produces reusable, verifiable artifacts:
- deterministic extraction benchmarks,
- failure-case corpora,
- transparent before/after quality diffs,
- stable MCP interfaces for external adopters.
