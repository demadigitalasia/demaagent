#!/usr/bin/env python3
"""Focused filesystem CRUD tests for Mission Control memory/skill managers."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_manager_test_plugin", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def status_of(value):
    return getattr(value, "status_code", 200)


class ManagedFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = {
            "MEMORY_DIR": plugin.MEMORY_DIR,
            "SKILLS_DIR": plugin.SKILLS_DIR,
            "AGENTS_STORE": plugin.AGENTS_STORE,
            "MEMORY_AUDIT_PATH": plugin.MEMORY_AUDIT_PATH,
        }
        plugin.MEMORY_DIR = root / "memories"
        plugin.SKILLS_DIR = root / "skills"
        plugin.AGENTS_STORE = root / "agents.json"
        plugin.MEMORY_AUDIT_PATH = root / "audit.jsonl"
        plugin.MEMORY_DIR.mkdir(parents=True)
        plugin.SKILLS_DIR.mkdir(parents=True)
        plugin.AGENTS_STORE.write_text(json.dumps([
            {"id": "a1", "name": "Agent Satu", "skills": ["assigned-skill"]},
            {"id": "a2", "name": "Agent Dua", "skills": []},
        ]), encoding="utf-8")
        plugin._cache.clear()

    def tearDown(self):
        plugin.MEMORY_DIR = self.old["MEMORY_DIR"]
        plugin.SKILLS_DIR = self.old["SKILLS_DIR"]
        plugin.AGENTS_STORE = self.old["AGENTS_STORE"]
        plugin.MEMORY_AUDIT_PATH = self.old["MEMORY_AUDIT_PATH"]
        plugin._cache.clear()
        self.tmp.cleanup()

    def test_memory_update_is_atomic_and_response_redacts_secret(self):
        plugin.MEMORY_DIR.joinpath("MEMORY.md").write_text("before", encoding="utf-8")
        result = plugin.memory_file_update("MEMORY.md", {
            "content": "api_key: before-secret\nnormal note",
        })
        self.assertEqual(status_of(result), 200)
        self.assertEqual(plugin.MEMORY_DIR.joinpath("MEMORY.md").read_text(encoding="utf-8"), "api_key: before-secret\nnormal note")
        shown = plugin.memory_file("MEMORY.md")
        self.assertEqual(shown["status"], "ok")
        self.assertNotIn("before-secret", shown["content"])
        self.assertIn("[redacted]", shown["content"])
        self.assertTrue(plugin.MEMORY_DIR.joinpath("MEMORY.md.bak").is_file())

    def test_memory_path_traversal_and_type_validation_rejected(self):
        self.assertEqual(status_of(plugin.memory_file("../USER.md")), 400)
        self.assertEqual(status_of(plugin.memory_file_update("USER.md", {"content": 42})), 400)
        self.assertEqual(status_of(plugin.memory_file_append("USER.md", {"title": "x", "content": ""})), 400)

    def test_managed_text_rejects_actual_nul_character(self):
        result = plugin.memory_file_update("MEMORY.md", {"content": "safe\x00value"})
        self.assertEqual(status_of(result), 400)
        self.assertFalse((plugin.MEMORY_DIR / "MEMORY.md").exists())

    def test_memory_append_section_writes_real_newlines(self):
        target = plugin.MEMORY_DIR / "MEMORY.md"
        target.write_text("before", encoding="utf-8")

        result = plugin.memory_file_append("MEMORY.md", {"title": "Title", "content": "Body"})

        self.assertEqual(status_of(result), 200)
        written = target.read_text(encoding="utf-8")
        self.assertEqual(written, "before\n\n## Title\n\nBody\n")
        self.assertNotIn("\\\\n", written)
        self.assertIn("## Title", written)

    def test_manager_audit_uses_real_newline_delimiters(self):
        result = plugin.memory_file_update("MEMORY.md", {"content": "audit note"})

        self.assertEqual(status_of(result), 200)
        audit_text = plugin.MEMORY_AUDIT_PATH.read_text(encoding="utf-8")
        self.assertTrue(audit_text.endswith("\n"))
        self.assertNotIn("\\n", audit_text)
        self.assertEqual(len(audit_text.splitlines()), 1)
        self.assertEqual(json.loads(audit_text.splitlines()[0])["action"], "memory.update")

    def test_redacted_get_marks_response_and_edit_source_remains_secret_free(self):
        target = plugin.MEMORY_DIR / "MEMORY.md"
        target.write_text("api_key: before-secret\nnormal note", encoding="utf-8")

        shown = plugin.memory_file("MEMORY.md")

        self.assertEqual(shown["status"], "ok")
        self.assertTrue(shown["redacted"])
        self.assertNotIn("before-secret", shown["content"])
        self.assertIn("[redacted]", shown["content"])
        self.assertNotIn("before-secret", json.dumps(shown))

    def test_non_redacted_get_marks_response_false(self):
        target = plugin.MEMORY_DIR / "USER.md"
        target.write_text("ordinary note", encoding="utf-8")

        shown = plugin.memory_file("USER.md")

        self.assertEqual(shown["status"], "ok")
        self.assertFalse(shown["redacted"])

    def test_symlink_targets_are_rejected(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("must stay", encoding="utf-8")
        (plugin.MEMORY_DIR / "USER.md").symlink_to(outside)
        self.assertEqual(status_of(plugin.memory_file_update("USER.md", {"content": "nope"})), 400)
        self.assertEqual(outside.read_text(encoding="utf-8"), "must stay")
        (plugin.MEMORY_DIR / "USER.md").unlink()
        skill_target = plugin.SKILLS_DIR / "real-category"
        skill_target.mkdir()
        (plugin.SKILLS_DIR / "linked-category").symlink_to(skill_target, target_is_directory=True)
        self.assertEqual(status_of(plugin.skill_library_detail("linked-category", "x")), 400)

    def test_memory_delete_requires_explicit_confirmation(self):
        target = plugin.MEMORY_DIR / "USER.md"
        target.write_text("keep", encoding="utf-8")
        denied = plugin.memory_file_delete("USER.md", {"confirm": False})
        self.assertEqual(status_of(denied), 400)
        self.assertTrue(target.exists())
        deleted = plugin.memory_file_delete("USER.md", {"confirm": True})
        self.assertEqual(status_of(deleted), 200)
        self.assertFalse(target.exists())
        self.assertTrue((plugin.MEMORY_DIR / "USER.md.bak").exists())

    def test_atomic_write_error_keeps_original_and_returns_safe_error(self):
        target = plugin.MEMORY_DIR / "MEMORY.md"
        target.write_text("original", encoding="utf-8")
        with patch.object(plugin, "_atomic_managed_write", side_effect=OSError("simulated")):
            result = plugin.memory_file_update("MEMORY.md", {"content": "replacement"})
        self.assertEqual(status_of(result), 500)
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        self.assertNotIn("simulated", getattr(result, "body", b"").decode("utf-8", "replace"))

    def test_skill_create_requires_safe_name_and_frontmatter(self):
        bad_path = plugin.skill_library_create({
            "category": "../escape", "name": "x", "content": "---\nname: x\n---\nbody",
        })
        self.assertEqual(status_of(bad_path), 400)
        missing_frontmatter = plugin.skill_library_create({
            "category": "test", "name": "new-skill", "content": "body only",
        })
        self.assertEqual(status_of(missing_frontmatter), 400)
        created = plugin.skill_library_create({
            "category": "test", "name": "new-skill",
            "content": "---\nname: new-skill\ndescription: Test skill\n---\n# Body",
        })
        self.assertEqual(status_of(created), 200)
        self.assertTrue((plugin.SKILLS_DIR / "test" / "new-skill" / "SKILL.md").exists())

    def test_skill_detail_lists_assigned_agents_and_delete_guard(self):
        skill_dir = plugin.SKILLS_DIR / "test" / "assigned-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: assigned-skill\ndescription: Assigned\n---\n# Body", encoding="utf-8"
        )
        detail = plugin.skill_library_detail("test", "assigned-skill")
        self.assertEqual(detail["status"], "ok")
        self.assertFalse(detail["redacted"])
        self.assertEqual([a["name"] for a in detail["assigned_agents"]], ["Agent Satu"])
        denied = plugin.skill_library_delete("test", "assigned-skill", {"confirm": False})
        self.assertEqual(status_of(denied), 409)
        self.assertTrue((skill_dir / "SKILL.md").exists())
        removed = plugin.skill_library_delete("test", "assigned-skill", {"confirm": True})
        self.assertEqual(status_of(removed), 200)
        self.assertFalse((skill_dir / "SKILL.md").exists())
        self.assertEqual(removed["assigned_agents"][0]["name"], "Agent Satu")

    def test_skill_delete_path_traversal_rejected_and_no_secret_response(self):
        result = plugin.skill_library_detail("test", "../agents.json")
        self.assertEqual(status_of(result), 400)
        created = plugin.skill_library_create({
            "category": "test", "name": "secret-skill",
            "content": "---\nname: secret-skill\ndescription: safe\n---\npassword: super-secret",
        })
        self.assertEqual(status_of(created), 200)
        detail = plugin.skill_library_detail("test", "secret-skill")
        self.assertTrue(detail["redacted"])
        self.assertNotIn("super-secret", detail["content"])
        self.assertIn("[redacted]", detail["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
