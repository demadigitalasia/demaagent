import base64
import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT = Path("/opt/data/mission-control")
SCRIPTS = Path("/opt/data/scripts")
PYTHON = Path("/opt/hermes/.venv/bin/python")
LAUNCHER = SCRIPTS / "mission_control_runtime_launcher.py"
PROBE = SCRIPTS / "mission_control_runtime_probe.py"
ROSTER = PROJECT / "agents.json"
TEST_SECRET = b"launcher-test-secret-0123456789-abcdef"


def current_knowledge_agent_ids():
    rows = json.loads(ROSTER.read_text(encoding="utf-8"))
    return tuple(sorted(
        row["id"] for row in rows
        if {"obsidian", "llm-wiki"}.issubset(set(row.get("skills") or []))
        and row.get("id") != "opencode"
    ))


AGENT_IDS = current_knowledge_agent_ids()
PRIMARY_AGENT_ID = AGENT_IDS[0]


def _decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _verify_runtime_token(token: str, expected_agent: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(TEST_SECRET, signing_input, hashlib.sha256).digest()
    signature = _decode_b64url(parts[2])
    if not hmac.compare_digest(signature, expected):
        raise ValueError("bad signature")
    payload = json.loads(_decode_b64url(parts[1]).decode("utf-8"))
    if payload.get("agent_id") != expected_agent or payload.get("sub") != expected_agent:
        raise ValueError("wrong identity")
    if payload.get("scope") != ["workspace:read"]:
        raise ValueError("wrong scope")
    return payload


def _mock_runtime_handler(expected_agent: str):
    class MockRuntimeHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            try:
                auth = self.headers.get("Authorization", "")
                prefix = "Bearer "
                if not auth.startswith(prefix):
                    raise ValueError("missing bearer")
                claims = _verify_runtime_token(auth[len(prefix):], expected_agent)
                body = json.dumps({
                    "status": "ok",
                    "runtime_identity": {"agent_id": claims["agent_id"]},
                }).encode("utf-8")
                self.send_response(200)
            except Exception:
                body = b'{"status":"unauthorized"}'
                self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return MockRuntimeHandler


class RuntimeLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("mission_control_runtime_launcher_test", LAUNCHER)
        cls.launcher = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.launcher)

    def setUp(self):
        self.env = os.environ.copy()
        self.env["MISSION_CONTROL_RUNTIME_TOKEN_SECRET"] = TEST_SECRET.decode("ascii")
        self.env.pop("MISSION_CONTROL_RUNTIME_TOKEN", None)
        self.env.pop("MISSION_CONTROL_RUNTIME_AGENT_ID", None)
        self.env["HERMES_DASHBOARD_BASIC_AUTH_USERNAME"] = "owner-user"
        self.env["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"] = "owner-password"
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-runtime-launcher-")
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_launcher(self, *args, command=None):
        command = command or [str(PYTHON), "-c", "print('child-ok')"]
        result = subprocess.run(
            [str(PYTHON), str(LAUNCHER), *args, "--", *command],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result

    def test_child_receives_identity_scoped_token_and_owner_secrets_are_stripped(self):
        child = (
            "import os; "
            "print('agent=' + os.environ.get('MISSION_CONTROL_RUNTIME_AGENT_ID', '')); "
            "print('base=' + os.environ.get('MISSION_CONTROL_RUNTIME_BASE_URL', '')); "
            "print('refresh_url=' + os.environ.get('MISSION_CONTROL_RUNTIME_REFRESH_URL', '')); "
            "print('scopes=' + os.environ.get('MISSION_CONTROL_RUNTIME_SCOPES', '')); "
            "print('expires=' + os.environ.get('MISSION_CONTROL_RUNTIME_TOKEN_EXPIRES_AT', '')); "
            "print('refresh_until=' + os.environ.get('MISSION_CONTROL_RUNTIME_TOKEN_REFRESH_UNTIL', '')); "
            "print('token_seen=' + str(bool(os.environ.get('MISSION_CONTROL_RUNTIME_TOKEN')))); "
            "print('owner_session=' + str(bool(os.environ.get('HERMES_DASHBOARD_BASIC_AUTH_PASSWORD')))); "
            "print('owner_secret=' + str(bool(os.environ.get('MISSION_CONTROL_RUNTIME_TOKEN_SECRET')))); "
            "print('bearer=' + os.environ.get('MISSION_CONTROL_RUNTIME_TOKEN', ''))"
        )
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                result = self.run_launcher(
                    "--agent-id", agent_id,
                    command=[str(PYTHON), "-c", child],
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                output = result.stdout + result.stderr
                self.assertIn(f"agent={agent_id}", output)
                self.assertIn("base=http://127.0.0.1:9120", output)
                self.assertIn("refresh_url=http://127.0.0.1:9120/runtime-api/auth/refresh", output)
                self.assertIn("scopes=workspace:read", output)
                self.assertIn("expires=", output)
                self.assertIn("refresh_until=", output)
                self.assertIn("token_seen=True", output)
                self.assertIn("owner_session=False", output)
                self.assertIn("owner_secret=False", output)
                self.assertIn("bearer=[REDACTED_RUNTIME_TOKEN]", output)
                self.assertNotIn("MC-RUNTIME", output)

    def test_signed_token_reaches_runtime_probe_and_claim_identity_is_verified(self):
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                server = ThreadingHTTPServer(("127.0.0.1", 0), _mock_runtime_handler(agent_id))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = self.run_launcher(
                        "--agent-id", agent_id,
                        "--base-url", f"http://127.0.0.1:{server.server_port}",
                        command=[str(PYTHON), str(PROBE)],
                    )
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"agent_id": agent_id, "status": 200})
                self.assertNotIn("Bearer ", result.stdout + result.stderr)

    def test_direct_executable_reaches_runtime_probe_for_all_allowlisted_agents(self):
        self.assertTrue(LAUNCHER.is_file())
        self.assertTrue(os.access(LAUNCHER, os.X_OK))
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                server = ThreadingHTTPServer(("127.0.0.1", 0), _mock_runtime_handler(agent_id))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = subprocess.run(
                        [
                            str(LAUNCHER),
                            "--agent-id", agent_id,
                            "--base-url", f"http://127.0.0.1:{server.server_port}",
                            "--",
                            str(PYTHON), str(PROBE),
                        ],
                        cwd=self.cwd,
                        env=self.env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"agent_id": agent_id, "status": 200})
                output = result.stdout + result.stderr
                self.assertNotIn("Bearer ", output)
                self.assertNotIn("MISSION_CONTROL_RUNTIME_TOKEN", output)
                self.assertNotIn("MC-RUNTIME", output)

    def test_invalid_agents_scopes_ttl_and_cli_token_are_rejected(self):
        cases = [
            (("--agent-id", "opencode"), "opencode"),
            (("--agent-id", "unknown-agent"), "unknown-agent"),
            (("--agent-id", "../agent-engineer"), "malformed-agent"),
            (("--scope", "invalid"), "scope"),
            (("--ttl", "0"), "ttl-low"),
            (("--ttl", "901"), "ttl-high"),
            (("--ttl", "not-a-number"), "ttl-malformed"),
            (("--base-url", "not-a-url"), "base-url"),
            (("--token", "do-not-accept"), "token"),
        ]
        for args, label in cases:
            with self.subTest(label=label):
                result = self.run_launcher(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("do-not-accept", result.stdout + result.stderr)

    def test_non_knowledge_roster_agent_is_rejected(self):
        class FakePlugin:
            OBSIDIAN_AGENT_IDS = ()

            @staticmethod
            def _load_agents():
                return [
                    {"id": "knowledge-agent", "skills": ["obsidian", "llm-wiki"]},
                    {"id": "nonknowledge-agent", "skills": ["mission-control"]},
                ]

        with self.assertRaises(self.launcher.LauncherError):
            self.launcher._validate_agent(FakePlugin(), "nonknowledge-agent")

    def test_explicit_child_command_is_required(self):
        result = subprocess.run(
            [str(PYTHON), str(LAUNCHER), "--agent-id", "agent-engineer"],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("MISSION_CONTROL_RUNTIME_TOKEN", result.stdout + result.stderr)

    def test_launcher_does_not_create_token_files(self):
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                before = sorted(path.relative_to(self.cwd).as_posix() for path in self.cwd.rglob("*"))
                result = self.run_launcher("--agent-id", agent_id)
                after = sorted(path.relative_to(self.cwd).as_posix() for path in self.cwd.rglob("*"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(before, after)
                self.assertNotIn("MISSION_CONTROL_RUNTIME_TOKEN", result.stdout + result.stderr)
                self.assertNotIn("Bearer ", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
