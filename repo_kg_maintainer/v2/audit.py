from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class AuditEvent:
    tenant_id: str
    principal_id: str
    action: str
    metadata: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditLog:
    def __init__(self) -> None:
        self._entries: Dict[str, List[AuditEvent]] = {}

    def record(self, event: AuditEvent) -> None:
        self._entries.setdefault(event.tenant_id, []).append(event)

    def list_tenant_events(self, tenant_id: str) -> List[AuditEvent]:
        return list(self._entries.get(tenant_id, []))
