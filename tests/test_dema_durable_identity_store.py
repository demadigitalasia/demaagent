#!/usr/bin/env python3
"""Focused TDD tests for the internal durable identity/audit foundation."""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from business_gateway.identity_store import (  # noqa: E402
    AmbiguousIdentityMapping,
    AuditMetadataError,
    DuplicateIdentityMapping,
    PlatformAdminMappingError,
    initialize_identity_store,
)
from business_gateway.tenant_boundary import (  # noqa: E402
    Capability,
    IdentityMapping,
    IdentityStatus,
    Role,
    build_identity_registry,
    route_business_request,
)


ROSTER = BASE / "agents.json"
PHASE1 = BASE / "catalog" / "dema-phase1-runtime-readiness-v1.json"
SERVER = BASE / "server.py"
PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
TELEGRAM_A = "00090000000000000001"
TELEGRAM_B = "00090000000000000002"


class TestDemaDurableIdentityStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dema-identity-store-")
        self.db_path = Path(self.tmp.name) / "identity.sqlite3"
        self.store = initialize_identity_store(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add_a(self, **overrides):
        values = {
            "telegram_user_id": TELEGRAM_A,
            "user_id": "fixture-user-a",
            "tenant_id": "fixture-tenant-a",
            "role": Role.USER,
            "status": IdentityStatus.ACTIVE,
            "actor_type": "system",
            "actor_id": "unit-test",
            "audit_metadata": {"source": "unit-test"},
        }
        values.update(overrides)
        return self.store.add_mapping(**values)

    def test_schema_creation_and_persistence_across_reopen(self):
        self.add_a()
        self.store.close()
        reopened = initialize_identity_store(self.db_path)
        self.store = reopened

        resolved = reopened.resolve_mapping(TELEGRAM_A)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.telegram_user_id, TELEGRAM_A)
        self.assertEqual(resolved.user_id, "fixture-user-a")
        self.assertEqual(resolved.tenant_id, "fixture-tenant-a")
        self.assertEqual(resolved.role, Role.USER)
        self.assertEqual(resolved.status, IdentityStatus.ACTIVE)
        self.assertTrue(resolved.created_at)
        self.assertEqual(resolved.created_at, resolved.updated_at)

        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue({"identity_mappings", "audit_events"} <= tables)
            mapping_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(identity_mappings)")
            }
            self.assertEqual(
                mapping_columns,
                {
                    "telegram_user_id",
                    "user_id",
                    "tenant_id",
                    "role",
                    "status",
                    "created_at",
                    "updated_at",
                },
            )
        finally:
            connection.close()

    def test_exact_literal_telegram_id_is_preserved(self):
        literal = "000123"
        stored = self.store.add_mapping(
            telegram_user_id=literal,
            user_id="fixture-user-literal",
            tenant_id="fixture-tenant-a",
            role=Role.USER,
            status=IdentityStatus.ACTIVE,
            actor_type="system",
            actor_id="unit-test",
        )
        self.assertEqual(stored.telegram_user_id, literal)
        self.assertEqual(self.store.resolve_mapping(literal).telegram_user_id, literal)

    def test_duplicate_telegram_mapping_is_rejected_without_replacement(self):
        first = self.add_a()
        with self.assertRaises(DuplicateIdentityMapping):
            self.add_a(user_id="fixture-user-other")
        current = self.store.resolve_mapping(TELEGRAM_A)
        self.assertEqual(current.user_id, first.user_id)
        self.assertEqual(len(self.store.read_audit_events()), 1)

    def test_ambiguous_same_user_across_tenants_is_rejected(self):
        self.add_a()
        with self.assertRaises(AmbiguousIdentityMapping):
            self.store.add_mapping(
                telegram_user_id=TELEGRAM_B,
                user_id="fixture-user-a",
                tenant_id="fixture-tenant-b",
                role=Role.USER,
                status=IdentityStatus.ACTIVE,
                actor_type="system",
                actor_id="unit-test",
            )
        self.assertIsNone(self.store.resolve_mapping(TELEGRAM_B))
        self.assertEqual(len(self.store.read_audit_events()), 1)

    def test_platform_admin_is_rejected_from_telegram_mapping(self):
        with self.assertRaises(PlatformAdminMappingError):
            self.add_a(role=Role.PLATFORM_ADMIN)
        self.assertIsNone(self.store.resolve_mapping(TELEGRAM_A))
        self.assertEqual(self.store.read_audit_events(), ())

    def test_status_update_persists_and_policy_denies_inactive_identity(self):
        self.add_a()
        updated = self.store.set_mapping_status(
            TELEGRAM_A,
            IdentityStatus.SUSPENDED,
            actor_type="system",
            actor_id="unit-test",
            audit_metadata={"reason": "review"},
        )
        self.assertEqual(updated.status, IdentityStatus.SUSPENDED)
        resolved = self.store.resolve_mapping(TELEGRAM_A)
        self.assertEqual(resolved.status, IdentityStatus.SUSPENDED)

        registry = build_identity_registry(
            [
                IdentityMapping(
                    telegram_user_id=resolved.telegram_user_id,
                    user_id=resolved.user_id,
                    tenant_id=resolved.tenant_id,
                    role=resolved.role,
                    status=resolved.status,
                )
            ]
        )
        decision = route_business_request(
            registry,
            TELEGRAM_A,
            Capability.BUSINESS_REQUEST,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_not_active")
        self.assertEqual(len(self.store.read_audit_events()), 2)

    def test_transaction_rolls_back_when_audit_append_fails(self):
        with patch.object(self.store, "_append_audit", side_effect=RuntimeError("audit failure")):
            with self.assertRaises(RuntimeError):
                self.add_a()
        self.assertIsNone(self.store.resolve_mapping(TELEGRAM_A))
        self.assertEqual(self.store.read_audit_events(), ())

    def test_transaction_rolls_back_when_audit_metadata_is_unsafe(self):
        with self.assertRaises(AuditMetadataError):
            self.add_a(audit_metadata={"token": "sk-test-1234567890"})
        self.assertIsNone(self.store.resolve_mapping(TELEGRAM_A))
        self.assertEqual(self.store.read_audit_events(), ())

    def test_audit_contains_safe_metadata_and_deterministic_fingerprint_only(self):
        self.add_a(audit_metadata={"source": "unit-test", "attempt": 1})
        event = self.store.read_audit_events()[0]
        self.assertEqual(
            event.identity_fingerprint,
            hashlib.sha256(TELEGRAM_A.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(event.action, "mapping.added")
        self.assertEqual(event.actor_type, "system")
        self.assertEqual(event.actor_id, "unit-test")
        self.assertEqual(event.target_type, "identity_mapping")
        self.assertEqual(event.result, "success")
        self.assertEqual(event.metadata, {"attempt": 1, "source": "unit-test"})

        serialized = json.dumps(event.metadata, sort_keys=True)
        self.assertNotIn(TELEGRAM_A, serialized)
        self.assertNotIn("sk-test", serialized)
        self.assertNotIn("password", serialized.lower())
        self.assertNotIn("token", serialized.lower())
        self.assertEqual(len(event.identity_fingerprint), 64)

    def test_unknown_identity_returns_none_and_policy_denies(self):
        self.assertIsNone(self.store.resolve_mapping("99999999999999999999"))
        self.assertIsNone(self.store.resolve_mapping("not-a-telegram-id"))

        decision = route_business_request(
            build_identity_registry(()),
            "99999999999999999999",
            Capability.CATALOG_LOOKUP,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unknown_telegram_identity")

    def test_invalid_status_and_metadata_are_fail_closed(self):
        with self.assertRaises(ValueError):
            self.add_a(status="not-a-status")
        with self.assertRaises(AuditMetadataError):
            self.add_a(audit_metadata={"telegram_user_id": TELEGRAM_A})
        self.assertIsNone(self.store.resolve_mapping(TELEGRAM_A))

    def test_existing_roster_phase1_namespace_and_server_wiring_remain_unchanged(self):
        roster_before = ROSTER.read_bytes()
        phase1_before = PHASE1.read_bytes()
        roster = json.loads(roster_before)
        self.assertEqual(len(roster), len({row["id"] for row in roster}))
        self.assertNotIn("dema-assistant", {row["id"] for row in roster})
        self.assertNotIn("dema-lead", {row["id"] for row in roster})
        for row in roster:
            self.assertIs(row.get("active"), False, row["id"])
        for entry in json.loads(phase1_before)["candidate_entries"]:
            for flag in ("configured", "tested", "on_demand_ready", "approved_for_users", "active"):
                self.assertIs(entry["lifecycle"][flag], False)

        tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
        namespace_ids = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(isinstance(target, ast.Name) and target.id == "OBSIDIAN_AGENT_IDS" for target in targets):
                namespace_ids = tuple(ast.literal_eval(node.value))
                break
        self.assertIsNotNone(namespace_ids)
        self.assertEqual(namespace_ids, ())
        self.assertNotIn("identity_store", SERVER.read_text(encoding="utf-8"))
        self.assertNotIn("identity_store", PLUGIN.read_text(encoding="utf-8"))

        self.add_a()
        self.assertEqual(ROSTER.read_bytes(), roster_before)
        self.assertEqual(PHASE1.read_bytes(), phase1_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
