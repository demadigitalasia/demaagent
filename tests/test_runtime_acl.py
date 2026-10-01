import importlib.util
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient


PROJECT = Path("/opt/data/mission-control")
SERVER_PATH = PROJECT / "server.py"
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
SECONDARY_AGENT_ID = AGENT_IDS[1]


class RuntimeAclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
        spec = importlib.util.spec_from_file_location("mission_control_runtime_acl_server", SERVER_PATH)
        cls.server = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.server)
        cls.plugin = cls.server._plugin

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-runtime-acl-")
        self.root = Path(self.tmp.name)
        (self.root / "10-Wiki/concepts").mkdir(parents=True)
        (self.root / "10-Wiki/index.md").write_text("# Shared\n", encoding="utf-8")
        (self.root / "10-Wiki/concepts/Agent Knowledge Workflow.md").write_text(
            "# Workflow\n", encoding="utf-8"
        )
        (self.root / "10-Wiki/concepts/Agent Workspace Access Model.md").write_text(
            "# Access\n", encoding="utf-8"
        )
        (self.root / "10-Wiki/SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
        for agent_id in AGENT_IDS:
            folder = self.root / "30-Agents" / agent_id
            folder.mkdir(parents=True)
            (folder / "README.md").write_text(
                f"---\nagent_id: {agent_id}\n---\n# {agent_id}\n",
                encoding="utf-8",
            )
        primary_folder = self.root / "30-Agents" / PRIMARY_AGENT_ID
        secondary_folder = self.root / "30-Agents" / SECONDARY_AGENT_ID
        (primary_folder / "private.md").write_text(
            "# Private A\n", encoding="utf-8"
        )
        (secondary_folder / "private.md").write_text(
            "# Private B\n", encoding="utf-8"
        )
        try:
            (primary_folder / "symlink.md").symlink_to(secondary_folder / "private.md")
        except OSError:
            self.skipTest("symlink not supported")
        self.roster = [
            {"id": agent_id, "name": agent_id, "role": "test", "skills": ["obsidian", "llm-wiki"]}
            for agent_id in AGENT_IDS
        ]
        self.original_root = self.plugin._obsidian_root
        self.original_loader = self.plugin._load_agents
        self.plugin._obsidian_root = lambda: (self.root, "test-vault")
        self.plugin._load_agents = lambda: self.roster
        self.env = patch.dict(
            os.environ,
            {
                "MISSION_CONTROL_RUNTIME_TOKEN_SECRET": "r" * 48,
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "runtime-user",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "runtime-pass",
            },
            clear=False,
        )
        self.env.start()
        self.client = TestClient(self.server.app)

    def tearDown(self):
        self.client.close()
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
        body = response.json()
        self.assertIn("token", body)
        self.assertNotIn("secret", json.dumps(body).lower())
        return body

    def _resign_with_payload(self, token, **updates):
        parts = token.split(".")
        payload = json.loads(self.plugin._b64url_decode(parts[1]).decode("utf-8"))
        payload.update(updates)
        encoded_payload = self.plugin._b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{parts[0]}.{encoded_payload}".encode("ascii")
        signature = hmac.new(b"r" * 48, signing_input, hashlib.sha256).digest()
        return f"{parts[0]}.{encoded_payload}.{self.plugin._b64url_encode(signature)}"

    def test_token_encode_decode_claims_and_tamper_expiry(self):
        token = self.plugin.encode_runtime_token(
            PRIMARY_AGENT_ID, scopes=["workspace:read"], ttl_s=60, now=1_000
        )
        claims = self.plugin.decode_runtime_token(token, now=1_001)
        self.assertEqual(claims["agent_id"], PRIMARY_AGENT_ID)
        self.assertEqual(claims["sub"], PRIMARY_AGENT_ID)
        self.assertEqual(claims["iss"], self.plugin.RUNTIME_TOKEN_ISSUER)
        self.assertEqual(claims["aud"], self.plugin.RUNTIME_TOKEN_AUDIENCE)
        self.assertEqual(claims["scope"], ["workspace:read"])
        self.assertEqual(len(token.split(".")), 3)
        tampered = token.split(".")
        tampered[2] = ("A" if tampered[2][0] != "A" else "B") + tampered[2][1:]
        self.assertIsNone(self.plugin.decode_runtime_token(".".join(tampered), now=1_001))
        self.assertIsNone(self.plugin.decode_runtime_token(token, now=1_061))
        self.assertIsNone(self.plugin.decode_runtime_token(self._resign_with_payload(token, iss="wrong"), now=1_001))
        self.assertIsNone(self.plugin.decode_runtime_token(self._resign_with_payload(token, aud="wrong"), now=1_001))

    def test_missing_secret_fails_closed(self):
        with patch.dict(os.environ, {"MISSION_CONTROL_RUNTIME_TOKEN_SECRET": ""}, clear=False):
            self.assertIsNone(self.plugin.runtime_token_secret())
            with self.assertRaises(self.plugin.RuntimeTokenConfigurationError):
                self.plugin.encode_runtime_token(PRIMARY_AGENT_ID, scopes=["workspace:read"])

    def test_mint_revoke_and_runtime_auth_boundary(self):
        minted = self._mint()
        token = minted["token"]
        self.assertEqual(minted["agent_id"], PRIMARY_AGENT_ID)
        self.assertIn("workspace:read", minted["scopes"])
        self.assertNotIn("token", json.dumps(minted.get("metadata", {})).lower())

        anon = self.client.get("/runtime-api/obsidian/workspace")
        self.assertEqual(anon.status_code, 401)
        good = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(good.status_code, 200, good.text)
        body = good.json()
        self.assertEqual(body["runtime_identity"]["agent_id"], PRIMARY_AGENT_ID)
        self.assertEqual(body["policy"]["runtime_identity"], "verified_service_token")
        self.assertEqual(body["policy"]["agent_runtime_acl"], "enforced")
        spoofed = self.client.get(
            f"/runtime-api/obsidian/workspace?agent_id={SECONDARY_AGENT_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(spoofed.status_code, 200)
        self.assertEqual(spoofed.json()["runtime_identity"]["agent_id"], PRIMARY_AGENT_ID)
        self.assertNotIn("r" * 20, good.text)

        signature_bytes = self.plugin._b64url_decode(token.split(".")[2])
        tampered_signature = bytes([signature_bytes[0] ^ 0x01]) + signature_bytes[1:]
        tampered_token = ".".join(
            token.split(".")[:2] + [self.plugin._b64url_encode(tampered_signature)]
        )
        bad_sig = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        self.assertEqual(bad_sig.status_code, 401)

        self._login()
        revoked = self.client.post(
            "/api/obsidian/runtime-tokens/revoke",
            headers=self._owner_headers(),
            json={"token_id": minted["token_id"]},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        after = self.client.get(
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(after.status_code, 401)

    def test_scope_identity_and_path_acl(self):
        read_a = self._mint(PRIMARY_AGENT_ID, ["workspace:read"])["token"]
        read_b = self._mint(SECONDARY_AGENT_ID, ["workspace:read"])["token"]
        own = self.client.get(
            "/runtime-api/obsidian/workspace/notes/private.md",
            headers={"Authorization": f"Bearer {read_a}"},
        )
        self.assertEqual(own.status_code, 200, own.text)
        self.assertIn("Private A", own.text)
        cross = self.client.get(
            f"/runtime-api/obsidian/workspace/notes/30-Agents/{SECONDARY_AGENT_ID}/private.md",
            headers={"Authorization": f"Bearer {read_a}"},
        )
        self.assertEqual(cross.status_code, 400)
        other = self.client.get(
            "/runtime-api/obsidian/workspace/notes/private.md",
            headers={"Authorization": f"Bearer {read_b}"},
        )
        self.assertEqual(other.status_code, 200, other.text)
        self.assertIn("Private B", other.text)
        traversal = self.client.get(
            f"/runtime-api/obsidian/workspace/notes/../{SECONDARY_AGENT_ID}/private.md",
            headers={"Authorization": f"Bearer {read_a}"},
        )
        self.assertIn(traversal.status_code, (400, 404))
        absolute = self.client.get(
            f"/runtime-api/obsidian/workspace/notes/%2Fopt%2Fdata%2Fobsidian-vault%2F30-Agents%2F{SECONDARY_AGENT_ID}%2Fprivate.md",
            headers={"Authorization": f"Bearer {read_a}"},
        )
        self.assertEqual(absolute.status_code, 400)
        symlink = self.client.get(
            "/runtime-api/obsidian/workspace/notes/symlink.md",
            headers={"Authorization": f"Bearer {read_a}"},
        )
        self.assertEqual(symlink.status_code, 404)

    def test_proposal_scope_only_and_no_core_promotion(self):
        read_only = self._mint(PRIMARY_AGENT_ID, ["workspace:read"])["token"]
        denied = self.client.post(
            "/runtime-api/obsidian/workspace/proposals",
            headers={"Authorization": f"Bearer {read_only}"},
            json={"path": "notes/new.md", "content": "pending"},
        )
        self.assertEqual(denied.status_code, 403)
        writer = self._mint(PRIMARY_AGENT_ID, ["proposal:create"])["token"]
        mismatch = self.client.post(
            "/runtime-api/obsidian/workspace/proposals",
            headers={"Authorization": f"Bearer {writer}"},
            json={"agent_id": SECONDARY_AGENT_ID, "path": "notes/new.md", "content": "pending"},
        )
        self.assertEqual(mismatch.status_code, 403)
        proposal = self.client.post(
            "/runtime-api/obsidian/workspace/proposals",
            headers={"Authorization": f"Bearer {writer}"},
            json={"path": "notes/new.md", "content": "pending"},
        )
        self.assertEqual(proposal.status_code, 200, proposal.text)
        body = proposal.json()
        self.assertFalse(body["private_note_written"])
        self.assertTrue(body["approval_required"])
        self.assertFalse((self.root / "30-Agents" / PRIMARY_AGENT_ID / "notes/new.md").exists())
        self.assertNotIn("/opt/data/", proposal.text)
        core = self.client.post(
            "/runtime-api/obsidian/workspace/proposals",
            headers={"Authorization": f"Bearer {writer}"},
            json={"path": "MEMORY.md", "content": "must reject"},
        )
        self.assertEqual(core.status_code, 400)

    def test_owner_routes_remain_session_scoped_and_unknown_agents_rejected(self):
        anonymous = TestClient(self.server.app)
        denied = anonymous.post("/api/obsidian/runtime-tokens", json={"agent_id": PRIMARY_AGENT_ID})
        self.assertEqual(denied.status_code, 401)
        anonymous.close()
        self._login()
        owner = self.client.get(f"/api/obsidian/agent-workspaces/{PRIMARY_AGENT_ID}")
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertEqual(owner.json()["policy"]["scope"], "owner_control_plane")
        unknown = self.client.post(
            "/api/obsidian/runtime-tokens",
            headers=self._owner_headers(),
            json={"agent_id": "opencode"},
        )
        self.assertEqual(unknown.status_code, 403)
        unknown2 = self.client.post(
            "/api/obsidian/runtime-tokens",
            headers=self._owner_headers(),
            json={"agent_id": "unknown-agent"},
        )
        self.assertEqual(unknown2.status_code, 404)
        no_runtime_list = self.client.get("/runtime-api/obsidian/agent-workspaces")
        self.assertEqual(no_runtime_list.status_code, 404)

    def test_namespace_initializer_requires_owner_csrf_and_reads_back_exact_approved_slice(self):
        anonymous = TestClient(self.server.app)
        denied = anonymous.post("/api/obsidian/agent-workspaces/initialize", json={})
        self.assertEqual(denied.status_code, 401)
        anonymous.close()

        self._login()
        missing_csrf = self.client.post("/api/obsidian/agent-workspaces/initialize", json={})
        self.assertEqual(missing_csrf.status_code, 403)
        initialized = self.client.post(
            "/api/obsidian/agent-workspaces/initialize",
            headers=self._owner_headers(),
            json={},
        )
        self.assertEqual(initialized.status_code, 200, initialized.text)
        body = initialized.json()
        self.assertEqual(
            set(body["agent_ids"]),
            {"hermes-lead", "document-knowledge", "social-research-trends", "content-planner-copywriter"},
        )
        self.assertEqual(body["readback"]["count"], 4)
        self.assertTrue(body["readback"]["verified"])
        self.assertNotIn("/opt/data/", initialized.text)
        repeated = self.client.post(
            "/api/obsidian/agent-workspaces/initialize",
            headers=self._owner_headers(),
            json={},
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["created_agent_ids"], [])

    def test_validly_signed_unknown_and_opencode_tokens_are_forbidden(self):
        for agent_id in ("opencode", "unknown-agent"):
            token = self.plugin.encode_runtime_token(agent_id, scopes=["workspace:read"])
            response = self.client.get(
                "/runtime-api/obsidian/workspace",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 403, agent_id)


if __name__ == "__main__":
    unittest.main()
