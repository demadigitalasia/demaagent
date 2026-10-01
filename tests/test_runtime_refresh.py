import base64
import hashlib
import hmac
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient


PROJECT = Path("/opt/data/mission-control")
PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
CLIENT_PATH = Path("/opt/data/scripts/mission_control_runtime_client.py")
ROSTER_PATH = PROJECT / "agents.json"


def current_knowledge_agent_ids():
    rows = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    return tuple(sorted(
        row["id"] for row in rows
        if {"obsidian", "llm-wiki"}.issubset(set(row.get("skills") or []))
        and row.get("id") != "opencode"
    ))


AGENT_IDS = current_knowledge_agent_ids()
PRIMARY_AGENT_ID = AGENT_IDS[0]
TEST_SECRET = "runtime-refresh-test-secret-0123456789"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    os.sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeRefreshAclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(PROJECT) not in os.sys.path:
            os.sys.path.insert(0, str(PROJECT))
        server = _load(PROJECT / "server.py", "mission_control_runtime_refresh_server")
        cls.server = server
        cls.plugin = server._plugin

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-runtime-refresh-")
        self.root = Path(self.tmp.name)
        (self.root / "10-Wiki/concepts").mkdir(parents=True)
        for relative, text in {
            "10-Wiki/index.md": "# Shared\n",
            "10-Wiki/concepts/Agent Workspace Access Model.md": "# Access\n",
        }.items():
            (self.root / relative).write_text(text, encoding="utf-8")
        self.roster = []
        for agent_id in AGENT_IDS:
            folder = self.root / "30-Agents" / agent_id
            folder.mkdir(parents=True)
            (folder / "README.md").write_text(f"# {agent_id}\n", encoding="utf-8")
            self.roster.append({
                "id": agent_id,
                "name": agent_id,
                "role": "test",
                "skills": ["obsidian", "llm-wiki"],
            })
        self.original_root = self.plugin._obsidian_root
        self.original_loader = self.plugin._load_agents
        self.plugin._obsidian_root = lambda: (self.root, "test-vault")
        self.plugin._load_agents = lambda: self.roster
        self.env = patch.dict(
            os.environ,
            {
                "MISSION_CONTROL_RUNTIME_TOKEN_SECRET": TEST_SECRET,
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "runtime-user",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "runtime-pass",
            },
            clear=False,
        )
        self.env.start()
        self.plugin._runtime_revoked_tokens.clear()
        self.client = TestClient(self.server.app)

    def tearDown(self):
        self.client.close()
        self.plugin._runtime_revoked_tokens.clear()
        self.env.stop()
        self.plugin._obsidian_root = self.original_root
        self.plugin._load_agents = self.original_loader
        self.tmp.cleanup()

    def _login(self):
        response = self.client.post(
            "/auth/login", json={"username": "runtime-user", "password": "runtime-pass"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        session = response.cookies.get("mc_session")
        csrf = response.cookies.get("mc_csrf")
        self.assertTrue(session)
        self.assertTrue(csrf)
        self.client.cookies.clear()
        self.client.cookies.set("mc_session", session, path="/")
        self.client.cookies.set("mc_csrf", csrf, path="/")

    def _owner_headers(self):
        return {"X-CSRF-Token": self.client.cookies.get("mc_csrf")}

    def _mint(self, agent_id=PRIMARY_AGENT_ID, scopes=None, ttl_s=900):
        self._login()
        payload = {"agent_id": agent_id, "ttl_s": ttl_s}
        if scopes is not None:
            payload["scopes"] = scopes
        response = self.client.post(
            "/api/obsidian/runtime-tokens",
            headers=self._owner_headers(),
            json=payload,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _resign(self, token, updates=None, remove=()):
        parts = token.split(".")
        payload = json.loads(self.plugin._b64url_decode(parts[1]).decode("utf-8"))
        for key in remove:
            payload.pop(key, None)
        payload.update(updates or {})
        encoded_payload = self.plugin._b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{parts[0]}.{encoded_payload}".encode("ascii")
        signature = hmac.new(TEST_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{parts[0]}.{encoded_payload}.{self.plugin._b64url_encode(signature)}"

    def test_encoder_and_owner_mint_add_bounded_absolute_refresh_claim(self):
        now = 1_000
        token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=60, now=now, jti="claim-test"
        )
        claims = self.plugin.decode_runtime_token(token, now=now + 1)
        self.assertEqual(claims["refresh_until"], now + self.plugin.RUNTIME_TOKEN_MAX_REFRESH_S)
        self.assertLessEqual(claims["exp"], claims["refresh_until"])
        self.assertIsNone(self.plugin.decode_runtime_token(token, now=claims["refresh_until"]))

        minted = self._mint(PRIMARY_AGENT_ID, ["workspace:read"], ttl_s=60)
        self.assertIn("refresh_until", minted)
        self.assertIsInstance(minted["refresh_until_epoch"], int)
        self.assertEqual(
            minted["refresh_until_epoch"] - minted["issued_at_epoch"],
            self.plugin.RUNTIME_TOKEN_MAX_REFRESH_S,
        )

    def test_legacy_token_remains_usable_but_cannot_refresh(self):
        minted = self._mint()
        legacy = self._resign(minted["token"], remove=("refresh_until",))
        self.assertIsNotNone(self.plugin.decode_runtime_token(legacy))
        workspace = self.client.get(
            "/runtime-api/obsidian/workspace", headers={"Authorization": f"Bearer {legacy}"}
        )
        self.assertEqual(workspace.status_code, 200, workspace.text)
        refreshed = self.client.post(
            "/runtime-api/auth/refresh", headers={"Authorization": f"Bearer {legacy}"}
        )
        self.assertEqual(refreshed.status_code, 401)
        self.assertNotIn("refresh_until", refreshed.text.lower())

    def test_refresh_preserves_identity_scope_and_absolute_boundary_old_token_stays_valid(self):
        anonymous = TestClient(self.server.app)
        anonymous_refresh = anonymous.post("/runtime-api/auth/refresh")
        self.assertEqual(anonymous_refresh.status_code, 401)
        anonymous.close()

        minted = self._mint(
            PRIMARY_AGENT_ID, ["workspace:read", "proposal:create"], ttl_s=900
        )
        old_claims = self.plugin.decode_runtime_token(minted["token"])
        response = self.client.post(
            "/runtime-api/auth/refresh",
            headers={"Authorization": f"Bearer {minted['token']}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotEqual(body["token"], minted["token"])
        self.assertEqual(body["agent_id"], PRIMARY_AGENT_ID)
        self.assertEqual(body["scopes"], ["proposal:create", "workspace:read"])
        self.assertEqual(body["refresh_until_epoch"], old_claims["refresh_until"])
        self.assertFalse(body["owner_privileges"])
        self.assertEqual(body["rotation"], "old_token_valid_until_expiry")

        old_request = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {minted['token']}"},
        )
        new_request = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {body['token']}"},
        )
        self.assertEqual(old_request.status_code, 200, old_request.text)
        self.assertEqual(new_request.status_code, 200, new_request.text)
        self.assertEqual(new_request.json()["runtime_identity"]["agent_id"], PRIMARY_AGENT_ID)
        self.assertEqual(new_request.json()["runtime_identity"]["scopes"], body["scopes"])

    def test_refresh_rejects_absolute_boundary_revocation_and_bad_signature(self):
        minted = self._mint(PRIMARY_AGENT_ID, ["workspace:read"], ttl_s=900)
        now = int(time.time())
        absolute_expired = self._resign(
            minted["token"],
            updates={"refresh_until": now - 1, "exp": now + 300},
        )
        response = self.client.post(
            "/runtime-api/auth/refresh",
            headers={"Authorization": f"Bearer {absolute_expired}"},
        )
        self.assertEqual(response.status_code, 401)

        bad_signature = minted["token"][:-1] + ("A" if minted["token"][-1] != "A" else "B")
        response = self.client.post(
            "/runtime-api/auth/refresh",
            headers={"Authorization": f"Bearer {bad_signature}"},
        )
        self.assertEqual(response.status_code, 401)

        self._login()
        revoked = self.client.post(
            "/api/obsidian/runtime-tokens/revoke",
            headers=self._owner_headers(),
            json={"token_id": minted["token_id"]},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        response = self.client.post(
            "/runtime-api/auth/refresh",
            headers={"Authorization": f"Bearer {minted['token']}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_refresh_cannot_change_agent_or_upgrade_proposal_only_scope(self):
        minted = self._mint(PRIMARY_AGENT_ID, ["proposal:create"], ttl_s=900)
        response = self.client.post(
            "/runtime-api/auth/refresh",
            headers={"Authorization": f"Bearer {minted['token']}"},
            json={"agent_id": "hermes-lead", "scopes": ["workspace:read"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["agent_id"], PRIMARY_AGENT_ID)
        self.assertEqual(body["scopes"], ["proposal:create"])
        denied = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {body['token']}"},
        )
        self.assertEqual(denied.status_code, 403)
        mismatch = self.client.post(
            "/runtime-api/obsidian/workspace/proposals",
            headers={"Authorization": f"Bearer {body['token']}"},
            json={"agent_id": "hermes-lead", "path": "new.md", "content": "x"},
        )
        self.assertEqual(mismatch.status_code, 403)


class RuntimeClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = _load(PLUGIN_PATH, "mission_control_runtime_refresh_client_plugin")
        cls.client_module = _load(CLIENT_PATH, "mission_control_runtime_client_test")

    def test_client_refreshes_in_memory_and_retries_once_without_files_or_token_output(self):
        now = int(time.time())
        old_token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=300, now=now, jti="client-old"
        )
        old_claims = self.plugin.decode_runtime_token(old_token, now=now)
        new_token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=300,
            now=now, jti="client-new", refresh_until=old_claims["refresh_until"]
        )
        refreshed = {"count": 0}
        requests = {"count": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                if self.path != "/runtime-api/auth/refresh":
                    self.send_response(404)
                    self.end_headers()
                    return
                refreshed["count"] += 1
                body = json.dumps({
                    "status": "ok", "token": new_token, "agent_id": PRIMARY_AGENT_ID,
                    "scopes": ["workspace:read"],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                requests["count"] += 1
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {new_token}":
                    body = b'{"status":"unauthorized"}'
                    self.send_response(401)
                else:
                    body = json.dumps({"status": "ok", "runtime_identity": {"agent_id": PRIMARY_AGENT_ID}}).encode("utf-8")
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="mc-runtime-client-files-") as cwd:
                before = sorted(Path(cwd).rglob("*"))
                client = self.client_module.RuntimeClient(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    token=old_token,
                    agent_id=PRIMARY_AGENT_ID,
                    expires_at=now + 1,
                    refresh_until=old_claims["refresh_until"],
                    safety_margin_s=30,
                )
                response = client.request("/runtime-api/obsidian/workspace")
                after = sorted(Path(cwd).rglob("*"))
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.body)["runtime_identity"]["agent_id"], PRIMARY_AGENT_ID)
                self.assertEqual(client.token, new_token)
                self.assertEqual(refreshed["count"], 1)
                self.assertEqual(requests["count"], 1)
                self.assertEqual(before, after)
                self.assertNotIn(old_token, response.body.decode("utf-8"))
                self.assertNotIn(new_token, response.body.decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_client_refreshes_after_single_401_and_does_not_loop(self):
        now = int(time.time())
        old_token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=300, now=now, jti="retry-old"
        )
        old_claims = self.plugin.decode_runtime_token(old_token, now=now)
        new_token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=300,
            now=now, jti="retry-new", refresh_until=old_claims["refresh_until"]
        )
        refresh_count = {"count": 0}
        get_count = {"count": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                refresh_count["count"] += 1
                body = json.dumps({"token": new_token}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                get_count["count"] += 1
                if get_count["count"] == 1:
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                body = b'{"status":"ok"}'
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = self.client_module.RuntimeClient(
                base_url=f"http://127.0.0.1:{server.server_port}",
                token=old_token,
                agent_id=PRIMARY_AGENT_ID,
                expires_at=now + 300,
                refresh_until=old_claims["refresh_until"],
                safety_margin_s=1,
            )
            response = client.request("/runtime-api/obsidian/workspace")
            self.assertEqual(response.status, 200)
            self.assertEqual(refresh_count["count"], 1)
            self.assertEqual(get_count["count"], 2)
            self.assertEqual(client.token, new_token)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
