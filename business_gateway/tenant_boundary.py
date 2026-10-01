"""Pure DEMA User Gateway identity and routing boundary.

This module intentionally has no transport, persistence, scheduler, or platform
control-plane dependency. It resolves an exact Telegram identity against an
explicit, preconfigured mapping and returns a deny-by-default routing decision.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import re
from typing import Any


TELEGRAM_USER_ID_MIN_LENGTH = 1
TELEGRAM_USER_ID_MAX_LENGTH = 20
_INTERNAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_TELEGRAM_USER_ID_RE = re.compile(r"^[0-9]{1,20}$")

ROUTE_CHAIN = (
    "telegram_user",
    "tenant_boundary",
    "dema_assistant",
    "dema_lead",
    "approved_business_catalog_or_workflow",
)


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class Role(str, Enum):
    USER = "user"
    TENANT_ADMIN = "tenant_admin"
    PLATFORM_ADMIN = "platform_admin"


class Capability(str, Enum):
    BUSINESS_REQUEST = "business_request"
    CATALOG_LOOKUP = "catalog_lookup"
    REQUEST_ROUTING = "request_routing"
    PROPOSAL_CREATE = "proposal_create"
    TENANT_BUSINESS_ADMIN = "tenant_business_admin"

    GLOBAL_MEMORY = "global_memory"
    GLOBAL_SKILL_LIBRARY = "global_skill_library"
    ROSTER_MUTATION = "roster_mutation"
    PROVIDER_CONFIGURATION = "provider_configuration"
    RUNTIME_TOKEN_MINT_REVOKE = "runtime_token_mint_revoke"
    COOLIFY_DEPLOY = "coolify_deploy"
    MISSION_CONTROL_OWNER = "mission_control_owner_control_plane"
    AUTONOMOUS_SCHEDULING_CRON = "autonomous_scheduling_cron"


class IdentityBoundaryError(ValueError):
    """Base error for invalid identity-boundary configuration or input."""


class InvalidTelegramUserId(IdentityBoundaryError):
    """Raised when a Telegram identity is not an exact bounded digit string."""


class MappingConfigurationError(IdentityBoundaryError):
    """Raised when identity mappings are duplicated, ambiguous, or unsafe."""


DEFAULT_TELEGRAM_ROLE = Role.USER

ALLOWED_CAPABILITIES = frozenset(
    {
        Capability.BUSINESS_REQUEST,
        Capability.CATALOG_LOOKUP,
        Capability.REQUEST_ROUTING,
        Capability.PROPOSAL_CREATE,
        Capability.TENANT_BUSINESS_ADMIN,
    }
)

DENIED_CAPABILITIES = frozenset(
    {
        Capability.GLOBAL_MEMORY,
        Capability.GLOBAL_SKILL_LIBRARY,
        Capability.ROSTER_MUTATION,
        Capability.PROVIDER_CONFIGURATION,
        Capability.RUNTIME_TOKEN_MINT_REVOKE,
        Capability.COOLIFY_DEPLOY,
        Capability.MISSION_CONTROL_OWNER,
        Capability.AUTONOMOUS_SCHEDULING_CRON,
    }
)

_ROLE_CAPABILITIES = MappingProxyType(
    {
        Role.USER: frozenset(
            {
                Capability.BUSINESS_REQUEST,
                Capability.CATALOG_LOOKUP,
                Capability.REQUEST_ROUTING,
                Capability.PROPOSAL_CREATE,
            }
        ),
        Role.TENANT_ADMIN: frozenset(
            {
                Capability.BUSINESS_REQUEST,
                Capability.CATALOG_LOOKUP,
                Capability.REQUEST_ROUTING,
                Capability.PROPOSAL_CREATE,
                Capability.TENANT_BUSINESS_ADMIN,
            }
        ),
        # This role belongs to a separate owner/admin boundary and is never
        # admitted to a Telegram identity registry.
        Role.PLATFORM_ADMIN: frozenset(),
    }
)


def validate_telegram_user_id(value: Any) -> str:
    """Validate and return the Telegram ID without coercion or normalization."""
    if not isinstance(value, str):
        raise InvalidTelegramUserId("telegram_user_id must be a string")
    if not (
        TELEGRAM_USER_ID_MIN_LENGTH <= len(value) <= TELEGRAM_USER_ID_MAX_LENGTH
        and _TELEGRAM_USER_ID_RE.fullmatch(value)
    ):
        raise InvalidTelegramUserId("telegram_user_id must be 1-20 ASCII digits")
    return value


def _validate_internal_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _INTERNAL_ID_RE.fullmatch(value) is None:
        raise MappingConfigurationError(f"{field_name} must be an explicit bounded identifier")
    return value


def _coerce_enum(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise MappingConfigurationError(f"invalid {field_name}") from None


@dataclass(frozen=True)
class IdentityMapping:
    """One exact Telegram identity to one internal user/tenant context."""

    telegram_user_id: str
    user_id: str
    tenant_id: str
    role: Role
    status: IdentityStatus

    def __post_init__(self) -> None:
        validate_telegram_user_id(self.telegram_user_id)
        _validate_internal_id(self.user_id, "user_id")
        _validate_internal_id(self.tenant_id, "tenant_id")
        role = _coerce_enum(self.role, Role, "role")
        status = _coerce_enum(self.status, IdentityStatus, "status")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "status", status)


@dataclass(frozen=True)
class IdentityContext:
    """Resolved internal context carried after identity resolution."""

    telegram_user_id: str
    user_id: str
    tenant_id: str
    role: Role
    status: IdentityStatus


@dataclass(frozen=True)
class IdentityRegistry:
    """Immutable lookup table for exact Telegram identity mappings."""

    mappings: Mapping[str, IdentityContext]

    def resolve(self, telegram_user_id: Any) -> IdentityContext | None:
        try:
            literal = validate_telegram_user_id(telegram_user_id)
        except InvalidTelegramUserId:
            return None
        return self.mappings.get(literal)


def build_identity_registry(mappings: Iterable[IdentityMapping]) -> IdentityRegistry:
    """Build an immutable, deterministic registry and reject ambiguity."""
    by_telegram: dict[str, IdentityContext] = {}
    by_user: dict[str, tuple[str, Role, IdentityStatus]] = {}
    try:
        iterator = iter(mappings)
    except TypeError:
        raise MappingConfigurationError("mappings must be iterable") from None

    for mapping in iterator:
        if not isinstance(mapping, IdentityMapping):
            raise MappingConfigurationError("mappings must contain IdentityMapping values")
        if mapping.role is Role.PLATFORM_ADMIN:
            raise MappingConfigurationError(
                "platform_admin is outside the Telegram identity boundary"
            )
        if mapping.telegram_user_id in by_telegram:
            raise MappingConfigurationError("duplicate Telegram identity mapping")

        user_context = (mapping.tenant_id, mapping.role, mapping.status)
        prior_context = by_user.get(mapping.user_id)
        if prior_context is not None and prior_context != user_context:
            raise MappingConfigurationError("ambiguous user/tenant identity mapping")

        context = IdentityContext(
            telegram_user_id=mapping.telegram_user_id,
            user_id=mapping.user_id,
            tenant_id=mapping.tenant_id,
            role=mapping.role,
            status=mapping.status,
        )
        by_telegram[mapping.telegram_user_id] = context
        by_user[mapping.user_id] = user_context

    return IdentityRegistry(MappingProxyType(dict(by_telegram)))


def resolve_identity(
    registry: IdentityRegistry, telegram_user_id: Any
) -> IdentityContext | None:
    """Resolve one exact identity; invalid and unmapped inputs return None."""
    return registry.resolve(telegram_user_id)


@dataclass(frozen=True)
class PolicyDecision:
    """Deterministic allow/deny result with explicit resolved context."""

    allowed: bool
    reason: str
    capability: str
    route_chain: tuple[str, ...]
    telegram_user_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    role: Role | None = None


def _capability_value(value: Any) -> tuple[Capability | None, str]:
    if isinstance(value, Capability):
        return value, value.value
    if isinstance(value, str):
        try:
            capability = Capability(value)
        except ValueError:
            return None, value
        return capability, value
    return None, "invalid_capability"


def _decision(
    *,
    allowed: bool,
    reason: str,
    capability: str,
    context: IdentityContext | None,
) -> PolicyDecision:
    return PolicyDecision(
        allowed=allowed,
        reason=reason,
        capability=capability,
        route_chain=ROUTE_CHAIN,
        telegram_user_id=context.telegram_user_id if context else None,
        user_id=context.user_id if context else None,
        tenant_id=context.tenant_id if context else None,
        role=context.role if context else None,
    )


def route_business_request(
    registry: IdentityRegistry,
    telegram_user_id: Any,
    capability: Any,
    *,
    requested_tenant_id: str | None = None,
    requested_user_id: str | None = None,
) -> PolicyDecision:
    """Authorize only bounded business routing from a resolved tenant context.

    ``requested_tenant_id`` and ``requested_user_id`` are checks only. The
    resolved context remains the sole source of tenant and user authority; a
    caller cannot select a different context through request input.
    """
    if not isinstance(registry, IdentityRegistry):
        raise TypeError("registry must be an IdentityRegistry")

    resolved = resolve_identity(registry, telegram_user_id)
    capability_enum, capability_value = _capability_value(capability)
    if resolved is None:
        return _decision(
            allowed=False,
            reason="unknown_telegram_identity",
            capability=capability_value,
            context=None,
        )
    if resolved.status is not IdentityStatus.ACTIVE:
        return _decision(
            allowed=False,
            reason="identity_not_active",
            capability=capability_value,
            context=resolved,
        )
    if requested_tenant_id is not None and requested_tenant_id != resolved.tenant_id:
        return _decision(
            allowed=False,
            reason="cross_tenant_access_denied",
            capability=capability_value,
            context=resolved,
        )
    if (
        resolved.role is Role.USER
        and requested_user_id is not None
        and requested_user_id != resolved.user_id
    ):
        return _decision(
            allowed=False,
            reason="user_scope_access_denied",
            capability=capability_value,
            context=resolved,
        )
    if capability_enum is None or capability_enum not in ALLOWED_CAPABILITIES:
        return _decision(
            allowed=False,
            reason="capability_not_allowed",
            capability=capability_value,
            context=resolved,
        )
    if capability_enum not in _ROLE_CAPABILITIES[resolved.role]:
        return _decision(
            allowed=False,
            reason="capability_not_allowed",
            capability=capability_value,
            context=resolved,
        )

    return _decision(
        allowed=True,
        reason="allowed",
        capability=capability_value,
        context=resolved,
    )


__all__ = [
    "ALLOWED_CAPABILITIES",
    "Capability",
    "DEFAULT_TELEGRAM_ROLE",
    "DENIED_CAPABILITIES",
    "IdentityBoundaryError",
    "IdentityContext",
    "IdentityMapping",
    "IdentityRegistry",
    "IdentityStatus",
    "InvalidTelegramUserId",
    "MappingConfigurationError",
    "PolicyDecision",
    "ROLE_CAPABILITIES",
    "ROUTE_CHAIN",
    "Role",
    "build_identity_registry",
    "resolve_identity",
    "route_business_request",
    "validate_telegram_user_id",
]

# Public immutable view for callers that need to document role scopes.
ROLE_CAPABILITIES = _ROLE_CAPABILITIES
