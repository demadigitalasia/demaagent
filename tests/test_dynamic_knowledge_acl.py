import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
LAUNCHER_PATH = Path("/opt/data/scripts/mission_control_runtime_launcher.py")
ROSTER_PATH = Path("/opt/data/mission-control/agents.json")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DynamicKnowledgeAclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_module(PLUGIN_PATH, "mission_control_dynamic_acl_plugin")
        cls.launcher = load_module(LAUNCHER_PATH, "mission_control_dynamic_acl_launcher")

    def test_runtime_acl_derives_current_roster_knowledge_skills_not_legacy_ids(self):
        roster = [
            {"id": "hermes-lead", "skills": ["obsidian", "llm-wiki"]},
            {"id": "current-knowledge", "skills": ["obsidian", "llm-wiki"]},
            {"id": "current-obsidian-only", "skills": ["obsidian"]},
            {"id": "opencode", "skills": ["opencode"]},
            {"id": "current-knowledge-2", "skills": ["obsidian", "llm-wiki"]},
        ]
        with patch.object(self.plugin, "_load_agents", return_value=roster):
            self.assertEqual(
                self.plugin._knowledge_agent_ids(),
                {"hermes-lead", "current-knowledge", "current-knowledge-2"},
            )
            record, error = self.plugin._agent_workspace_record("current-knowledge")
            self.assertIsNone(error)
            self.assertEqual(record["id"], "current-knowledge")
            _record, deleted_error = self.plugin._agent_workspace_record("deleted-legacy-agent")
            self.assertEqual(deleted_error.status_code, 404)
            self.assertIsNone(
                self.plugin._runtime_identity_from_claims({
                    "agent_id": "deleted-legacy-agent", "sub": "deleted-legacy-agent",
                    "jti": "jti", "scope": ["workspace:read"],
                })
            )

    def test_launcher_allowlist_matches_current_roster_and_excludes_executor(self):
        roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        expected = {
            row["id"] for row in roster
            if {"obsidian", "llm-wiki"}.issubset(set(row.get("skills") or []))
        }
        self.assertNotIn("opencode", expected)
        with patch.object(self.plugin, "_load_agents", return_value=roster):
            allowlist = self.launcher._knowledge_agent_allowlist(self.plugin)
        self.assertEqual(allowlist, frozenset(expected))
        self.assertNotIn("deleted-legacy-agent", allowlist)
        self.assertNotIn("legacy-news-agent", allowlist)

    def test_agent_live_uses_runtime_adapter_metadata_for_non_special_id(self):
        source = {
            "agents": {
                "agent_engineer": {
                    "status": "ok",
                    "rows": [{"active": True}],
                },
                "delegations": {
                    "status": "ok",
                    "states": {"running": 1, "completed": 0},
                },
            }
        }
        with patch.object(self.plugin, "_cached", return_value=source):
            live = self.plugin._agent_live({
                "id": "new-engineering-agent",
                "routing": {"runtime_adapter": "agent_engineer", "runtime_mode": "specialist"},
            })
        self.assertEqual(live["status"], "online")
        self.assertEqual(live["source_status"], "ok")

    def test_agent_live_provider_oneshot_is_configured_but_not_running(self):
        live = self.plugin._agent_live({
            "id": "new-specialist",
            "model": "opencode-go/deepseek-v4-flash",
            "drive_workspace": {"status": "ready"},
            "routing": {"runtime_adapter": "provider_oneshot", "runtime_mode": "specialist"},
        })
        self.assertEqual(live["status"], "standby")
        self.assertEqual(live["source_status"], "configured")
        self.assertEqual(live["runtime_adapter"], "provider_oneshot")
        self.assertIn("one-shot", live["detail"])

    def test_agent_live_unknown_ordinary_agent_stays_explicitly_not_configured(self):
        with patch.object(self.plugin, "_cached", return_value={"agents": {}}):
            live = self.plugin._agent_live({
                "id": "new-ordinary-agent",
                "routing": {"runtime_mode": "specialist"},
            })
        self.assertEqual(live["status"], "standby")
        self.assertEqual(live["source_status"], "not_configured")


if __name__ == "__main__":
    unittest.main(verbosity=2)
