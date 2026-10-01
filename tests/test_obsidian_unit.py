#!/usr/bin/env python3
"""Focused read-only Obsidian vault tests using a temporary fixture vault."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_obsidian_test_plugin", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def status_of(value):
    return getattr(value, "status_code", 200)


def body_of(value):
    body = getattr(value, "body", None)
    if body is None:
        return value
    return json.loads(body.decode("utf-8"))


class ObsidianVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        self.root.mkdir()
        (self.root / "Welcome.md").write_text("# Welcome\nA safe note.\n", encoding="utf-8")
        nested = self.root / "Projects"
        nested.mkdir()
        (nested / "Roadmap.md").write_text("# Roadmap\nneedle appears here.\n", encoding="utf-8")
        (nested / "Credentials.md").write_text(
            "# Credentials\napi_key: super-secret-value\npassword = top-secret-value\nneedle\n",
            encoding="utf-8",
        )
        (nested / "not-markdown.txt").write_text("needle", encoding="utf-8")
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("# Outside\nsecret outside\n", encoding="utf-8")
        (nested / "escape.md").symlink_to(outside)
        (nested / "too-big.md").write_text("x" * (plugin.OBSIDIAN_MAX_FILE_BYTES + 1), encoding="utf-8")
        for index in range(plugin.OBSIDIAN_MAX_NOTE_LIST + 5):
            (self.root / "bounded" / f"Note-{index:03d}.md").parent.mkdir(exist_ok=True)
            (self.root / "bounded" / f"Note-{index:03d}.md").write_text(
                f"# Note {index}\n", encoding="utf-8"
            )
        self.old_env = os.environ.get("OBSIDIAN_VAULT_PATH")
        os.environ["OBSIDIAN_VAULT_PATH"] = str(self.root)
        plugin._cache.clear()

    def tearDown(self):
        plugin._cache.clear()
        if self.old_env is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = self.old_env
        self.tmp.cleanup()

    def test_status_lists_bounded_safe_metadata_without_absolute_path(self):
        result = plugin.obsidian()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["vault_path"], "configured vault")
        self.assertGreaterEqual(result["note_count"], plugin.OBSIDIAN_MAX_NOTE_LIST)
        self.assertLessEqual(len(result["notes"]), plugin.OBSIDIAN_MAX_NOTE_LIST)
        self.assertGreaterEqual(result["folder_count"], 2)
        encoded = json.dumps(result)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("super-secret-value", encoded)
        self.assertTrue(all(set(note) >= {"relative_path", "title", "folder", "size", "updated"} for note in result["notes"]))

    def test_search_matches_filename_and_content_with_redacted_snippet(self):
        result = plugin.obsidian_notes(query="needle", folder="Projects", limit=100)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["folder"], "Projects")
        self.assertGreaterEqual(result["count"], 2)
        self.assertTrue(any(row["relative_path"] == "Projects/Roadmap.md" for row in result["results"]))
        encoded = json.dumps(result)
        self.assertNotIn("super-secret-value", encoded)
        self.assertNotIn("top-secret-value", encoded)
        self.assertTrue(all(len(row.get("snippet", "")) <= plugin.OBSIDIAN_SNIPPET_MAX for row in result["results"]))

    def test_read_returns_redacted_content_and_metadata(self):
        result = plugin.obsidian_note("Projects/Credentials.md")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["relative_path"], "Projects/Credentials.md")
        self.assertTrue(result["redacted"])
        self.assertNotIn("super-secret-value", result["content"])
        self.assertNotIn("top-secret-value", result["content"])
        self.assertIn("[redacted]", result["content"])

    def test_missing_vault_is_graceful_and_does_not_leak_path(self):
        missing = Path(self.tmp.name) / "missing-vault"
        with patch.dict(os.environ, {"OBSIDIAN_VAULT_PATH": str(missing)}):
            plugin._cache.clear()
            status = plugin.obsidian()
            search = plugin.obsidian_notes(query="x")
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(search["status"], "unavailable")
        self.assertNotIn(str(missing), json.dumps(status))
        self.assertNotIn(str(missing), json.dumps(search))

    def test_read_rejects_traversal_nul_non_markdown_oversized_and_symlink_escape(self):
        for path in ("../outside.md", "Projects/../outside.md", "Projects/bad\x00.md", "Projects/not-markdown.txt", "Projects/too-big.md", "Projects/escape.md"):
            result = body_of(plugin.obsidian_note(path))
            self.assertIn(status_of(plugin.obsidian_note(path)), (400, 404, 413), path)
            self.assertEqual(result.get("status"), "error")
            self.assertNotIn(str(self.root), json.dumps(result))

    def test_limits_are_bounded_and_invalid_query_rejected(self):
        result = plugin.obsidian_notes(query="", limit=999999)
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(result["limit"], plugin.OBSIDIAN_MAX_SEARCH_LIMIT)
        self.assertLessEqual(len(result["results"]), plugin.OBSIDIAN_MAX_SEARCH_LIMIT)
        invalid = plugin.obsidian_notes(query="x" * (plugin.OBSIDIAN_QUERY_MAX + 1), limit=10)
        self.assertEqual(status_of(invalid), 400)
        self.assertEqual(body_of(invalid)["status"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
