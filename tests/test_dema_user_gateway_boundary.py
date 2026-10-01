#!/usr/bin/env python3
"""Focused TDD contract tests for the DEMA User Gateway boundary."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from business_gateway.tenant_boundary import (  # noqa: E402
    ALLOWED_CAPABILITIES,
    DEFAULT_TELEGRAM_ROLE,
    DENIED_CAPABILITIES,
    IdentityMapping,
    IdentityStatus,
    MappingConfigurationError,
    Role,
    ROUTE_CHAIN,
    Capability,
    build_identity_registry,
    route_business_request,
    validate_telegram_user_id,
)


CONTRACT = BASE / "catalog" / "dema-user-gateway-contract-v1.json"
PHASE1 = BASE / "catalog" / "dema-phase1-runtime-readiness-v1.json"
ROSTER = BASE / "agents.json"

SECRET_FIELD = re.compile(
    r"(?:secret|token|password|api[_-]?key|client[_-]?secret|credential|private[_-]?key|access[_-]?token)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|(?:ghp|github_pat|sk|xox[baprs])-[_A-Za-z0-9-]{12,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
    re.IGNORECASE,
)
ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/])")


TELEGRAM_A = "90000000000000000001"
TELEGRAM_B = "90000000000000000002"


def _mapping(
    telegram_user_id: str = TELEGRAM_A,
    *,
    user_id: str = "fixture-user-a",
    tenant_id: str = "fixture-tenant-a",
    role: Role = Role.USER,
    status: IdentityStatus = IdentityStatus.ACTIVE,
) -> IdentityMapping:
    return IdentityMapping(
        telegram_user_id=telegram_user_id,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        status=status,
    )


def _registry(*mappings: IdentityMapping):
    return build_identity_registry(mappings)


def _walk_json(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, path + (str(index),))


class TestDemaUserGatewayBoundary(unittest.TestCase):
    def test_telegram_id_validation_preserves_literal_and_rejects_repairable_input(self):
        literal = "000123"
        self.assertEqual(validate_telegram_user_id(literal), literal)
        self.assertEqual(validate_telegram_user_id("9" * 20), "9" * 20)
        for invalid in (
            "",
            " 123",
            "123 ",
            "+123",
            "-123",
            "123.0",
            "1" * 21,
            123,
            None,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_telegram_user_id(invalid)

    def test_unknown_or_inactive_identity_is_denied(self):
        registry = _registry(_mapping())
        unknown = route_business_request(registry, TELEGRAM_B, Capability.CATALOG_LOOKUP)
        self.assertFalse(unknown.allowed)
        self.assertEqual(unknown.reason, "unknown_telegram_identity")

        inactive = route_business_request(
            _registry(_mapping(status=IdentityStatus.SUSPENDED)),
            TELEGRAM_A,
            Capability.CATALOG_LOOKUP,
        )
        self.assertFalse(inactive.allowed)
        self.assertEqual(inactive.reason, "identity_not_active")

    def test_duplicate_or_ambiguous_mapping_is_rejected(self):
        with self.assertRaises(MappingConfigurationError):
            _registry(_mapping(), _mapping())

        with self.assertRaises(MappingConfigurationError):
            _registry(
                _mapping(user_id="fixture-user-a", tenant_id="fixture-tenant-a"),
                _mapping(
                    telegram_user_id=TELEGRAM_B,
                    user_id="fixture-user-a",
                    tenant_id="fixture-tenant-b",
                ),
            )

    def test_user_is_limited_to_own_user_and_tenant_context(self):
        registry = _registry(_mapping())
        allowed = route_business_request(
            registry,
            TELEGRAM_A,
            Capability.BUSINESS_REQUEST,
            requested_tenant_id="fixture-tenant-a",
            requested_user_id="fixture-user-a",
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.tenant_id, "fixture-tenant-a")
        self.assertEqual(allowed.user_id, "fixture-user-a")
        self.assertEqual(allowed.route_chain, ROUTE_CHAIN)

        cross_tenant = route_business_request(
            registry,
            TELEGRAM_A,
            Capability.BUSINESS_REQUEST,
            requested_tenant_id="fixture-tenant-b",
        )
        self.assertFalse(cross_tenant.allowed)
        self.assertEqual(cross_tenant.reason, "cross_tenant_access_denied")

        cross_user = route_business_request(
            registry,
            TELEGRAM_A,
            Capability.BUSINESS_REQUEST,
            requested_user_id="fixture-user-b",
        )
        self.assertFalse(cross_user.allowed)
        self.assertEqual(cross_user.reason, "user_scope_access_denied")

    def test_tenant_admin_has_business_scope_but_not_platform_control_plane(self):
        registry = _registry(
            _mapping(role=Role.TENANT_ADMIN, user_id="fixture-admin", tenant_id="fixture-tenant-a")
        )
        business = route_business_request(
            registry,
            TELEGRAM_A,
            Capability.TENANT_BUSINESS_ADMIN,
            requested_tenant_id="fixture-tenant-a",
        )
        self.assertTrue(business.allowed)

        owner = route_business_request(registry, TELEGRAM_A, Capability.MISSION_CONTROL_OWNER)
        self.assertFalse(owner.allowed)
        self.assertEqual(owner.reason, "capability_not_allowed")

    def test_platform_admin_is_separate_and_never_defaulted_by_telegram_mapping(self):
        self.assertEqual(DEFAULT_TELEGRAM_ROLE, Role.USER)
        with self.assertRaises(MappingConfigurationError):
            _registry(_mapping(role=Role.PLATFORM_ADMIN))

    def test_allowed_request_always_uses_assistant_then_lead_chain(self):
        registry = _registry(_mapping())
        for capability in sorted(ALLOWED_CAPABILITIES, key=lambda item: item.value):
            if capability == Capability.TENANT_BUSINESS_ADMIN:
                continue
            decision = route_business_request(registry, TELEGRAM_A, capability)
            self.assertTrue(decision.allowed, capability.value)
            self.assertEqual(
                decision.route_chain,
                (
                    "telegram_user",
                    "tenant_boundary",
                    "dema_assistant",
                    "dema_lead",
                    "approved_business_catalog_or_workflow",
                ),
            )

    def test_deny_list_covers_platform_and_autonomy_boundaries(self):
        required = {
            Capability.GLOBAL_MEMORY,
            Capability.GLOBAL_SKILL_LIBRARY,
            Capability.ROSTER_MUTATION,
            Capability.PROVIDER_CONFIGURATION,
            Capability.RUNTIME_TOKEN_MINT_REVOKE,
            Capability.COOLIFY_DEPLOY,
            Capability.MISSION_CONTROL_OWNER,
            Capability.AUTONOMOUS_SCHEDULING_CRON,
        }
        self.assertTrue(required <= DENIED_CAPABILITIES)
        registry = _registry(_mapping())
        for capability in required:
            with self.subTest(capability=capability.value):
                decision = route_business_request(registry, TELEGRAM_A, capability)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "capability_not_allowed")

    def test_policy_module_is_transport_independent(self):
        source = (BASE / "business_gateway" / "tenant_boundary.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("fastapi", source)
        self.assertNotIn("uvicorn", source)
        self.assertNotIn("sqlite", source)

    def test_contract_has_explicit_not_enabled_status_and_safe_fields(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_id"], "dema-user-gateway-contract/v1")
        self.assertEqual(contract["version"], "1.0.0")
        self.assertEqual(contract["status"], "not_enabled_yet")
        identity = contract["identity_contract"]
        telegram = identity["telegram_user_id"]
        self.assertEqual(telegram["type"], "string")
        self.assertEqual(telegram["format"], "ascii_digits")
        self.assertEqual(telegram["min_length"], 1)
        self.assertEqual(telegram["max_length"], 20)
        self.assertTrue(telegram["preserve_literal"])
        self.assertEqual(
            identity["required_internal_fields"],
            ["user_id", "tenant_id", "role", "status"],
        )
        self.assertEqual(set(contract["route_chain"]), set(ROUTE_CHAIN))
        self.assertTrue(
            {
                "telegram_webhook",
                "persistent_identity_database",
                "public_route",
                "session_issuance",
                "tenant_user_data",
                "runtime_activation",
            }
            <= set(contract["not_enabled_yet"])
        )
        self.assertTrue(set(item.value for item in DENIED_CAPABILITIES) <= set(contract["denied_capability_classes"]))
        self.assertTrue(set(item.value for item in ALLOWED_CAPABILITIES) <= set(contract["allowed_capability_classes"]))

        for path, value in _walk_json(contract):
            if path:
                self.assertIsNone(SECRET_FIELD.search(path[-1]), "/".join(path))
            if isinstance(value, str):
                self.assertIsNone(SECRET_VALUE.search(value), "/".join(path))
                self.assertFalse(ABSOLUTE_PATH.match(value), "/".join(path))
                self.assertNotIn("/opt/data/", value)
                self.assertNotIn("/home/", value)

    def test_phase1_catalog_and_existing_roster_are_not_mutated(self):
        phase1_before = PHASE1.read_bytes()
        roster_before = ROSTER.read_bytes()
        phase1 = json.loads(phase1_before.decode("utf-8"))
        roster = json.loads(roster_before.decode("utf-8"))
        self.assertEqual(len(roster), 11)
        self.assertFalse(next(row for row in roster if row["id"] == "dema-assistant")["active"])
        self.assertFalse(next(row for row in roster if row["id"] == "dema-lead")["active"])
        for entry in phase1["candidate_entries"]:
            lifecycle = entry["lifecycle"]
            for flag in ("configured", "tested", "on_demand_ready", "approved_for_users", "active"):
                self.assertIs(lifecycle[flag], False, entry["id"])

        route_business_request(_registry(_mapping()), TELEGRAM_A, Capability.PROPOSAL_CREATE)
        self.assertEqual(PHASE1.read_bytes(), phase1_before)
        self.assertEqual(ROSTER.read_bytes(), roster_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
