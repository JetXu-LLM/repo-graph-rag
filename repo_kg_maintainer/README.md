# repo_kg_maintainer

Deterministic graph extraction runtime for Code Mesh experiments and v2 production hardening.

## v2 implementation map

- `v2/analyzer/`: modular deterministic Python analysis pipeline
  - parse/normalize
  - symbol table
  - import resolution
  - type inference
  - relation extraction
  - relation validation + provenance rules
- `v2/graph/`: graph schema migration + stores
  - non-destructive migration bootstrap
  - tenant/repo/commit scoped graph snapshots
- `v2/ingestion/`: webhook normalization, queue jobs, retry worker, invalidation planner
- `v2/api/`: managed-service API surface (REST contract adapter + service methods)
- `v2/mcp/`: MCP parity tools (`kg.find_entities`, `kg.find_relations`, `kg.get_subgraph`, `kg.explain_relation`)
- `v2/evidence/`: monthly benchmark protocol + report generators

## v2 graph schema

Node and edge identities include:
- `tenant_id`
- `repo_id`
- `commit_sha`
- `entity_kind`
- canonical symbol path

Each edge includes provenance:
- `extractor_pass`
- `rule_id`
- `source_span`
- `confidence`

Snapshot metadata includes:
- `graph_version = "2.0"`
- `schema_hash`
- deterministic canonical sorting for nodes/edges

## local v2 snapshot build

```bash
cd /Users/xujiantong/Code/repos/code-mesh/repo-graph-rag/repo_kg_maintainer
python main_v2.py --tenant tenant-a --repo demo/repo --commit local --source . --output output/graph_snapshot_v2.json
```

## REST contract (v2)

- `POST /v2/index/repository`
- `POST /v2/index/commit`
- `GET /v2/graph/{tenant}/{repo}/{sha}`
- `POST /v2/query/context`
- `GET /v2/jobs/{job_id}`

`v2/api/rest.py` exposes `create_fastapi_app(...)` when FastAPI is installed.

## tests

```bash
cd /Users/xujiantong/Code/repos/code-mesh/repo-graph-rag/repo_kg_maintainer
python -m pytest tests -q
```
