from __future__ import annotations

from dataclasses import dataclass


class QuotaExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class TenantQuotaPolicy:
    max_repos: int
    max_concurrent_jobs: int
    max_graph_nodes: int


class QuotaManager:
    def __init__(self) -> None:
        self._policies: dict[str, TenantQuotaPolicy] = {}
        self._repos: dict[str, set[str]] = {}
        self._active_jobs: dict[str, int] = {}

    def set_policy(self, tenant_id: str, policy: TenantQuotaPolicy) -> None:
        self._policies[tenant_id] = policy

    def register_repo(self, tenant_id: str, repo_id: str) -> None:
        repos = self._repos.setdefault(tenant_id, set())
        repos.add(repo_id)
        policy = self._require_policy(tenant_id)
        if len(repos) > policy.max_repos:
            repos.remove(repo_id)
            raise QuotaExceededError("repo quota exceeded")

    def acquire_job_slot(self, tenant_id: str) -> None:
        policy = self._require_policy(tenant_id)
        active = self._active_jobs.get(tenant_id, 0) + 1
        if active > policy.max_concurrent_jobs:
            raise QuotaExceededError("concurrent job quota exceeded")
        self._active_jobs[tenant_id] = active

    def release_job_slot(self, tenant_id: str) -> None:
        self._active_jobs[tenant_id] = max(self._active_jobs.get(tenant_id, 1) - 1, 0)

    def validate_graph_size(self, tenant_id: str, node_count: int) -> None:
        policy = self._require_policy(tenant_id)
        if node_count > policy.max_graph_nodes:
            raise QuotaExceededError("graph size quota exceeded")

    def _require_policy(self, tenant_id: str) -> TenantQuotaPolicy:
        if tenant_id not in self._policies:
            raise QuotaExceededError("missing quota policy")
        return self._policies[tenant_id]
