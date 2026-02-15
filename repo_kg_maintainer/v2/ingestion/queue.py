from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Dict, Optional


@dataclass
class IndexJobV2:
    job_id: str
    tenant_id: str
    repo_id: str
    commit_sha: str
    files: Dict[str, str]
    delivery_id: str
    max_retries: int = 3
    attempts: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DeliveryDeduplicator:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def is_duplicate(self, tenant_id: str, delivery_id: str) -> bool:
        key = (tenant_id, delivery_id)
        if key in self._seen:
            return True
        self._seen.add(key)
        return False


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._queue: Queue[IndexJobV2] = Queue()

    def enqueue(self, job: IndexJobV2) -> None:
        self._queue.put(job)

    def dequeue(self, timeout_seconds: float | None = None) -> Optional[IndexJobV2]:
        try:
            return self._queue.get(timeout=timeout_seconds)
        except Empty:
            return None

    def size(self) -> int:
        return self._queue.qsize()
