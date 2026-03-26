# Validation

This document records how the repository is meant to be validated as a public
research artifact.

## Public Test Gate

The default CI validates the supported Python public surface only.

Primary command:

```bash
PYTHONPATH=repo_kg_maintainer python -m pytest repo_kg_maintainer/tests -q
```

Relevant syntax gate:

```bash
PYTHONPATH=repo_kg_maintainer python -m py_compile \
  repo_kg_maintainer/main.py \
  repo_kg_maintainer/main_v2.py \
  repo_kg_maintainer/repo_knowledge_graph.py \
  repo_kg_maintainer/utils.py \
  repo_kg_maintainer/code_analyze/code_analyzer.py \
  repo_kg_maintainer/code_analyze/python_analyzer.py \
  repo_kg_maintainer/code_analyze/python_relation.py \
  repo_kg_maintainer/code_analyze/java_analyzer.py \
  repo_kg_maintainer/code_analyze/jsts_analyzer.py \
  repo_kg_maintainer/v2/api/rest.py \
  repo_kg_maintainer/v2/api/service.py \
  repo_kg_maintainer/v2/analyzer/pipeline.py \
  repo_kg_maintainer/v2/graph/store.py \
  repo_kg_maintainer/v2/mcp/toolset.py \
  repo_kg_maintainer/v2/evidence/benchmark.py \
  repo_kg_maintainer/v2/runtime.py
```

## Recommended Manual Checks

### Python `v2` Smoke

```bash
PYTHONPATH=repo_kg_maintainer .venv/bin/python repo_kg_maintainer/main_v2.py \
  --tenant tenant-demo \
  --repo examples/python-demo \
  --commit demo-commit \
  --source examples/python_demo_repo \
  --output /tmp/python_demo_snapshot_v2.json
```

This should:

- complete without private keys or ArangoDB
- write a canonical snapshot JSON
- print a summary with graph version, schema hash, snapshot hash, node count,
  and edge count

Expected stable demo values:

- `nodes = 14`
- `edges = 11`
- `snapshot_hash = 1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`

### Compare Against The Committed Fixture

```bash
python - <<'PY'
import json
from pathlib import Path

actual = json.loads(Path('/tmp/python_demo_snapshot_v2.json').read_text())
expected = json.loads(Path('examples/python_demo_snapshot_v2.json').read_text())

actual.pop('generated_at', None)
expected.pop('generated_at', None)

assert actual == expected
print('demo snapshot matches committed fixture')
PY
```

### Larger Local Mainline Smoke

```bash
PYTHONPATH=repo_kg_maintainer .venv/bin/python repo_kg_maintainer/main_v2.py \
  --tenant tenant-a \
  --repo repo-graph-rag/self \
  --commit local \
  --source repo_kg_maintainer \
  --output /tmp/repo_graph_rag_v2_snapshot.json
```

### Legacy Arango Smoke

```bash
PYTHONPATH=repo_kg_maintainer .venv/bin/python repo_kg_maintainer/main.py \
  --repo JetXu-LLM/llama-github \
  --database repo_graph_rag_oss_smoke_legacy \
  --reset-collections \
  --log-level WARNING
```

This requires:

- `.env` or explicit CLI values for ArangoDB
- `requirements-legacy.txt`
- published `llama-github==0.4.0`

## Latest OSS-Cut Validation

Local release validation performed on **March 26, 2026** included:

- public Python regression suite
- syntax gate for the supported surface
- real `main_v2.py` demo smoke run
- larger local `main_v2.py` smoke over `repo_kg_maintainer`
- import and instantiation smoke for published `llama-github==0.4.0`
- real legacy full-build smoke against local ArangoDB

At the time of the OSS cut:

- the public test suite passed cleanly
- the committed demo produced a deterministic `2.0` snapshot with:
  - `nodes = 14`
  - `edges = 11`
  - `snapshot_hash = 1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`
- the larger local `repo_kg_maintainer` smoke also completed successfully
- the legacy path completed successfully on published `llama-github==0.4.0`
  and the modern `langchain-core 0.3.x` provider stack
- the legacy Arango path produced non-empty collections including:
  - `Repository = 1`
  - `Module = 14`
  - `File = 60`
  - `Class = 35`
  - `Method = 182`
  - `Variable = 5`
  - `CONTAINS = 296`
  - `CALLS = 216`
  - `USES = 8`
  - `INSTANTIATES = 41`

## What Is Intentionally Not In CI

- local Arango-backed legacy validation
- Go subtree compilation and testing
- any flow that requires private API keys or machine-local services

Those checks can still be run locally, but they are not part of the public
support gate.
