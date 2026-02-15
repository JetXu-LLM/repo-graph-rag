from __future__ import annotations

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.api.service import GraphServiceV2
from v2.audit import AuditLog
from v2.graph.store import ArangoGraphStoreV2, InMemoryGraphStoreV2
from v2.ingestion.queue import DeliveryDeduplicator, InMemoryJobQueue
from v2.ingestion.worker import IndexWorkerV2
from v2.quota import QuotaManager
from v2.security import ApiKeyRBAC


def build_in_memory_runtime() -> tuple[GraphServiceV2, IndexWorkerV2]:
    store = InMemoryGraphStoreV2()
    queue = InMemoryJobQueue()
    authz = ApiKeyRBAC()
    quota = QuotaManager()
    audit = AuditLog()
    dedup = DeliveryDeduplicator()
    analyzer = PythonGraphAnalyzerV2()

    service = GraphServiceV2(
        graph_store=store,
        queue=queue,
        authz=authz,
        quota=quota,
        audit_log=audit,
        deduplicator=dedup,
    )
    worker = IndexWorkerV2(queue=queue, analyzer=analyzer, graph_store=store, quota_manager=quota)
    return service, worker


def build_arango_runtime(db) -> tuple[GraphServiceV2, IndexWorkerV2, ArangoGraphStoreV2]:
    store = ArangoGraphStoreV2(db)
    store.bootstrap()
    queue = InMemoryJobQueue()
    authz = ApiKeyRBAC()
    quota = QuotaManager()
    audit = AuditLog()
    dedup = DeliveryDeduplicator()
    analyzer = PythonGraphAnalyzerV2()

    service = GraphServiceV2(
        graph_store=store,
        queue=queue,
        authz=authz,
        quota=quota,
        audit_log=audit,
        deduplicator=dedup,
    )
    worker = IndexWorkerV2(queue=queue, analyzer=analyzer, graph_store=store, quota_manager=quota)
    return service, worker, store
