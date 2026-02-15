from __future__ import annotations

import hashlib
import re


def _sanitize(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    return re.sub(r"[^a-zA-Z0-9_./:-]", "_", normalized)


def canonical_symbol_path(file_path: str, parent_name: str, name: str) -> str:
    parent = parent_name.replace("/", ".") if parent_name else ""
    if parent:
        return f"{_sanitize(file_path)}::{_sanitize(parent)}.{_sanitize(name)}"
    return f"{_sanitize(file_path)}::{_sanitize(name)}"


def build_node_id(
    tenant_id: str,
    repo_id: str,
    commit_sha: str,
    entity_kind: str,
    symbol_path: str,
) -> str:
    return "|".join(
        [
            _sanitize(tenant_id),
            _sanitize(repo_id),
            _sanitize(commit_sha),
            _sanitize(entity_kind),
            _sanitize(symbol_path),
        ]
    )


def build_edge_id(
    source_id: str,
    relation_type: str,
    target_id: str,
    rule_id: str,
) -> str:
    edge_basis = "|".join(
        [_sanitize(source_id), _sanitize(relation_type), _sanitize(target_id), _sanitize(rule_id)]
    )
    digest = hashlib.sha256(edge_basis.encode("utf-8")).hexdigest()[:24]
    return f"edge|{digest}"


def build_schema_hash(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()
