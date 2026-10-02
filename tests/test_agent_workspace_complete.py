import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
ROSTER_PATH = Path("/opt/data/mission-control/agents.json")


def load_plugin(name):
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response_json(value):
    if isinstance(value, dict):
        return 200, value
    return value.status_code, json.loads(value.body.decode("utf-8"))


class TestCompleteAgentWorkspaceProvisioning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_plugin("mission_control_complete_workspace_test")
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        cls.agent_ids = [row["id"] for row in cls.roster]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-complete-workspace-")
        self.root = Path(self.tmp.name)
        (self.root / "10-Wiki").mkdir(parents=True)
        (self.root / "10-Wiki/index.md").write_text("# Shared index\n", encoding="utf-8")
        (self.root / "10-Wiki/SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
        (self.root / "10-Wiki/log.md").write_text("# Log\n", encoding="utf-8")
        (self.root / "30-Agents").mkdir()
        owner_dir = self.root / "30-Agents" / "agent-engineer"
        owner_dir.mkdir()
        self.owner_readme = "owner content must survive\n"
        (owner_dir / "README.md").write_text(self.owner_readme, encoding="utf-8")
        self.original_root = self.module._obsidian_root
        self.original_loader = self.module._load_agents
        self.module._obsidian_root = lambda: (self.root, "test-vault")
        self.module._load_agents = lambda: copy.deepcopy(self.roster)

    def tearDown(self):
        self.module._obsidian_root = self.original_root
        self.module._load_agents = self.original_loader
        self.tmp.cleanup()

    def test_all_dynamic_agents_get_private_namespace_and_scoped_manifests(self):
        result = self.module.initialize_approved_agent_namespaces()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["agent_ids"], sorted(self.agent_ids))
        self.assertEqual(result["readback"], {"verified": True, "count": len(self.agent_ids)})
        self.assertEqual(set(result["created_agent_ids"]), set(self.agent_ids))

        for agent_id in self.agent_ids:
            base = self.root / "30-Agents" / agent_id
            self.assertTrue(base.is_dir(), agent_id)
            manifest = json.loads((base / "mission-control-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["agent_id"], agent_id)
            self.assertEqual(manifest["scope"], f"30-Agents/{agent_id}")
            self.assertEqual(manifest["learning"]["state"], "not_evaluated")
            self.assertNotIn("score", json.dumps(manifest))
            self.assertTrue((base / "profile/persona.md").is_file())
            self.assertTrue((base / "profile/governance.json").is_file())
            self.assertTrue((base / "profile/routing.json").is_file())
            self.assertTrue((base / "skills/assigned-skills.json").is_file())
            self.assertTrue((base / "learning/state.json").is_file())

        self.assertEqual((self.root / "30-Agents/agent-engineer/README.md").read_text(encoding="utf-8"), self.owner_readme)

    def test_repeat_is_idempotent_and_preserves_core_and_owner_files(self):
        first = self.module.initialize_approved_agent_namespaces()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        second = self.module.initialize_approved_agent_namespaces()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(second["created_agent_ids"], [])
        self.assertEqual(second["already_ready_agent_ids"], sorted(self.agent_ids))
        self.assertEqual(before, after)
        self.assertEqual(first["core_readback"], second["core_readback"])
        self.assertEqual((self.root / "10-Wiki/index.md").read_text(), "# Shared index\n")
        self.assertEqual((self.root / "10-Wiki/SCHEMA.md").read_text(), "# Schema\n")
        self.assertEqual((self.root / "10-Wiki/log.md").read_text(), "# Log\n")

    def test_cross_agent_symlink_and_path_escape_are_rejected(self):
        first = self.module.initialize_approved_agent_namespaces()
        self.assertEqual(first["status"], "ok")
        source = self.root / "30-Agents/personal-assistant/private.md"
        source.write_text("private", encoding="utf-8")
        link = self.root / "30-Agents/hermes-lead/escape.md"
        try:
            link.symlink_to(source)
        except OSError:
            self.skipTest("symlink unsupported")
        for raw in ("../personal-assistant/private.md", "30-Agents/personal-assistant/private.md", "/absolute.md", "bad\\path.md", "bad\x00.md"):
            status, body = response_json(self.module._agent_workspace_read("hermes-lead", raw))
            self.assertEqual(status, 400, raw)
            self.assertEqual(body["status"], "error")
        status, _body = response_json(self.module._agent_workspace_read("hermes-lead", "escape.md"))
        self.assertEqual(status, 404)

    def test_generated_artifacts_have_no_secrets_or_absolute_paths(self):
        result = self.module.initialize_approved_agent_namespaces()
        encoded = json.dumps(result, ensure_ascii=False).lower()
        for marker in ("api_key:", "access_token:", "client_secret:", "bearer ", "/opt/data/"):
            self.assertNotIn(marker, encoded)
        for path in (self.root / "30-Agents").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/opt/data/", text)
                self.assertNotIn("api_key:", text.lower())

    def test_roster_models_and_active_flags_are_unchanged(self):
        before = {row["id"]: {
            "model": row.get("model"),
            "active": row.get("active"),
            "system": row.get("system"),
            "cron": row.get("cron"),
            "runtime": row.get("runtime"),
            "autonomy": row.get("autonomy"),
        } for row in self.roster}
        self.module.initialize_approved_agent_namespaces()
        after = {row["id"]: {
            "model": row.get("model"),
            "active": row.get("active"),
            "system": row.get("system"),
            "cron": row.get("cron"),
            "runtime": row.get("runtime"),
            "autonomy": row.get("autonomy"),
        } for row in self.roster}
        self.assertEqual(before, after)


class TestDriveWorkspaceStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_plugin("mission_control_drive_complete_workspace_test")
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))

    def test_reconcile_builds_complete_structure_from_existing_mappings(self):
        calls = []
        existing = {}
        objects = {}
        for row in self.roster:
            workspace = row.get("drive_workspace") or {}
            if workspace.get("status") != "ready":
                continue
            folder = {
                "id": workspace["folder_id"],
                "name": workspace["name"],
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [workspace["root_folder_id"]],
            }
            existing.setdefault(workspace["folder_id"], [])
            objects[workspace["folder_id"]] = folder

        def fake_command(args, *, params=None, body=None, upload=None, upload_content_type=None):
            calls.append((args, params, body, upload, upload_content_type))
            if args[-2:] == ["files", "get"]:
                return objects[params["fileId"]]
            if args[-2:] == ["files", "list"]:
                import re
                query = (params or {}).get("q", "")
                match = re.search(r"'([^']+)' in parents", query)
                parent = match.group(1) if match else ""
                rows = list(existing.get(parent, []))
                name_match = re.search(r"name = '([^']+)'", query)
                if name_match:
                    rows = [row for row in rows if row.get("name") == name_match.group(1)]
                mime_match = re.search(r"mimeType = '([^']+)'", query)
                if mime_match:
                    rows = [row for row in rows if row.get("mimeType") == mime_match.group(1)]
                return {"files": rows}
            if args[-2:] == ["files", "create"]:
                body = body or {}
                parent = (body.get("parents") or [None])[0]
                name = body.get("name")
                new_id = f"new-{len(calls)}"
                mime = body.get("mimeType") or ("application/vnd.google-apps.folder" if upload is None else "text/markdown")
                row = {"id": new_id, "name": name, "mimeType": mime, "parents": [parent] if parent else []}
                objects[new_id] = row
                existing.setdefault(parent, []).append(row)
                return row
            self.fail(f"unexpected command {args}")

        with patch.object(self.module, "_drive_command", side_effect=fake_command):
            result = self.module.reconcile_all_agent_workspaces(self.roster)
        self.assertEqual(result["count"], len(self.roster))
        expected_ready = sum(
            (row.get("drive_workspace") or {}).get("status") == "ready"
            for row in self.roster
        )
        self.assertEqual(result["ready_count"], expected_ready)
        self.assertEqual(len({row["agent_id"] for row in result["workspaces"]}), len(self.roster))
        self.assertEqual(
            len({row["folder_id"] for row in result["workspaces"] if row.get("folder_id")}),
            expected_ready,
        )
        self.assertEqual(
            {row["folder_id"] for row in result["workspaces"] if row.get("folder_id")},
            {
                row["drive_workspace"]["folder_id"]
                for row in self.roster
                if (row.get("drive_workspace") or {}).get("status") == "ready"
            },
        )
        for row in result["workspaces"]:
            if row["status"] == "ready":
                self.assertEqual(row["structure"]["status"], "ready")
                self.assertIn("profile/persona.md", row["structure"]["paths"])
                self.assertIn("learning/state.json", row["structure"]["paths"])
            else:
                self.assertEqual(row["status"], "pending")
                self.assertEqual(row["structure"]["status"], "pending")

    def test_drive_ambiguity_returns_pending_without_choosing_arbitrarily(self):
        row = self.roster[0]
        folder_id = row["drive_workspace"]["folder_id"]
        with patch.object(self.module, "_drive_get_file", return_value={
            "id": folder_id,
            "name": row["drive_workspace"]["name"],
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [row["drive_workspace"]["root_folder_id"]],
        }), patch.object(self.module, "_drive_exact_child", return_value=[
            {"id": "duplicate-a", "name": "profile", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "duplicate-b", "name": "profile", "mimeType": "application/vnd.google-apps.folder"},
        ]):
            result = self.module.reconcile_all_agent_workspaces([row])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["workspaces"][0]["status"], "pending")
        self.assertEqual(result["workspaces"][0]["error"], "ambiguous workspace structure")

    def test_drive_unavailable_returns_precise_status_without_fake_completion(self):
        rows = copy.deepcopy(self.roster)
        with patch.object(self.module, "_drive_command", side_effect=FileNotFoundError("gws unavailable")):
            result = self.module.reconcile_all_agent_workspaces(rows)
        self.assertEqual(result["count"], len(self.roster))
        self.assertEqual(result["ready_count"], 0)
        expected_pending = sum(
            (row.get("drive_workspace") or {}).get("status") != "ready"
            for row in self.roster
        )
        self.assertEqual(result["unavailable_count"], len(self.roster) - expected_pending)
        self.assertEqual(result["pending_count"], expected_pending)
        self.assertTrue(all(row["status"] in {"unavailable", "pending"} for row in result["workspaces"]))
        encoded = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("fake", encoded)
        self.assertNotIn("/opt/data/", encoded)

    def test_roster_reconcile_backfills_missing_mapping_before_structure_readback(self):
        rows = copy.deepcopy(self.roster)
        pending = next(row for row in rows if row["id"] == "content-intake-concierge")
        pending["drive_workspace"] = {
            "name": "Mission Control Workspace - content-intake-concierge",
            "status": "pending",
        }
        saved = []

        def ensure_all(current):
            current[-1]["drive_workspace"] = {
                "name": "Mission Control Workspace - content-intake-concierge",
                "status": "ready",
                "folder_id": "folder-content-intake",
                "root_folder_id": "root",
            }
            return True

        expected = {"status": "ready", "count": len(rows)}
        with patch.object(self.module, "_load_agents", return_value=rows), \
             patch.object(self.module, "_ensure_all_agent_workspaces", side_effect=ensure_all) as ensure, \
             patch.object(self.module, "_save_agents", side_effect=lambda current: saved.append(current)), \
             patch.object(self.module, "reconcile_all_agent_workspaces", return_value=expected) as reconcile:
            result = self.module.agent_workspaces_reconcile({})

        self.assertEqual(result, expected)
        ensure.assert_called_once_with(rows)
        reconcile.assert_called_once_with(rows)
        self.assertEqual(len(saved), 1)
        self.assertEqual(rows[-1]["drive_workspace"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
