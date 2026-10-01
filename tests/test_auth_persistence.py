#!/usr/bin/env python3
"""Persistence tests for owner sessions and runtime-token revocations."""
import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

PROJECT = Path("/opt/data/mission-control")
SERVER_PATH = PROJECT / "server.py"
PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AuthPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-auth-persistence-")
        self.db_path = Path(self.tmp.name) / "auth_state.db"
        self.env = patch.dict(
            os.environ,
            {
                "MISSION_CONTROL_AUTH_STATE_DB": str(self.db_path),
                "MISSION_CONTROL_RUNTIME_TOKEN_SECRET": "p" * 48,
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "persist-user",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "persist-pass",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_owner_session_survives_server_module_reload(self):
        first = load_module(SERVER_PATH, "mission_control_persistence_server_first")
        first_client = TestClient(first.app)
        response = first_client.post(
            "/auth/login", json={"username": "persist-user", "password": "persist-pass"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        session = response.cookies.get("mc_session")
        csrf = response.cookies.get("mc_csrf")
        self.assertTrue(session)
        self.assertTrue(csrf)
        first_client.close()

        second = load_module(SERVER_PATH, "mission_control_persistence_server_second")
        second_client = TestClient(second.app)
        second_client.cookies.set("mc_session", session, path="/")
        second_client.cookies.set("mc_csrf", csrf, path="/")
        restored = second_client.get("/auth/session")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertGreater(restored.json().get("expires_in_s", 0), 0)
        second_client.close()

        self.assertTrue(self.db_path.is_file())
        self.assertEqual(self.db_path.stat().st_mode & 0o077, 0)

    def test_expired_owner_session_is_pruned_after_reload(self):
        first = load_module(SERVER_PATH, "mission_control_persistence_expiry_first")
        client = TestClient(first.app)
        response = client.post(
            "/auth/login", json={"username": "persist-user", "password": "persist-pass"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        session = response.cookies.get("mc_session")
        csrf = response.cookies.get("mc_csrf")
        client.close()

        session_hash = hashlib.sha256(session.encode()).hexdigest()
        self.assertTrue(self.db_path.is_file(), "auth state database must be created")
        connection = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            connection.close()
        self.assertIn("owner_sessions", tables)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE owner_sessions SET expires_at = ? WHERE session_hash = ?",
                (time.time() - 1, session_hash),
            )
            connection.commit()
        finally:
            connection.close()

        second = load_module(SERVER_PATH, "mission_control_persistence_expiry_second")
        client = TestClient(second.app)
        client.cookies.set("mc_session", session, path="/")
        client.cookies.set("mc_csrf", csrf, path="/")
        denied = client.get("/auth/session")
        self.assertEqual(denied.status_code, 401, denied.text)
        client.close()

        connection = sqlite3.connect(self.db_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM owner_sessions WHERE session_hash = ?",
                (session_hash,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_runtime_revocation_survives_plugin_module_reload(self):
        first = load_module(PLUGIN_PATH, "mission_control_persistence_plugin_first")
        token_id = "persisted-runtime-jti"
        self.assertTrue(first.revoke_runtime_token(token_id, expires_at=time.time() + 300))
        self.assertTrue(first.is_runtime_token_revoked(token_id))

        second = load_module(PLUGIN_PATH, "mission_control_persistence_plugin_second")
        self.assertTrue(second.is_runtime_token_revoked(token_id))
        second._prune_runtime_revocations(now=time.time() + 301)
        self.assertFalse(second.is_runtime_token_revoked(token_id))

    def test_legacy_plain_runtime_revocation_is_migrated_to_hash(self):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "CREATE TABLE runtime_token_revocations ("
                "token_id TEXT PRIMARY KEY, expires_at REAL NOT NULL, revoked_at REAL NOT NULL)"
            )
            connection.execute(
                "INSERT INTO runtime_token_revocations(token_id, expires_at, revoked_at) VALUES (?, ?, ?)",
                ("legacy-jti", time.time() + 300, time.time()),
            )
            connection.commit()
        finally:
            connection.close()

        plugin = load_module(PLUGIN_PATH, "mission_control_persistence_plugin_migration")
        self.assertTrue(plugin.is_runtime_token_revoked("legacy-jti"))
        connection = sqlite3.connect(self.db_path)
        try:
            stored = connection.execute(
                "SELECT token_id FROM runtime_token_revocations"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotIn(b"legacy-jti", stored.encode())
        self.assertTrue(stored.startswith("sha256:"))

    def test_runtime_revocation_storage_never_contains_raw_bearer_token(self):
        plugin = load_module(PLUGIN_PATH, "mission_control_persistence_plugin_secret")
        token = plugin.encode_runtime_token(
            "agent-engineer", scopes=["workspace:read"], ttl_s=300, jti="storage-jti"
        )
        claims = plugin.decode_runtime_token(token)
        self.assertIsNotNone(claims)
        self.assertTrue(plugin.revoke_runtime_token(claims["jti"], expires_at=time.time() + 300))
        self.assertTrue(self.db_path.is_file(), "auth state database must be created")
        stored = self.db_path.read_bytes()
        self.assertNotIn(token.encode(), stored)
        self.assertNotIn(claims["jti"].encode(), stored)
        self.assertNotIn(b"MISSION_CONTROL_RUNTIME_TOKEN_SECRET", stored)


if __name__ == "__main__":
    unittest.main(verbosity=2)
