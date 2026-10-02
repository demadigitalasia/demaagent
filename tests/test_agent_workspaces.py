import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
ROSTER = Path("/opt/data/mission-control/agents.json")


def current_knowledge_agent_ids():
    rows = json.loads(ROSTER.read_text(encoding="utf-8"))
    return tuple(sorted(
        row["id"] for row in rows
        if {"obsidian", "llm-wiki"}.issubset(set(row.get("skills") or []))
        and row.get("id") != "opencode"
    ))


AGENT_IDS = current_knowledge_agent_ids()
PRIMARY_AGENT_ID = AGENT_IDS[0]
SECONDARY_AGENT_ID = AGENT_IDS[1]


def response_json(value):
    if isinstance(value, dict):
        return 200, value
    return value.status_code, json.loads(value.body.decode("utf-8"))


class TestAgentWorkspaceTemporaryVault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("mission_control_agent_workspace_test", PLUGIN)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-agent-workspaces-")
        self.root = Path(self.tmp.name)
        (self.root / "10-Wiki/concepts").mkdir(parents=True)
        (self.root / "10-Wiki/index.md").write_text(
            "---\ntype: index\nstatus: active\n---\n# Shared Index\n\n[[10-Wiki/concepts/Agent Knowledge Workflow]]\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki/concepts/Agent Knowledge Workflow.md").write_text(
            "---\ntype: procedure\nstatus: active\n---\n# Shared Workflow\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki/concepts/Agent Workspace Access Model.md").write_text(
            "---\ntype: procedure\nstatus: active\n---\n# Shared Access Model\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki/SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
        for agent_id in AGENT_IDS:
            folder = self.root / "30-Agents" / agent_id
            folder.mkdir(parents=True)
            (folder / "README.md").write_text(
                f"---\nagent_id: {agent_id}\nscope: private\n---\n# {agent_id}\n\n[[10-Wiki/index]]\n",
                encoding="utf-8",
            )
        primary_folder = self.root / "30-Agents" / PRIMARY_AGENT_ID
        secondary_folder = self.root / "30-Agents" / SECONDARY_AGENT_ID
        (primary_folder / "private.md").write_text(
            f"# Private\nonly {PRIMARY_AGENT_ID}\n", encoding="utf-8"
        )
        (secondary_folder / "private.md").write_text(
            "# Other Private\nmust not cross scope\n", encoding="utf-8"
        )
        try:
            (primary_folder / "symlink.md").symlink_to(secondary_folder / "private.md")
        except OSError:
            self.skipTest("symlink not supported by test filesystem")
        self.roster = [{"id": agent_id, "name": agent_id, "role": "test", "skills": ["obsidian", "llm-wiki"]}
                       for agent_id in AGENT_IDS]
        self.original_root = self.module._obsidian_root
        self.original_loader = self.module._load_agents
        self.module._obsidian_root = lambda: (self.root, "test-vault")
        self.module._load_agents = lambda: self.roster

    def tearDown(self):
        self.module._obsidian_root = self.original_root
        self.module._load_agents = self.original_loader
        self.tmp.cleanup()

    def test_namespace_creation_and_readback_are_bounded(self):
        status, body = response_json(self.module.obsidian_agent_workspaces())
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], len(AGENT_IDS))
        self.assertEqual({row["agent_id"] for row in body["workspaces"]}, set(AGENT_IDS))
        self.assertEqual(body["namespace_readiness"]["ready_count"], len(AGENT_IDS))
        self.assertEqual(set(body["namespace_readiness"]["ready_agent_ids"]), set(AGENT_IDS))
        self.assertTrue(all(row["status"] == "ready" for row in body["workspaces"]))
        status2, detail = response_json(self.module.obsidian_agent_workspace(PRIMARY_AGENT_ID))
        self.assertEqual(status2, 200)
        self.assertIn("README.md", {row["workspace_relative_path"] for row in detail["workspace"]["notes"]})
        self.assertGreaterEqual(len(detail["shared_context"]), 3)

    def test_valid_invalid_and_executor_agent_ids(self):
        status, body = response_json(self.module.obsidian_agent_workspace("not-an-agent"))
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], "error")
        status2, body2 = response_json(self.module.obsidian_agent_workspace("opencode"))
        self.assertEqual(status2, 403)
        self.assertIn("executor-only", body2["error"])
        status3, body3 = response_json(self.module.obsidian_agent_workspace(PRIMARY_AGENT_ID + "\x00"))
        self.assertEqual(status3, 400)

    def test_cross_agent_traversal_nul_backslash_core_and_raw_paths_rejected(self):
        rejected = [
            f"30-Agents/{SECONDARY_AGENT_ID}/private.md",
            f"../{SECONDARY_AGENT_ID}/private.md",
            "nested/../../private.md",
            "nested\\private.md",
            "bad\x00.md",
            f"/opt/data/obsidian-vault/30-Agents/{PRIMARY_AGENT_ID}/README.md",
            "MEMORY.md",
            "USER.md",
            "00-Hermes/Memory Index.md",
        ]
        for raw in rejected:
            status, body = response_json(self.module._agent_workspace_read(PRIMARY_AGENT_ID, raw))
            self.assertEqual(status, 400, raw)
            self.assertEqual(body["status"], "error")

    def test_symlink_and_cross_agent_reads_do_not_escape_scope(self):
        status, _body = response_json(self.module._agent_workspace_read(PRIMARY_AGENT_ID, "symlink.md"))
        self.assertEqual(status, 404)
        status2, _body2 = response_json(self.module._agent_workspace_read(PRIMARY_AGENT_ID, f"30-Agents/{SECONDARY_AGENT_ID}/private.md"))
        self.assertEqual(status2, 400)

    def test_shared_context_and_scoped_graph_include_only_private_plus_wiki(self):
        status, detail = response_json(self.module.obsidian_agent_workspace(PRIMARY_AGENT_ID))
        self.assertEqual(status, 200)
        shared_paths = {row["relative_path"] for row in detail["shared_context"]}
        self.assertIn("10-Wiki/index.md", shared_paths)
        status_read, shared_note = response_json(self.module._agent_workspace_read(PRIMARY_AGENT_ID, "10-Wiki/index.md"))
        self.assertEqual(status_read, 200)
        self.assertEqual(shared_note["scope"], "shared_10_wiki")
        status2, graph = response_json(self.module.obsidian_agent_workspace_graph(PRIMARY_AGENT_ID, path="README.md", depth=1, max_notes=40, max_bytes=60000))
        self.assertEqual(status2, 200)
        graph_paths = {row["relative_path"] for row in graph["notes"]}
        self.assertIn(f"30-Agents/{PRIMARY_AGENT_ID}/README.md", graph_paths)
        self.assertTrue(all(path.startswith(f"30-Agents/{PRIMARY_AGENT_ID}/") or path.startswith("10-Wiki/") for path in graph_paths))
        self.assertNotIn(f"30-Agents/{SECONDARY_AGENT_ID}/private.md", graph_paths)

    def test_list_and_graph_limits_are_bounded(self):
        folder = self.root / "30-Agents" / PRIMARY_AGENT_ID
        for index in range(80):
            (folder / f"note-{index:02d}.md").write_text(f"# Note {index}\n", encoding="utf-8")
        status, detail = response_json(self.module._agent_workspace_list(PRIMARY_AGENT_ID))
        self.assertEqual(status, 200)
        self.assertLessEqual(len(detail["workspace"]["notes"]), 50)
        status2, graph = response_json(self.module.obsidian_agent_workspace_graph(PRIMARY_AGENT_ID, path="README.md", max_notes=40, max_bytes=5000))
        self.assertEqual(status2, 200)
        self.assertLessEqual(len(graph["notes"]), 40)
        self.assertLessEqual(graph["context"]["content_bytes"], 5000)

    def test_proposal_only_write_readback_and_no_secret_response(self):
        status, body = response_json(self.module._agent_workspace_proposal(
            PRIMARY_AGENT_ID, {"path": "notes/proposed.md", "title": "A proposal", "content": "review me"}
        ))
        self.assertEqual(status, 200)
        self.assertFalse(body["private_note_written"])
        self.assertTrue(body["approval_required"])
        target = self.root / "30-Agents" / PRIMARY_AGENT_ID / "notes/proposed.md"
        self.assertFalse(target.exists())
        proposal = self.root / body["proposal"]["relative_path"]
        self.assertTrue(proposal.is_file())
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("api_key", "access_token", "client_secret", "password", "/opt/data/"):
            self.assertNotIn(marker, encoded)

    def test_proposal_rejects_private_cross_scope_and_secret_content(self):
        for raw in (f"30-Agents/{SECONDARY_AGENT_ID}/new.md", "../new.md", "MEMORY.md", "new\\file.md"):
            status, _body = response_json(self.module._agent_workspace_proposal(
                PRIMARY_AGENT_ID, {"path": raw, "content": "x"}
            ))
            self.assertEqual(status, 400, raw)
        status2, body2 = response_json(self.module._agent_workspace_proposal(
            PRIMARY_AGENT_ID, {"path": "secret.md", "content": "api_key: real-secret-value"}
        ))
        self.assertEqual(status2, 400)
        self.assertIn("credential", body2["error"])


class TestApprovedNamespaceInitialization(unittest.TestCase):
    APPROVED = {
        "hermes-lead",
        "document-knowledge",
        "social-research-trends",
        "content-planner-copywriter",
        "backend-data",
        "frontend-product-ui",
    }

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("mission_control_namespace_init_test", PLUGIN)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-namespace-init-")
        self.root = Path(self.tmp.name)
        (self.root / "10-Wiki").mkdir(parents=True)
        (self.root / "10-Wiki/index.md").write_text("# Shared index\n", encoding="utf-8")
        (self.root / "10-Wiki/SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
        legacy = self.root / "30-Agents/agent-engineer"
        legacy.mkdir(parents=True)
        (legacy / "README.md").write_text("legacy marker\n", encoding="utf-8")
        hermes = self.root / "30-Agents/hermes-lead"
        hermes.mkdir(parents=True)
        (hermes / "README.md").write_text("existing approved marker\n", encoding="utf-8")
        self.core_before = {
            path: path.read_bytes()
            for path in (self.root / "10-Wiki/index.md", self.root / "10-Wiki/SCHEMA.md")
        }
        self.roster = [
            {"id": agent_id, "name": agent_id, "skills": ["obsidian", "llm-wiki"]}
            for agent_id in sorted(self.APPROVED | {"backend-data", "frontend-product-ui"})
        ]
        self.roster.append({"id": "agent-engineer", "name": "Agent Engineer", "skills": ["mission-control"]})
        self.original_root = self.module._obsidian_root
        self.original_loader = self.module._load_agents
        self.module._obsidian_root = lambda: (self.root, "test-vault")
        self.module._load_agents = lambda: self.roster

    def tearDown(self):
        self.module._obsidian_root = self.original_root
        self.module._load_agents = self.original_loader
        self.tmp.cleanup()

    def test_initialization_is_exact_idempotent_and_does_not_expand_acl_or_touch_core(self):
        first = self.module.initialize_approved_agent_namespaces()
        self.assertEqual(first["status"], "ok")
        expected_ids = self.APPROVED | {"agent-engineer"}
        self.assertEqual(set(first["agent_ids"]), expected_ids)
        self.assertEqual(set(first["created_agent_ids"]), expected_ids)
        self.assertEqual(first["already_ready_agent_ids"], [])
        self.assertEqual(first["readback"]["verified"], True)
        self.assertEqual(self.module._knowledge_agent_ids(), self.APPROVED)

        folders = {path.name for path in (self.root / "30-Agents").iterdir() if path.is_dir()}
        self.assertEqual(folders, expected_ids)
        for agent_id in expected_ids:
            manifest = json.loads((self.root / "30-Agents" / agent_id / "mission-control-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["agent_id"], agent_id)
            self.assertEqual(manifest["scope"], f"30-Agents/{agent_id}")
        self.assertEqual(
            (self.root / "30-Agents/hermes-lead/README.md").read_text(encoding="utf-8"),
            "existing approved marker\n",
        )
        self.assertEqual((self.root / "30-Agents/agent-engineer/README.md").read_text(encoding="utf-8"), "legacy marker\n")
        self.assertEqual({path: path.read_bytes() for path in self.core_before}, self.core_before)

        snapshot = {
            path: path.read_bytes()
            for path in (self.root / "30-Agents").rglob("README.md")
        }
        second = self.module.initialize_approved_agent_namespaces()
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["created_agent_ids"], [])
        self.assertEqual(second["already_ready_agent_ids"], sorted(expected_ids))
        self.assertEqual(
            {path: path.read_bytes() for path in (self.root / "30-Agents").rglob("README.md")},
            snapshot,
        )
        encoded = json.dumps({"first": first, "second": second}, ensure_ascii=False).lower()
        for marker in ("api_key", "access_token", "password", "client_secret", "/opt/data/"):
            self.assertNotIn(marker, encoded)

    def test_initialization_rejects_non_approved_or_non_knowledge_agents(self):
        for invalid in (["backend-data"], [1]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.module.initialize_approved_agent_namespaces(invalid)
        with self.assertRaises(ValueError):
            self.module.initialize_approved_agent_namespaces(["agent-engineer"])


if __name__ == "__main__":
    unittest.main()
