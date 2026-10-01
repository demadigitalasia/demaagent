import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path("/opt/data/scripts")
BRIDGE_PATH = SCRIPTS / "mission_control_runtime_mcp_server.py"
PYTHON = Path("/opt/hermes/.venv/bin/python")


def _load_bridge():
    spec = importlib.util.spec_from_file_location("mission_control_runtime_mcp_bridge_test", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.body = json.dumps(payload or {}).encode("utf-8")
        self.headers = {}


class FakeRuntimeClient:
    def __init__(self, agent_id="agent-engineer", scopes=None):
        self.agent_id = agent_id
        self.scopes = sorted(scopes or ["workspace:read", "proposal:create"])
        self.token = "not-a-real-bearer-token"
        self.calls = []
        self.payload = {
            "status": "ok",
            "workspace": {
                "agent_id": agent_id,
                "notes": [{"relative_path": "README.md", "scope": "private_agent_namespace"}],
            },
            "shared_context": [{"relative_path": "10-Wiki/index.md", "scope": "shared_10_wiki"}],
            "runtime_identity": {"verified": True, "agent_id": agent_id, "scopes": self.scopes},
        }

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, None))
        if "/graph" in path:
            return FakeResponse(payload={"status": "ok", "notes": [], "scope": {"private": "own", "shared": "10-Wiki"}})
        if "/notes/" in path:
            return FakeResponse(payload={"status": "ok", "relative_path": "README.md", "content": "private"})
        return FakeResponse(payload=self.payload)

    def post_json(self, path, payload, **kwargs):
        self.calls.append(("POST", path, payload))
        return FakeResponse(payload={
            "status": "ok",
            "private_note_written": False,
            "approval_required": True,
            "proposal": {"relative_path": "40-Inbox/Agent-Workspace/agent-engineer/id.md", "status": "pending"},
        })


class RuntimeMcpBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = _load_bridge()

    def _call(self, server, name, arguments):
        result = asyncio.run(server.call_tool(name, arguments))
        self.assertFalse(getattr(result, "is_error", False), result)
        self.assertTrue(result.content)
        return json.loads(result.content[0].text)

    def test_protocol_discovery_and_scoped_tools(self):
        client = FakeRuntimeClient()
        server, _runtime = self.bridge.build_server(client=client, max_calls=20, max_duration_s=60)
        tools = asyncio.run(server.list_tools())
        names = {tool.name for tool in tools}
        self.assertEqual(names, {
            "workspace_list",
            "workspace_shared_context",
            "workspace_read",
            "workspace_graph",
            "workspace_create_proposal",
        })
        listed = self._call(server, "workspace_list", {})
        self.assertEqual(listed["runtime_identity"]["agent_id"], "agent-engineer")
        shared = self._call(server, "workspace_shared_context", {})
        self.assertEqual(shared["shared_context"][0]["scope"], "shared_10_wiki")

    def test_read_graph_and_proposal_use_runtime_client_scope(self):
        client = FakeRuntimeClient()
        server, _runtime = self.bridge.build_server(client=client, max_calls=20, max_duration_s=60)
        read = self._call(server, "workspace_read", {"path": "README.md"})
        self.assertEqual(read["relative_path"], "README.md")
        graph = self._call(server, "workspace_graph", {"path": "README.md", "depth": 1})
        self.assertEqual(graph["scope"]["shared"], "10-Wiki")
        proposal = self._call(server, "workspace_create_proposal", {
            "path": "notes/proposed.md",
            "title": "Proposal",
            "content": "pending review",
        })
        self.assertTrue(proposal["approval_required"])
        self.assertFalse(proposal["private_note_written"])
        method, route, payload = client.calls[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(route, "/runtime-api/obsidian/workspace/proposals")
        self.assertNotIn("agent_id", payload)

    def test_cross_agent_path_validation_and_proposal_scope(self):
        read_only = FakeRuntimeClient(scopes=["workspace:read"])
        server, _runtime = self.bridge.build_server(client=read_only, max_calls=20, max_duration_s=60)
        for args in (
            {"path": "30-Agents/other/private.md"},
            {"path": "../private.md"},
            {"path": "/absolute.md"},
            {"path": "nested\\private.md"},
            {"path": "MEMORY.md"},
        ):
            result = self._call(server, "workspace_read", args)
            self.assertEqual(result["status"], "error")
        denied = self._call(server, "workspace_create_proposal", {
            "path": "notes/new.md", "content": "x",
        })
        self.assertEqual(denied["status"], "error")
        self.assertNotIn("token", json.dumps(denied).lower())

    def test_safe_errors_remove_token_like_values_and_paths(self):
        class BrokenClient(FakeRuntimeClient):
            def get(self, path, **kwargs):
                raise self.bridge_error("Bearer fake-token-value /opt/data/secret")

            @staticmethod
            def bridge_error(message):
                from mission_control_runtime_client import RuntimeClientError
                return RuntimeClientError(message)

        client = BrokenClient()
        server, _runtime = self.bridge.build_server(client=client, max_calls=20, max_duration_s=60)
        result = self._call(server, "workspace_list", {})
        text = json.dumps(result)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("fake-token-value", text)
        self.assertNotIn("/opt/data/", text)
        self.assertNotIn("Bearer ", text)

    def test_long_lived_bridge_reuses_one_client_and_enforces_call_bound(self):
        client = FakeRuntimeClient()
        server, runtime = self.bridge.build_server(client=client, max_calls=2, max_duration_s=60)
        self._call(server, "workspace_list", {})
        self._call(server, "workspace_shared_context", {})
        self.assertEqual(runtime.calls, 2)
        third = self._call(server, "workspace_list", {})
        self.assertEqual(third["status"], "error")
        self.assertIn("bounded", third["error"])
        self.assertTrue(runtime.shutdown_requested.is_set())

    def test_long_lived_bridge_refreshes_one_runtime_client_in_memory(self):
        import base64

        def make_token(expiry):
            payload = {
                "agent_id": "agent-engineer",
                "sub": "agent-engineer",
                "scope": ["proposal:create", "workspace:read"],
                "iat": 0,
                "exp": expiry,
                "refresh_until": 100,
            }
            encode = lambda value: base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":")).encode("utf-8")
            ).rstrip(b"=").decode("ascii")
            return f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(payload)}.signature"

        initial = make_token(1)
        rotated = make_token(90)
        events = []

        class OpenResponse:
            def __init__(self, payload):
                self.status = 200
                self.body = json.dumps(payload).encode("utf-8")
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return self.body

        def opener(request, timeout=10):
            del timeout
            if request.get_method() == "POST":
                events.append("refresh")
                return OpenResponse({"token": rotated})
            events.append("get")
            return OpenResponse({
                "status": "ok",
                "runtime_identity": {"agent_id": "agent-engineer"},
                "workspace": {"notes": []},
                "shared_context": [],
            })

        from mission_control_runtime_client import RuntimeClient

        client = RuntimeClient(
            base_url="http://runtime.test",
            token=initial,
            agent_id="agent-engineer",
            refresh_url="http://runtime.test/runtime-api/auth/refresh",
            issued_at=0,
            expires_at=1,
            refresh_until=100,
            scopes=["workspace:read", "proposal:create"],
            safety_margin_s=30,
            opener=opener,
            clock=lambda: 50,
        )
        server, runtime = self.bridge.build_server(client=client, max_calls=10, max_duration_s=60)
        self._call(server, "workspace_list", {})
        self._call(server, "workspace_shared_context", {})
        self.assertEqual(events, ["refresh", "get", "get"])
        self.assertEqual(client.token, rotated)
        self.assertEqual(runtime.calls, 2)
        self.assertEqual(client.agent_id, "agent-engineer")

    def test_duration_bound_is_enforced_without_files(self):
        client = FakeRuntimeClient()
        server, runtime = self.bridge.build_server(client=client, max_calls=20, max_duration_s=0.01)
        # The guard is monotonic and does not create any state on disk.
        import time
        time.sleep(0.03)
        result = self._call(server, "workspace_list", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("duration", result["error"])
        with tempfile.TemporaryDirectory(prefix="mc-mcp-bridge-files-") as cwd:
            self.assertEqual(list(Path(cwd).rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
