# Go Experimental Subtree

This document describes the scope of the Go analyzer subtree that remains in the
repository.

## Position

The Go subtree is experimental.

That means:

- it is not part of the default quickstart
- it is not the main support promise of the repository
- it is not the place to start if you only want the working public path

The working public path is still the Python `v2` snapshot pipeline.

## Why Keep It

The subtree remains valuable because it contains real research work around:

- AST-driven graph construction for Go repositories
- weighted graph analysis and ranking
- MCP-oriented browsing over graph artifacts

It is preserved as evidence of a serious branch of work, not as a marketing
checkbox.

## Main Components

| Area | Purpose |
| :--- | :--- |
| `internal/analyzer/` | graph construction, traversal, node and edge logic |
| `internal/parser/` | Go source parsing pipeline |
| `internal/mcp/` | graph browsing handlers for MCP-style surfaces |
| `internal/llm/` | importance-scoring experiments |
| `cmd/` | buildable CLI entrypoints such as `kg`, `callgraph`, `pagerank`, `mcp` |

## Historical Commands

From `repo_kg_maintainer/code_analyze/go_analyzer/`:

```bash
make test
make all
```

If the subtree builds in your environment, the most important binary is usually
`kg`, because it is the entrypoint that emits the Go knowledge graph used by the
other experiments.

## Why It Is Not Public Mainline

The repository does not currently claim:

- stable builds across environments
- stable API contracts for the Go surfaces
- parity with the Python `v2` graph contract
- CI-backed support for the subtree

Those are deliberate non-claims, not forgotten TODOs.

## Practical Reading Strategy

If you are evaluating the repository:

1. understand Python `v2` first
2. read the Go subtree only if you care about adjacent graph-analysis research
3. treat it as an experimental branch, not as a promise of supported behavior
