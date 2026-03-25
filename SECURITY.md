# Security Policy

## Scope

This repository is a public research artifact. Security expectations here are
mostly about repository hygiene:

- no committed secrets
- no private `.env` values
- no accidental publication of machine-specific credentials
- no misleading claims about safety or production readiness
- no new public documentation that implies support beyond the tested surface

## Reporting

For non-sensitive issues, open a GitHub issue.

For sensitive disclosures, do not publish the details in a public issue. Contact
the maintainer directly.

## Current Boundaries

- the supported public path is the Python `v2` snapshot pipeline
- the legacy Arango path is not positioned as hardened production software
- the Go subtree is experimental
- historical large generated artifacts were removed from `HEAD` and should not
  be reintroduced

If you find a problem in a historical or experimental path, include that context
when reporting it.
