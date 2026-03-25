# Analyzer Integration Notes

This directory previously contained an integration proposal centered on a
service-style Go analyzer workflow.

That is no longer the public truth of the repository.

## Current Reality

- the supported public extraction path is the Python `v2` pipeline
- the legacy Python + Arango path still uses the local `CodeAnalyzer`
  abstraction
- the Go subtree exists, but it is experimental and not wired into the public
  Python `v2` contract

## What Matters For New Analyzer Work

If a future language analyzer is added to the supported surface, it should match
these constraints:

- deterministic entity identity
- deterministic edge identity
- explicit provenance on extracted relations
- narrow, testable public claims
- no environment-coupled hidden service requirement

## What This Means For Go

The Go analyzer in this repository should currently be read as:

- a research prototype
- a useful reference for graph-analysis ideas
- not a supported extractor integration surface

For the repo-level statement of support boundaries, see:

- `../../../docs/architecture.md`
- `../../../docs/go-experimental.md`
- `repo_kg_maintainer/code_analyze/go_analyzer/readme.md`
