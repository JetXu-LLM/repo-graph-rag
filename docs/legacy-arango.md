# Legacy Arango Path

This document describes the historical Python + Arango workflow that remains in
the repository for compatibility.

## Why It Still Exists

The legacy path is not kept by accident.

It preserves a real earlier method:

- repository retrieval and filtering from `llama-github`
- entity and relation extraction through the Python analyzer stack
- graph persistence in ArangoDB for exploratory querying

That history matters because the Code Mesh line did not start at snapshot v2. It
passed through `llama-github -> graph persistence -> traversal-oriented context`
experiments first.

## Current Status

- legacy
- full-build only
- not the default quickstart
- not the primary support surface

The public claim is compatibility, not feature velocity.

## Entry Points

| File | Role |
| :--- | :--- |
| `repo_kg_maintainer/main.py` | legacy CLI |
| `repo_kg_maintainer/repo_knowledge_graph.py` | Arango-backed graph builder |
| `repo_kg_maintainer/requirements-legacy.txt` | legacy dependency add-on |

## Dependency Stack

The legacy path intentionally keeps `llama-github` in the loop.

Direct dependencies:

- `requirements.txt`
- `llama-github==0.4.0`
- `python-arango`
- `python-dotenv`

What changed in the OSS cut:

- `llama-github 0.4.0` publishes its own modern dependency metadata
- the legacy path no longer re-pins `langchain`, `langchain-core`,
  `langchain-openai`, `langchain-mistralai`, or
  `langchain-text-splitters` in this repository
- repository discovery and filtering still come from `llama-github`, which is
  the part this repo intentionally wants to preserve
- the March 26, 2026 OSS validation ran the full-build path successfully
  against published `llama-github==0.4.0`

## Environment

The legacy path requires:

- GitHub access token
- local or reachable ArangoDB
- optional model tokens depending on the `llama-github` mode you use

Relevant variables are documented in `.env.example`.

## Run It

```bash
cd repo_kg_maintainer
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-legacy.txt
PYTHONPATH=. .venv/bin/python main.py \
  --repo JetXu-LLM/llama-github \
  --database repo_graph_rag_legacy_example \
  --reset-collections
```

Important behavior:

- `--repo` is explicit and required
- the database name can be supplied or derived from the repo name
- `--reset-collections` is destructive and opt-in

## What It Does

At a high level:

1. instantiate `GithubRAG` from `llama-github`
2. resolve the target repository object and structure
3. extract file and symbol entities
4. build containment and semantic relations
5. persist the graph into Arango collections

## What It Does Not Claim

- no incremental updates
- no production hardening
- no guarantee of multi-language completeness
- no guarantee that the legacy path will be the first surface to track every
  upstream change

The repository intentionally treats the failed incremental update line as a
closed experiment for the OSS release.

## When To Use It

Use the legacy path only if one of these is true:

- you want to reproduce the earlier `llama-github -> graph` workflow
- you specifically want Arango-backed persistence
- you are studying the historical method evolution of this repository

If you simply want the supported path, use Python `v2` instead.
