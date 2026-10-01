#!/usr/bin/env python3
"""Focused graph/write Obsidian tests using a temporary fixture vault."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_obsidian_graph_test_plugin", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def status_of(value):
    return getattr(value, "status_code", 200)


def body_of(value):
    body = getattr(value, "body", None)
    if body is None:
        return value
    return json.loads(body.decode("utf-8"))


class ObsidianGraphWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        self.root.mkdir()
        (self.root / "Seed.md").write_text(
            "# Seed\n\n[[Projects/Roadmap.md]]\n[[Missing.md]]\n",
            encoding="utf-8",
        )
        projects = self.root / "Projects"
        projects.mkdir()
        (projects / "Roadmap.md").write_text(
            "# Roadmap\n\n[[Projects/Deep.md]]\n",
            encoding="utf-8",
        )
        (projects / "Deep.md").write_text(
            "# Deep\n\nA bounded graph fixture.\n",
            encoding="utf-8",
        )
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        (self.root / "escape.md").symlink_to(outside)
        (self.root / "Secrets.md").write_text(
            "# Secrets\napi_key: fixture-secret\npassword = fixture-password\n",
            encoding="utf-8",
        )
        (self.root / "Paths.md").write_text(
            f"# Paths\nvault: {self.root}\n",
            encoding="utf-8",
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

    def test_create_note_atomic_readback_and_canonical_links(self):
        result = plugin.obsidian_note_create({
            "path": "Decisions/Deploy.md",
            "title": "Deploy Decision",
            "type": "decision",
            "status": "durable",
            "tags": ["deploy", "mission-control"],
            "keywords": ["roadmap"],
            "related": ["Projects/Roadmap", "Projects/Roadmap.md", "Missing.md"],
            "content": "Use the roadmap before deploying.\n",
        })
        self.assertEqual(status_of(result), 200)
        body = body_of(result)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["note"]["relative_path"], "Decisions/Deploy.md")
        self.assertEqual(body["links"], ["Projects/Roadmap.md"])
        self.assertIn("Missing.md", body["unresolved_candidates"])
        target = self.root / "Decisions" / "Deploy.md"
        self.assertTrue(target.is_file())
        text = target.read_text(encoding="utf-8")
        self.assertIn("id: \"Decisions/Deploy.md\"", text)
        self.assertIn("## Related", text)
        self.assertEqual(text.count("[[Projects/Roadmap.md]]"), 1)
        self.assertNotIn("[[Missing.md]]", text)
        readback = plugin.obsidian_note("Decisions/Deploy.md")
        self.assertEqual(readback["status"], "ok")
        self.assertIn("Deploy Decision", readback["content"])
        self.assertTrue(body["readback"]["verified"])

    def test_duplicate_links_and_existing_body_links_are_normalized(self):
        result = plugin.obsidian_note_create({
            "path": "Context.md",
            "title": "Context",
            "related": ["Projects/Roadmap.md", "Projects/Roadmap.md"],
            "content": "Existing relation [[Projects/Roadmap]] and duplicate [[Projects/Roadmap.md]].\n",
        })
        self.assertEqual(status_of(result), 200)
        body = body_of(result)
        self.assertEqual(body["links"], ["Projects/Roadmap.md"])
        text = (self.root / "Context.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("[[Projects/Roadmap.md]]"), 2)
        self.assertEqual(text.count("## Related"), 1)

    def test_write_rejects_traversal_nul_non_markdown_oversized_and_symlink(self):
        cases = [
            {"path": "../escape.md", "content": "x"},
            {"path": "bad\x00.md", "content": "x"},
            {"path": "bad.txt", "content": "x"},
            {"path": "escape.md", "content": "x"},
            {"path": "MEMORY.md", "content": "x"},
            {"path": "large.md", "content": "x" * (plugin.OBSIDIAN_WRITE_MAX_BYTES + 1)},
        ]
        for payload in cases:
            response = plugin.obsidian_note_create(payload)
            self.assertIn(status_of(response), (400, 413), payload["path"])
            self.assertEqual(body_of(response).get("status"), "error")
        self.assertFalse((self.root / "large.md").exists())

    def test_secret_rejection_and_read_redaction(self):
        response = plugin.obsidian_note_create({
            "path": "Unsafe.md",
            "content": "api_key: should-not-be-written\n",
        })
        self.assertEqual(status_of(response), 400)
        self.assertFalse((self.root / "Unsafe.md").exists())
        readback = plugin.obsidian_note("Secrets.md")
        self.assertEqual(readback["status"], "ok")
        self.assertTrue(readback["redacted"])
        self.assertNotIn("fixture-secret", readback["content"])
        self.assertNotIn("fixture-password", readback["content"])
        path_readback = plugin.obsidian_note("Paths.md")
        self.assertEqual(path_readback["status"], "ok")
        self.assertNotIn(str(self.root), path_readback["content"])
        self.assertIn("[vault]", path_readback["content"])
        bearer = plugin.obsidian_note_create({
            "path": "Bearer.md",
            "content": "Authorization: Bearer abcdefghijklmnop\n",
        })
        self.assertEqual(status_of(bearer), 400)

    def test_graph_exposes_unresolved_links_and_bounded_depth_and_budget(self):
        result = plugin.obsidian_graph(path="Seed.md", depth=2, max_notes=10, max_bytes=90)
        self.assertEqual(status_of(result), 200)
        body = body_of(result)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["seed"]["relative_path"], "Seed.md")
        self.assertIn("Missing.md", [row["target"] for row in body["unresolved_links"]])
        paths = [row["relative_path"] for row in body["notes"]]
        self.assertEqual(paths[0], "Seed.md")
        self.assertIn("Projects/Roadmap.md", paths)
        self.assertLessEqual(len(paths), 10)
        self.assertLessEqual(body["context"]["content_bytes"], 90)
        self.assertTrue(body["context"]["truncated"])
        chain = body["context"]["chain"]
        self.assertEqual(chain[0]["depth"], 0)
        self.assertTrue(any(row["depth"] == 2 for row in chain))

    def test_graph_query_selects_seed_and_invalid_bounds_are_rejected(self):
        result = plugin.obsidian_graph(query="Roadmap")
        self.assertEqual(status_of(result), 200)
        self.assertEqual(body_of(result)["seed"]["relative_path"], "Projects/Roadmap.md")
        for kwargs in (
            {"path": "../escape.md"},
            {"path": "Seed.md", "depth": 3},
            {"path": "Seed.md", "max_notes": 0},
            {"path": "Seed.md", "max_bytes": 0},
        ):
            response = plugin.obsidian_graph(**kwargs)
            self.assertEqual(status_of(response), 400)
            self.assertEqual(body_of(response).get("status"), "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
