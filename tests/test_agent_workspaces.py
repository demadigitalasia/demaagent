import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
AGENT_IDS = (
    "hermes-lead",
    "agent-engineer",
    "agent-socmed",
    "news-agent",
    "sub-agent-back-end",
    "sub-agent-devops",
    "sub-agent-front-end",
    "sub-agent-ui-ux",
)


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
        (self.root / "30-Agents/hermes-lead/private.md").write_text(
            "# Private\nonly hermes-lead\n", encoding="utf-8"
        )
        (self.root / "30-Agents/agent-engineer/private.md").write_text(
            "# Other Private\nmust not cross scope\n", encoding="utf-8"
        )
        try:
            (self.root / "30-Agents/hermes-lead/symlink.md").symlink_to(
                self.root / "30-Agents/agent-engineer/private.md"
            )
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
        self.assertEqual(body["count"], 8)
        self.assertEqual({row["agent_id"] for row in body["workspaces"]}, set(AGENT_IDS))
        self.assertTrue(all(row["status"] == "ready" for row in body["workspaces"]))
        status2, detail = response_json(self.module.obsidian_agent_workspace("hermes-lead"))
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
        status3, body3 = response_json(self.module.obsidian_agent_workspace("hermes-lead\x00"))
        self.assertEqual(status3, 400)

    def test_cross_agent_traversal_nul_backslash_core_and_raw_paths_rejected(self):
        rejected = [
            "30-Agents/agent-engineer/private.md",
            "../agent-engineer/private.md",
            "nested/../../private.md",
            "nested\\private.md",
            "bad\x00.md",
            "/opt/data/obsidian-vault/30-Agents/hermes-lead/README.md",
            "MEMORY.md",
            "USER.md",
            "00-Hermes/Memory Index.md",
        ]
        for raw in rejected:
            status, body = response_json(self.module._agent_workspace_read("hermes-lead", raw))
            self.assertEqual(status, 400, raw)
            self.assertEqual(body["status"], "error")

    def test_symlink_and_cross_agent_reads_do_not_escape_scope(self):
        status, _body = response_json(self.module._agent_workspace_read("hermes-lead", "symlink.md"))
        self.assertEqual(status, 404)
        status2, _body2 = response_json(self.module._agent_workspace_read("hermes-lead", "30-Agents/agent-engineer/private.md"))
        self.assertEqual(status2, 400)

    def test_shared_context_and_scoped_graph_include_only_private_plus_wiki(self):
        status, detail = response_json(self.module.obsidian_agent_workspace("hermes-lead"))
        self.assertEqual(status, 200)
        shared_paths = {row["relative_path"] for row in detail["shared_context"]}
        self.assertIn("10-Wiki/index.md", shared_paths)
        status_read, shared_note = response_json(self.module._agent_workspace_read("hermes-lead", "10-Wiki/index.md"))
        self.assertEqual(status_read, 200)
        self.assertEqual(shared_note["scope"], "shared_10_wiki")
        status2, graph = response_json(self.module.obsidian_agent_workspace_graph("hermes-lead", path="README.md", depth=1, max_notes=40, max_bytes=60000))
        self.assertEqual(status2, 200)
        graph_paths = {row["relative_path"] for row in graph["notes"]}
        self.assertIn("30-Agents/hermes-lead/README.md", graph_paths)
        self.assertTrue(all(path.startswith("30-Agents/hermes-lead/") or path.startswith("10-Wiki/") for path in graph_paths))
        self.assertNotIn("30-Agents/agent-engineer/private.md", graph_paths)

    def test_list_and_graph_limits_are_bounded(self):
        folder = self.root / "30-Agents/hermes-lead"
        for index in range(80):
            (folder / f"note-{index:02d}.md").write_text(f"# Note {index}\n", encoding="utf-8")
        status, detail = response_json(self.module._agent_workspace_list("hermes-lead"))
        self.assertEqual(status, 200)
        self.assertLessEqual(len(detail["workspace"]["notes"]), 50)
        status2, graph = response_json(self.module.obsidian_agent_workspace_graph("hermes-lead", path="README.md", max_notes=40, max_bytes=5000))
        self.assertEqual(status2, 200)
        self.assertLessEqual(len(graph["notes"]), 40)
        self.assertLessEqual(graph["context"]["content_bytes"], 5000)

    def test_proposal_only_write_readback_and_no_secret_response(self):
        status, body = response_json(self.module._agent_workspace_proposal(
            "hermes-lead", {"path": "notes/proposed.md", "title": "A proposal", "content": "review me"}
        ))
        self.assertEqual(status, 200)
        self.assertFalse(body["private_note_written"])
        self.assertTrue(body["approval_required"])
        target = self.root / "30-Agents/hermes-lead/notes/proposed.md"
        self.assertFalse(target.exists())
        proposal = self.root / body["proposal"]["relative_path"]
        self.assertTrue(proposal.is_file())
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("api_key", "access_token", "client_secret", "password", "/opt/data/"):
            self.assertNotIn(marker, encoded)

    def test_proposal_rejects_private_cross_scope_and_secret_content(self):
        for raw in ("30-Agents/agent-engineer/new.md", "../new.md", "MEMORY.md", "new\\file.md"):
            status, _body = response_json(self.module._agent_workspace_proposal(
                "hermes-lead", {"path": raw, "content": "x"}
            ))
            self.assertEqual(status, 400, raw)
        status2, body2 = response_json(self.module._agent_workspace_proposal(
            "hermes-lead", {"path": "secret.md", "content": "api_key: real-secret-value"}
        ))
        self.assertEqual(status2, 400)
        self.assertIn("credential", body2["error"])


if __name__ == "__main__":
    unittest.main()
