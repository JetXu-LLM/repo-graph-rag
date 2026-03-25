# Demo Walkthrough

This document walks through the committed public proof artifact:

- source: `examples/python_demo_repo/`
- expected snapshot: `examples/python_demo_snapshot_v2.json`

## Why This Demo Exists

The demo is intentionally small enough to inspect manually and rich enough to
prove the supported Python path is doing real graph work.

It exercises:

- file nodes
- class and method nodes
- local import resolution
- instantiation
- method and function calls
- provenance-bearing edges

## Demo Source

### `app.py`

```python
from service import TaskService

class DemoApp:
    def run(self) -> str:
        service = TaskService()
        return service.execute("  demo  ")
```

### `service.py`

```python
from helpers import finalize
from workers import Worker

class TaskService:
    def execute(self, raw_value: str) -> str:
        worker = Worker()
        result = worker.work(raw_value)
        return finalize(result)
```

### `helpers.py`

```python
class Formatter:
    def format(self, value: str) -> str:
        return f"[{value}]"

def finalize(value: str) -> str:
    formatter = Formatter()
    return formatter.format(value)
```

### `workers.py`

```python
class Worker:
    def prepare(self, value: str) -> str:
        return value.strip().upper()

    def work(self, value: str) -> str:
        prepared = self.prepare(value)
        return f"WORKER:{prepared}"
```

## Expected Snapshot Summary

For:

- `tenant_id = tenant-demo`
- `repo_id = examples/python-demo`
- `commit_sha = demo-commit`

The committed snapshot is expected to have:

- `graph_version = 2.0`
- `nodes = 14`
- `edges = 11`
- `snapshot_hash = 1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`

## Representative Nodes

Examples from the committed snapshot:

- `Class | service.py::TaskService`
- `Method | service.py::TaskService.execute`
- `Class | workers.py::Worker`
- `Method | helpers.py::finalize`
- `File | service.py::_file_`

The file nodes matter because they allow the graph to represent import edges in
addition to symbol-to-symbol semantic edges.

## Representative Edges

### Import edges

- `service.py::_file_ --IMPORTS--> workers.py::Worker`
- `service.py::_file_ --IMPORTS--> helpers.py::finalize`
- `app.py::_file_ --IMPORTS--> service.py::TaskService`

Rule ID:

- `imports.module.symbol`

### Instantiation edges

- `DemoApp.run --INSTANTIATES--> TaskService`
- `TaskService.execute --INSTANTIATES--> Worker`
- `finalize --INSTANTIATES--> Formatter`

Rule ID:

- `instantiates.class.call`

### Call edges

- `DemoApp.run --CALLS--> TaskService.execute`
- `TaskService.execute --CALLS--> Worker.work`
- `TaskService.execute --CALLS--> finalize`
- `Worker.work --CALLS--> Worker.prepare`

Rule ID:

- `calls.function.dispatch`

## Provenance Example

Every edge includes provenance. A typical call edge looks like:

```json
{
  "relation_type": "CALLS",
  "provenance": {
    "extractor_pass": "relation_extraction",
    "rule_id": "calls.function.dispatch",
    "source_span": [8, 18],
    "confidence": 0.9
  }
}
```

That is the repo's main point in miniature: deterministic graph edges with
explicit evidence about how they were extracted.

## How To Verify It Yourself

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

Then compare the generated snapshot against the committed reference while
ignoring `generated_at`.
