from __future__ import annotations

import time
from datetime import datetime, timezone

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.models import IndexJobStatus
from v2.ingestion.queue import InMemoryJobQueue, IndexJobV2


class IndexWorkerV2:
    def __init__(
        self,
        queue: InMemoryJobQueue,
        analyzer: PythonGraphAnalyzerV2,
        graph_store,
        quota_manager=None,
        sleep_fn=time.sleep,
    ) -> None:
        self.queue = queue
        self.analyzer = analyzer
        self.graph_store = graph_store
        self.quota_manager = quota_manager
        self.sleep_fn = sleep_fn
        self._completed_jobs: set[tuple[str, str]] = set()

    def process_once(self) -> bool:
        job = self.queue.dequeue(timeout_seconds=0)
        if job is None:
            return False

        idempotency_key = (job.tenant_id, job.job_id)
        if idempotency_key in self._completed_jobs:
            self._upsert_status(job, "SKIPPED", attempts=job.attempts)
            return True

        self._upsert_status(job, "RUNNING", attempts=job.attempts)

        try:
            _, snapshot = self.analyzer.analyze_files(
                files=job.files,
                tenant_id=job.tenant_id,
                repo_id=job.repo_id,
                commit_sha=job.commit_sha,
            )
            self.graph_store.save_snapshot(snapshot)
            self._completed_jobs.add(idempotency_key)
            self._upsert_status(job, "COMPLETED", attempts=job.attempts + 1)
            if self.quota_manager:
                self.quota_manager.release_job_slot(job.tenant_id)
            return True
        except Exception as exc:  # pragma: no cover - covered through retry behavior tests
            job.attempts += 1
            if job.attempts < job.max_retries:
                self._upsert_status(job, "RETRYING", attempts=job.attempts, error=str(exc))
                self.sleep_fn(min(2 ** job.attempts, 8))
                self.queue.enqueue(job)
            else:
                self._upsert_status(job, "FAILED", attempts=job.attempts, error=str(exc))
                if self.quota_manager:
                    self.quota_manager.release_job_slot(job.tenant_id)
            return True

    def _upsert_status(self, job: IndexJobV2, status: str, attempts: int, error: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.graph_store.get_job_status(job.tenant_id, job.job_id)
        created_at = existing.created_at if existing else now
        status_obj = IndexJobStatus(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            repo_id=job.repo_id,
            commit_sha=job.commit_sha,
            status=status,
            attempts=attempts,
            error=error,
            created_at=created_at,
            updated_at=now,
        )
        self.graph_store.upsert_job_status(status_obj)
