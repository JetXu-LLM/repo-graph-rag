# Contributing

This repository is a public research artifact. Contributions are welcome, but
the bar is clarity and reproducibility, not feature sprawl.

## What Good Contributions Improve

- deterministic extraction quality
- reproducibility and validation
- clarity of support boundaries
- maintainability of the Python `v2` path
- usefulness of public documentation

## Scope Discipline

Before opening a PR:

- keep scope tight
- avoid unrelated cleanup
- do not widen public support claims unless code, tests, and docs move together
- treat the Go subtree as experimental unless the change is explicitly about
  that area
- do not revive archived or legacy behavior as if it were public mainline

## Testing Expectations

For Python changes, run the relevant subset of:

```bash
PYTHONPATH=repo_kg_maintainer python -m pytest repo_kg_maintainer/tests -q
```

If you touch entrypoints or runtime behavior, also run the documented smoke
commands from `docs/validation.md` when feasible.

For documentation-only changes, make sure the documented paths, commands, and
support claims are still real.

## Documentation Expectations

Update docs when you change:

- architecture or workflow
- public interfaces or schema semantics
- env vars, services, or runtime assumptions
- support boundaries

Relevant documents live under `docs/` and in `repo_kg_maintainer/README.md`.

## Security And Privacy

- never commit secrets, private `.env` values, or machine-specific credentials
- do not add new absolute local paths to code or docs
- do not reintroduce large generated graph artifacts into tracked `HEAD`
- treat legacy and experimental paths with the same secret-hygiene standard as
  the mainline

## PR Style

Prefer changes that are:

- specific
- reversible
- evidence-backed
- honest about limits
