from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.api.service import GraphServiceV2, IndexRepositoryRequestV2, QueryContextRequestV2
from v2.audit import AuditLog
from v2.graph.store import InMemoryGraphStoreV2
from v2.ingestion.events import WebhookValidationError, normalize_github_webhook
from v2.ingestion.invalidation import DependencyInvalidationPlanner
from v2.ingestion.queue import DeliveryDeduplicator, InMemoryJobQueue
from v2.ingestion.worker import IndexWorkerV2
from v2.quota import QuotaManager, TenantQuotaPolicy
from v2.security import ApiKeyRBAC, ApiPrincipal, AuthorizationError


def _build_service() -> tuple[GraphServiceV2, InMemoryJobQueue, InMemoryGraphStoreV2, QuotaManager]:
    graph_store = InMemoryGraphStoreV2()
    queue = InMemoryJobQueue()
    authz = ApiKeyRBAC()
    authz.register_key(
        "key-tenant-a",
        ApiPrincipal(
            principal_id="maintainer",
            tenant_ids=frozenset({"tenant-a"}),
            roles=frozenset({"viewer", "indexer"}),
        ),
    )
    quota = QuotaManager()
    quota.set_policy("tenant-a", TenantQuotaPolicy(max_repos=5, max_concurrent_jobs=5, max_graph_nodes=5000))
    service = GraphServiceV2(
        graph_store=graph_store,
        queue=queue,
        authz=authz,
        quota=quota,
        audit_log=AuditLog(),
        deduplicator=DeliveryDeduplicator(),
    )
    return service, queue, graph_store, quota


def test_normalize_github_webhook_verifies_signature_and_contract() -> None:
    payload = {
        "installation": {"id": 42},
        "repository": {"full_name": "org/repo"},
        "after": "abc123",
    }
    body = json.dumps(payload).encode("utf-8")
    secret = "secret-token"
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    event = normalize_github_webhook(
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-1",
        },
        body=body,
        webhook_secret=secret,
        tenant_resolver=lambda installation_id, _payload: f"tenant-{installation_id}",
    )

    assert event.tenant_id == "tenant-42"
    assert event.installation_id == "42"
    assert event.repo_full_name == "org/repo"
    assert event.event_type == "push"
    assert event.delivery_id == "delivery-1"
    assert event.commit_sha == "abc123"


def test_normalize_github_webhook_rejects_invalid_signature() -> None:
    payload = {
        "installation": {"id": 42},
        "repository": {"full_name": "org/repo"},
    }
    with pytest.raises(WebhookValidationError):
        normalize_github_webhook(
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
            },
            body=json.dumps(payload).encode("utf-8"),
            webhook_secret="secret-token",
            tenant_resolver=lambda installation_id, _payload: f"tenant-{installation_id}",
        )


def test_service_enqueues_index_job_and_deduplicates_delivery() -> None:
    service, queue, _, _ = _build_service()
    request = IndexRepositoryRequestV2(
        tenant_id="tenant-a",
        repo_id="repo-x",
        commit_sha="sha-1",
        files={"a.py": "class A:\n    pass\n"},
        delivery_id="d-1",
    )

    first = service.post_index_repository(request, api_key="key-tenant-a")
    second = service.post_index_repository(request, api_key="key-tenant-a")

    assert first["status"] == "queued"
    assert second["status"] == "duplicate"
    assert queue.size() == 1


def test_worker_processes_job_and_graph_is_queryable() -> None:
    service, queue, graph_store, quota = _build_service()
    request = IndexRepositoryRequestV2(
        tenant_id="tenant-a",
        repo_id="repo-x",
        commit_sha="sha-2",
        files={
            "service.py": """
class Service:
    def run(self):
        worker = Worker()
        worker.work()

class Worker:
    def work(self):
        return 1
"""
        },
        delivery_id="d-2",
    )
    response = service.post_index_repository(request, api_key="key-tenant-a")

    worker = IndexWorkerV2(
        queue=queue,
        analyzer=PythonGraphAnalyzerV2(),
        graph_store=graph_store,
        quota_manager=quota,
        sleep_fn=lambda _seconds: None,
    )
    worker.process_once()

    graph = service.get_graph("tenant-a", "repo-x", "sha-2", api_key="key-tenant-a")
    job = service.get_job("tenant-a", response["job_id"], api_key="key-tenant-a")

    assert graph["nodes"]
    assert graph["edges"]
    assert job["status"] == "COMPLETED"


def test_service_enforces_tenant_isolation() -> None:
    service, _, _, _ = _build_service()

    with pytest.raises(AuthorizationError):
        service.get_graph("tenant-b", "repo-x", "sha-2", api_key="key-tenant-a")


def test_query_context_returns_deterministic_pagination() -> None:
    service, queue, graph_store, quota = _build_service()
    request = IndexRepositoryRequestV2(
        tenant_id="tenant-a",
        repo_id="repo-y",
        commit_sha="sha-3",
        files={"a.py": "class A:\n    pass\n", "b.py": "class B:\n    pass\n"},
        delivery_id="d-3",
    )
    service.post_index_repository(request, api_key="key-tenant-a")

    worker = IndexWorkerV2(
        queue=queue,
        analyzer=PythonGraphAnalyzerV2(),
        graph_store=graph_store,
        quota_manager=quota,
        sleep_fn=lambda _seconds: None,
    )
    worker.process_once()

    first_page = service.post_query_context(
        QueryContextRequestV2(
            tenant_id="tenant-a",
            repo_id="repo-y",
            commit_sha="sha-3",
            cursor=0,
            limit=2,
        ),
        api_key="key-tenant-a",
    )
    second_page = service.post_query_context(
        QueryContextRequestV2(
            tenant_id="tenant-a",
            repo_id="repo-y",
            commit_sha="sha-3",
            cursor=2,
            limit=2,
        ),
        api_key="key-tenant-a",
    )

    assert first_page["nodes"]
    assert first_page["next_cursor"] == 2
    assert second_page["nodes"]


def test_dependency_invalidation_planner_expands_impacted_files() -> None:
    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(
        files={
            "a.py": "class A:\\n    pass\\n",
            "b.py": "from a import A\\nclass B:\\n    def run(self):\\n        return A()\\n",
            "c.py": "from b import B\\nclass C:\\n    def run(self):\\n        return B()\\n",
        },
        tenant_id="tenant-a",
        repo_id="repo-z",
        commit_sha="sha-9",
    )
    planner = DependencyInvalidationPlanner()

    impacted = planner.compute_impacted_files(snapshot, changed_files={"a.py"})

    assert "a.py" in impacted
    assert "b.py" in impacted or "c.py" in impacted
