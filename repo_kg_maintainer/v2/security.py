from __future__ import annotations

from dataclasses import dataclass, field


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class ApiPrincipal:
    principal_id: str
    tenant_ids: frozenset[str]
    roles: frozenset[str]


class ApiKeyRBAC:
    def __init__(self) -> None:
        self._api_keys: dict[str, ApiPrincipal] = {}

    def register_key(self, api_key: str, principal: ApiPrincipal) -> None:
        self._api_keys[api_key] = principal

    def authorize(self, api_key: str, tenant_id: str, required_role: str) -> ApiPrincipal:
        if api_key not in self._api_keys:
            raise AuthorizationError("invalid api key")
        principal = self._api_keys[api_key]
        if tenant_id not in principal.tenant_ids:
            raise AuthorizationError("tenant access denied")
        if required_role not in principal.roles:
            raise AuthorizationError("missing required role")
        return principal
