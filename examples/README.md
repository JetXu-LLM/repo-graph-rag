# Examples

This directory contains the tiny public proof artifacts used to demonstrate that
the supported Python `v2` path is real, deterministic, and easy to verify.

Current contents:

- `python_demo_repo/`: a tiny Python repository used for smoke runs
- `python_demo_snapshot_v2.json`: the committed expected snapshot for that demo

The example is intentionally small enough to inspect by hand and strong enough
to exercise:

- imports
- class and method extraction
- instantiation
- method calls
- edge provenance

Expected stable demo snapshot:

- `graph_version = "2.0"`
- `nodes = 14`
- `edges = 11`
- `snapshot_hash = 1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e`
