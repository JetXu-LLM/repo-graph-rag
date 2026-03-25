"""Service-layer contract for indexing and querying snapshot v2 graphs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import uuid
from typing import Dict

from v2.audit import AuditEvent, AuditLog
from v2.ingestion.queue import DeliveryDeduplicator, InMemoryJobQueue, IndexJobV2
from v2.quota import QuotaManager
from v2.security import ApiKeyRBAC
from v2.serializer import snapshot_to_dict


@dataclass
class IndexRepositoryRequestV2:
    """Request payload for indexing a full repository snapshot."""

    tenant_id: str
    repo_id: str
    commit_sha: str
    files: Dict[str, str]
    delivery_id: str


@dataclass
class QueryContextRequestV2:
    """Request payload for deterministic context/subgraph queries."""

    tenant_id: str
    repo_id: str
    commit_sha: str
    file_path: str | None = None
    symbol_type: str | None = None
    relation_type: str | None = None
    hop_limit: int = 1
    cursor: int = 0
    limit: int = 50


class GraphServiceV2:
    """Application service exposing index, query, and job-status operations."""

    def __init__(
        self,
        graph_store,
        queue: InMemoryJobQueue,
        authz: ApiKeyRBAC,
        quota: QuotaManager,
        audit_log: AuditLog,
        deduplicator: DeliveryDeduplicator,
    ) -> None:
        self.graph_store = graph_store
        self.queue = queue
        self.authz = authz
        self.quota = quota
        self.audit_log = audit_log
        self.deduplicator = deduplicator

    def post_index_repository(self, request: IndexRepositoryRequestV2, api_key: str) -> Dict[str, object]:
        """Validate, deduplicate, and enqueue an indexing job."""
        principal = self.authz.authorize(api_key, request.tenant_id, "indexer")
        self.quota.register_repo(request.tenant_id, request.repo_id)
        self.quota.acquire_job_slot(request.tenant_id)

        if self.deduplicator.is_duplicate(request.tenant_id, request.delivery_id):
            self.quota.release_job_slot(request.tenant_id)
            return {"status": "duplicate", "delivery_id": request.delivery_id}

        job = IndexJobV2(
            job_id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            repo_id=request.repo_id,
            commit_sha=request.commit_sha,
            files=request.files,
            delivery_id=request.delivery_id,
        )
        self.queue.enqueue(job)
        self.audit_log.record(
            AuditEvent(
                tenant_id=request.tenant_id,
                principal_id=principal.principal_id,
                action="index_repository",
                metadata={
                    "repo_id": request.repo_id,
                    "commit_sha": request.commit_sha,
                    "job_id": job.job_id,
                },
            )
        )
        return {
            "status": "queued",
            "job_id": job.job_id,
            "tenant_id": request.tenant_id,
            "repo_id": request.repo_id,
            "commit_sha": request.commit_sha,
        }

    def post_index_commit(self, request: IndexRepositoryRequestV2, api_key: str) -> Dict[str, object]:
        """Alias for repository indexing with commit-scoped semantics."""
        return self.post_index_repository(request, api_key)

    def get_graph(
        self,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        api_key: str,
    ) -> Dict[str, object]:
        """Return a canonicalized graph snapshot for the requested repository state."""
        principal = self.authz.authorize(api_key, tenant_id, "viewer")
        snapshot = self.graph_store.get_snapshot(tenant_id, repo_id, commit_sha)
        self.quota.validate_graph_size(tenant_id, len(snapshot.nodes))
        self.audit_log.record(
            AuditEvent(
                tenant_id=tenant_id,
                principal_id=principal.principal_id,
                action="get_graph",
                metadata={"repo_id": repo_id, "commit_sha": commit_sha},
            )
        )
        return snapshot_to_dict(snapshot)

    def post_query_context(self, request: QueryContextRequestV2, api_key: str) -> Dict[str, object]:
        """Return a deterministic graph slice using store-backed query capabilities."""
        principal = self.authz.authorize(api_key, request.tenant_id, "viewer")
        query_fn = getattr(self.graph_store, "query_context", None)
        if query_fn is None:
            snapshot = self.graph_store.get_snapshot(request.tenant_id, request.repo_id, request.commit_sha)
            result = {
                "nodes": [asdict(node) for node in snapshot.nodes],
                "edges": [asdict(edge) for edge in snapshot.edges],
                "total": len(snapshot.nodes),
                "next_cursor": None,
            }
        else:
            result = query_fn(
                tenant_id=request.tenant_id,
                repo_id=request.repo_id,
                commit_sha=request.commit_sha,
                file_path=request.file_path,
                symbol_type=request.symbol_type,
                relation_type=request.relation_type,
                hop_limit=request.hop_limit,
                cursor=request.cursor,
                limit=request.limit,
            )

        self.audit_log.record(
            AuditEvent(
                tenant_id=request.tenant_id,
                principal_id=principal.principal_id,
                action="query_context",
                metadata={
                    "repo_id": request.repo_id,
                    "commit_sha": request.commit_sha,
                    "filters": {
                        "file_path": request.file_path,
                        "symbol_type": request.symbol_type,
                        "relation_type": request.relation_type,
                        "hop_limit": request.hop_limit,
                    },
                },
            )
        )
        return result

    def get_job(self, tenant_id: str, job_id: str, api_key: str) -> Dict[str, object]:
        """Fetch the latest job status for a tenant-visible indexing job."""
        principal = self.authz.authorize(api_key, tenant_id, "viewer")
        status = self.graph_store.get_job_status(tenant_id, job_id)
        if status is None:
            return {"job_id": job_id, "status": "not_found"}
        self.audit_log.record(
            AuditEvent(
                tenant_id=tenant_id,
                principal_id=principal.principal_id,
                action="get_job",
                metadata={"job_id": job_id},
            )
        )
        return asdict(status)
