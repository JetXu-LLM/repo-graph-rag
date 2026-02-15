from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


VERTEX_COLLECTION = "GraphNodeV2"
EDGE_COLLECTION = "GraphEdgeV2"
JOB_COLLECTION = "IndexJobV2"
DELIVERY_COLLECTION = "WebhookDeliveryV2"
AUDIT_COLLECTION = "AuditLogV2"


@dataclass(frozen=True)
class IndexSpec:
    fields: tuple[str, ...]
    unique: bool = False


class MigrationManagerV2:
    def __init__(self) -> None:
        self.vertex_indexes = [
            IndexSpec(("tenant_id", "repo_id", "commit_sha", "id"), unique=True),
            IndexSpec(("tenant_id", "repo_id", "commit_sha", "entity_kind"), unique=False),
        ]
        self.edge_indexes = [
            IndexSpec(("tenant_id", "repo_id", "commit_sha", "source_id"), unique=False),
            IndexSpec(("tenant_id", "repo_id", "commit_sha", "target_id"), unique=False),
            IndexSpec(("tenant_id", "repo_id", "commit_sha", "id"), unique=True),
        ]
        self.job_indexes = [
            IndexSpec(("tenant_id", "job_id"), unique=True),
            IndexSpec(("tenant_id", "status"), unique=False),
        ]
        self.delivery_indexes = [
            IndexSpec(("tenant_id", "delivery_id"), unique=True),
        ]
        self.audit_indexes = [
            IndexSpec(("tenant_id", "created_at"), unique=False),
        ]

    def bootstrap(self, db) -> Dict[str, List[str]]:
        created: Dict[str, List[str]] = {
            "collections": [],
            "indexes": [],
        }

        self._ensure_collection(db, VERTEX_COLLECTION, edge=False, created=created)
        self._ensure_collection(db, EDGE_COLLECTION, edge=True, created=created)
        self._ensure_collection(db, JOB_COLLECTION, edge=False, created=created)
        self._ensure_collection(db, DELIVERY_COLLECTION, edge=False, created=created)
        self._ensure_collection(db, AUDIT_COLLECTION, edge=False, created=created)

        self._ensure_indexes(db.collection(VERTEX_COLLECTION), self.vertex_indexes, created)
        self._ensure_indexes(db.collection(EDGE_COLLECTION), self.edge_indexes, created)
        self._ensure_indexes(db.collection(JOB_COLLECTION), self.job_indexes, created)
        self._ensure_indexes(db.collection(DELIVERY_COLLECTION), self.delivery_indexes, created)
        self._ensure_indexes(db.collection(AUDIT_COLLECTION), self.audit_indexes, created)

        return created

    def _ensure_collection(self, db, name: str, edge: bool, created: Dict[str, List[str]]) -> None:
        if db.has_collection(name):
            return
        db.create_collection(name, edge=edge)
        created["collections"].append(name)

    def _ensure_indexes(self, collection, index_specs: Iterable[IndexSpec], created: Dict[str, List[str]]) -> None:
        add_index = getattr(collection, "add_persistent_index", None)
        if add_index is None:
            return

        existing_indexes = getattr(collection, "indexes", lambda: [])()
        existing_signatures = {
            (tuple(index.get("fields", [])), bool(index.get("unique", False)))
            for index in existing_indexes
        }

        for spec in index_specs:
            signature = (spec.fields, spec.unique)
            if signature in existing_signatures:
                continue
            add_index(fields=list(spec.fields), unique=spec.unique)
            created["indexes"].append(f"{collection.name}:{','.join(spec.fields)}:{spec.unique}")
