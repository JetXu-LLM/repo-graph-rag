# Go Analyzer (Experimental)

This subtree preserves a substantial Go-based analyzer prototype that was
originally developed as an adjacent exploration to the Python orchestration
path.

## Status

- experimental
- not part of the default quickstart
- not part of the default CI gate
- not positioned as a supported public surface

## Why It Still Exists

The Go subtree still carries real research value:

- AST-driven graph construction research for Go repositories
- call graph and weighted graph experiments over repository structure
- MCP-oriented exploration over graph outputs

It is useful as a design reference and as a possible future extraction line, but
it is not the public center of this repository.

## What Is Here

- `internal/analyzer/`: graph construction, call graph, node and edge logic
- `internal/parser/`: parser orchestration over Go source trees
- `internal/mcp/`: MCP-oriented graph query handlers
- `internal/llm/`: importance-scoring experiments
- `cmd/`: CLI entrypoints such as `kg`, `pagerank`, `importance`, `tagging`,
  and `mcp`

## If You Want To Explore It

From this directory, the historical build commands are:

```bash
make test
make all
```

If a Go toolchain is available and the subtree builds cleanly in your
environment, the main artifact to inspect is the `kg` binary, which emits a Go
repository knowledge graph for downstream experiments.

## What Is Intentionally Not Claimed

- stable build guarantees across environments
- stable public API contracts
- production support
- parity with the Python v2 path

## Relationship To The Rest Of The Repo

- the Python `v2` path is the supported public surface
- the legacy Arango path is historical compatibility
- this Go subtree is an adjacent experimental branch of the same broader
  Code Mesh research effort

See [../../../docs/go-experimental.md](../../../docs/go-experimental.md)
for the repo-level statement of support boundaries.
