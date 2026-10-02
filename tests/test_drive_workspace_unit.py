#!/usr/bin/env python3
"""Unit tests for Mission Control Drive workspace mapping (no network/write)."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_plugin_api_workspace_test", PLUGIN_PATH)
_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plugin)


class TestDriveWorkspaceMapping(unittest.TestCase):
    def test_reuses_persisted_folder_without_drive_call(self):
        agent = {"id": "agent-one", "name": "Agent One"}
        existing = {
            "folder_id": "folder-existing",
            "name": "Mission Control Workspace - agent-one",
            "status": "ready",
        }
        with patch.object(_plugin, "_drive_command") as drive:
            result = _plugin._ensure_agent_workspace(agent, existing)
        self.assertEqual(result["folder_id"], "folder-existing")
        self.assertEqual(result["status"], "ready")
        drive.assert_not_called()

    def test_creates_existing_root_then_agent_folder(self):
        agent = {"id": "agent-two", "name": "Agent Two"}
        responses = [
            {"files": [{"id": "root-1", "name": "DEMA AI AGENT", "mimeType": "application/vnd.google-apps.folder"}]},
            {"files": [{"id": "workspace-1", "name": "Mission Control Workspace - agent-two", "mimeType": "application/vnd.google-apps.folder", "webViewLink": "https://drive.google.com/drive/folders/workspace-1"}]},
        ]
        with patch.object(_plugin, "_drive_command", side_effect=responses) as drive:
            result = _plugin._ensure_agent_workspace(agent, {})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["folder_id"], "workspace-1")
        self.assertEqual(result["name"], "Mission Control Workspace - agent-two")
        self.assertEqual(result["webViewLink"], "https://drive.google.com/drive/folders/workspace-1")
        self.assertEqual(drive.call_count, 2)

    def test_creates_root_when_missing_without_duplicate_lookup(self):
        agent = {"id": "agent-three", "name": "Agent Three"}
        responses = [
            {"files": []},
            {"id": "root-new", "name": "DEMA AI AGENT", "mimeType": "application/vnd.google-apps.folder"},
            {"files": []},
            {"id": "workspace-new", "name": "Mission Control Workspace - agent-three", "mimeType": "application/vnd.google-apps.folder"},
        ]
        with patch.object(_plugin, "_drive_command", side_effect=responses) as drive:
            result = _plugin._ensure_agent_workspace(agent, {})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["folder_id"], "workspace-new")
        self.assertEqual(drive.call_count, 4)

    def test_drive_unavailable_is_honest_and_secret_free(self):
        agent = {"id": "agent-four", "name": "Agent Four"}
        secret = "super-secret-token-value"
        with patch.dict(os.environ, {"TEST_SECRET_TOKEN": secret}, clear=False), patch.object(
            _plugin, "_drive_command", side_effect=RuntimeError(f"wrapper failed token={secret}")
        ):
            result = _plugin._ensure_agent_workspace(agent, {})
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("error", result)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("access_token", encoded.lower())

    def test_drive_upload_runs_from_upload_parent_and_passes_relative_media_path(self):
        upload_dir = Path("/opt/data/cache/scratch")
        upload_path = upload_dir / "drive-upload-test.txt"
        upload_path.write_text("projection", encoding="utf-8")
        fake_proc = type("Proc", (), {"returncode": 0, "stdout": '{"id":"file-1"}', "stderr": ""})()
        try:
            with patch.object(_plugin.subprocess, "run", return_value=fake_proc) as run:
                result = _plugin._drive_command(
                    ["drive", "files", "create"],
                    upload=upload_path,
                    upload_content_type="text/plain",
                )
            self.assertEqual(result["id"], "file-1")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--upload") + 1], upload_path.name)
            self.assertEqual(run.call_args.kwargs["cwd"], str(upload_dir))
        finally:
            upload_path.unlink(missing_ok=True)
