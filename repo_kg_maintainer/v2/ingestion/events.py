from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class NormalizedWebhookEventV2:
    tenant_id: str
    installation_id: str
    repo_full_name: str
    event_type: str
    delivery_id: str
    commit_sha: str
    payload: Dict[str, Any]


class WebhookValidationError(ValueError):
    pass


def normalize_github_webhook(
    headers: Dict[str, str],
    body: bytes,
    webhook_secret: str,
    tenant_resolver: Callable[[str, Dict[str, Any]], str],
) -> NormalizedWebhookEventV2:
    signature = _header(headers, "X-Hub-Signature-256")
    event_type = _header(headers, "X-GitHub-Event")
    delivery_id = _header(headers, "X-GitHub-Delivery")

    expected_signature = "sha256=" + hmac.new(
        webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise WebhookValidationError("invalid webhook signature")

    payload = json.loads(body.decode("utf-8"))
    installation = payload.get("installation") or {}
    repository = payload.get("repository") or {}
    installation_id = str(installation.get("id", ""))
    repo_full_name = repository.get("full_name", "")

    if not installation_id:
        raise WebhookValidationError("missing installation id")
    if not repo_full_name:
        raise WebhookValidationError("missing repository full name")

    commit_sha = payload.get("after") or payload.get("head_commit", {}).get("id") or ""
    tenant_id = tenant_resolver(installation_id, payload)

    return NormalizedWebhookEventV2(
        tenant_id=tenant_id,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
        event_type=event_type,
        delivery_id=delivery_id,
        commit_sha=commit_sha,
        payload=payload,
    )


def _header(headers: Dict[str, str], key: str) -> str:
    for candidate, value in headers.items():
        if candidate.lower() == key.lower():
            return value
    raise WebhookValidationError(f"missing header: {key}")
