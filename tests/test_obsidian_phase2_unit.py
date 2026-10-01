#!/usr/bin/env python3
"""Phase 2 reviewed-ingestion and Wiki-lint tests on a temporary vault."""
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_obsidian_phase2_test_plugin", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def status_of(value):
    return getattr(value, "status_code", 200)


def body_of(value):
    body = getattr(value, "body", None)
    if body is None:
        return value
    return json.loads(body.decode("utf-8"))


class Phase2VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        (self.root / "10-Wiki" / "entities").mkdir(parents=True)
        (self.root / "10-Wiki" / "concepts").mkdir(parents=True)
        (self.root / "10-Wiki" / "raw" / "articles").mkdir(parents=True)
        (self.root / "40-Inbox").mkdir()
        (self.root / "10-Wiki" / "index.md").write_text(
            "---\n"
            "id: index-10-wiki\n"
            "title: Catalog\n"
            "type: index\n"
            "status: active\n"
            "created: 2026-09-30\n"
            "updated: 2026-09-30\n"
            "tags:\n  - llm-wiki\n"
            "source_refs:\n  - [[10-Wiki/SCHEMA]]\n"
            "---\n\n"
            "# Catalog\n\n## Entities\n\n"
            "## Concepts\n\n## Comparisons\n\n## Queries\n\n"
            "## Sources\n\n## Maintenance\n\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki" / "log.md").write_text(
            "---\nid: log-10-wiki\ntype: log\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - log\n"
            "source_refs:\n  - [[10-Wiki/SCHEMA]]\n---\n\n# Log\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki" / "SCHEMA.md").write_text(
            "---\nid: schema-10-wiki\ntitle: Schema\ntype: procedure\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - schema\n"
            "source_refs:\n  - [[10-Wiki/index]]\n---\n\n# Schema\n",
            encoding="utf-8",
        )
        (self.root / "10-Wiki" / "entities" / "Existing.md").write_text(
            "---\n"
            "id: existing\n"
            "title: Existing\n"
            "type: entity\n"
            "status: active\n"
            "created: 2026-09-30\n"
            "updated: 2026-09-30\n"
            "tags:\n  - fixture\n"
            "source_refs:\n  - [[10-Wiki/raw/articles/fixture]]\n"
            "---\n\n# Existing\n\nA fixture page.\n",
            encoding="utf-8",
        )
        old_env = os.environ.get("OBSIDIAN_VAULT_PATH")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore_env, old_env)
        os.environ["OBSIDIAN_VAULT_PATH"] = str(self.root)
        plugin._cache.clear()

    def _restore_env(self, old_env):
        plugin._cache.clear()
        if old_env is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = old_env

    def _payload(self, **overrides):
        payload = {
            "title": "Reviewed source",
            "source_url": "https://example.com/articles/reviewed-source#section",
            "source_type": "article",
            "content": "A bounded captured source with durable claims.",
            "tags": ["llm", "reviewed"],
            "summary": "A concise source summary.",
        }
        payload.update(overrides)
        return payload

    def test_ingest_writes_immutable_raw_and_pending_proposal(self):
        result = plugin.obsidian_ingest(self._payload())
        self.assertEqual(status_of(result), 200)
        body = body_of(result)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["proposal"]["status"], "pending")
        raw_path = self.root / body["raw_capture"]["relative_path"]
        proposal_path = self.root / body["proposal"]["relative_path"]
        self.assertTrue(raw_path.is_file())
        self.assertTrue(proposal_path.is_file())
        self.assertTrue(str(raw_path.relative_to(self.root)).startswith("10-Wiki/raw/"))
        self.assertTrue(str(proposal_path.relative_to(self.root)).startswith("40-Inbox/"))
        self.assertFalse((self.root / "10-Wiki" / "concepts" / "Reviewed source.md").exists())
        raw_before = raw_path.read_bytes()
        self.assertNotIn("[vault]", raw_before.decode("utf-8"))
        self.assertNotIn(str(self.root), proposal_path.read_text(encoding="utf-8"))
        self.assertEqual(body["deduplicated"], False)
        self.ingested = body
        self.assertEqual(raw_before, raw_path.read_bytes())

    def test_ingest_is_idempotent_by_source_identity_and_content_hash(self):
        first = body_of(plugin.obsidian_ingest(self._payload()))
        raw_path = self.root / first["raw_capture"]["relative_path"]
        raw_before = raw_path.read_bytes()
        second = body_of(plugin.obsidian_ingest(self._payload(content="changed but same source")))
        self.assertEqual(second["status"], "ok")
        self.assertTrue(second["deduplicated"])
        self.assertEqual(second["proposal"]["relative_path"], first["proposal"]["relative_path"])
        self.assertEqual(second["raw_capture"]["relative_path"], first["raw_capture"]["relative_path"])
        self.assertEqual(raw_before, raw_path.read_bytes(), "raw capture must remain immutable")

        by_hash = body_of(plugin.obsidian_ingest(self._payload(source_url="https://other.example/source")))
        self.assertTrue(by_hash["deduplicated"])
        self.assertEqual(by_hash["proposal"]["relative_path"], first["proposal"]["relative_path"])

    def test_ingest_rejects_url_nul_utf8_size_and_secrets(self):
        cases = [
            {"source_url": "file:///etc/passwd"},
            {"source_url": "https://user:password@example.com/a"},
            {"source_url": "https://example.com/a?api_key=secret-value"},
            {"content": "bad\x00content"},
            {"content": "\ud800"},
            {"content": "x" * (plugin.OBSIDIAN_INGEST_MAX_BYTES + 1)},
            {"content": "Authorization: Bearer abcdefghijklmnop"},
            {"content": "password = secret-value"},
        ]
        for change in cases:
            response = plugin.obsidian_ingest(self._payload(**change))
            self.assertIn(status_of(response), (400, 413), change)
            self.assertEqual(body_of(response).get("status"), "error")
        self.assertFalse(list((self.root / "10-Wiki" / "raw").rglob("*.md")))
        self.assertFalse(list((self.root / "40-Inbox").rglob("*.md")))

    def test_proposal_list_read_and_approval_guards_and_controlled_updates(self):
        ingested = body_of(plugin.obsidian_ingest(self._payload()))
        proposal_path = ingested["proposal"]["relative_path"]
        listed = body_of(plugin.obsidian_inbox(limit=20))
        self.assertEqual(listed["status"], "ok")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["proposals"][0]["relative_path"], proposal_path)
        read = body_of(plugin.obsidian_inbox_proposal(proposal_path))
        self.assertEqual(read["status"], "ok")
        self.assertEqual(read["proposal"]["status"], "pending")
        self.assertNotIn(str(self.root), json.dumps(read))

        no_confirm = plugin.obsidian_inbox_approve({"proposal_path": proposal_path, "target_path": "10-Wiki/concepts/Approved.md"})
        self.assertEqual(status_of(no_confirm), 400)
        traversal = plugin.obsidian_inbox_approve({"proposal_path": proposal_path, "confirm": True, "target_path": "10-Wiki/concepts/../entities/Bad.md"})
        self.assertEqual(status_of(traversal), 400)
        core = plugin.obsidian_inbox_approve({"proposal_path": proposal_path, "confirm": True, "target_path": "MEMORY.md"})
        self.assertEqual(status_of(core), 400)

        approved = body_of(plugin.obsidian_inbox_approve({
            "proposal_path": proposal_path,
            "confirm": True,
            "target_path": "10-Wiki/concepts/Approved.md",
            "type": "concept",
        }))
        self.assertEqual(approved["status"], "ok")
        accepted = self.root / "10-Wiki" / "concepts" / "Approved.md"
        self.assertTrue(accepted.is_file())
        accepted_text = accepted.read_text(encoding="utf-8")
        self.assertIn("source_refs:", accepted_text)
        self.assertIn("status: \"active\"", accepted_text)
        self.assertIn("[[10-Wiki/raw/", accepted_text)
        index = (self.root / "10-Wiki" / "index.md").read_text(encoding="utf-8")
        log = (self.root / "10-Wiki" / "log.md").read_text(encoding="utf-8")
        self.assertEqual(index.count("[[10-Wiki/concepts/Approved]]"), 1)
        self.assertIn("approve", log)
        reread = body_of(plugin.obsidian_inbox_proposal(proposal_path))
        self.assertEqual(reread["proposal"]["status"], "approved")
        self.assertEqual(reread["proposal"]["approved_target"], "10-Wiki/concepts/Approved.md")
        conflict = plugin.obsidian_inbox_approve({
            "proposal_path": proposal_path,
            "confirm": True,
            "target_path": "10-Wiki/concepts/Approved.md",
        })
        self.assertEqual(status_of(conflict), 409)

    def test_approval_rejects_target_symlink_and_keeps_raw_unchanged(self):
        ingested = body_of(plugin.obsidian_ingest(self._payload(title="Symlink target")))
        raw_path = self.root / ingested["raw_capture"]["relative_path"]
        raw_before = raw_path.read_bytes()
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        target = self.root / "10-Wiki" / "entities" / "Escape.md"
        target.symlink_to(outside)
        response = plugin.obsidian_inbox_approve({
            "proposal_path": ingested["proposal"]["relative_path"],
            "confirm": True,
            "target_path": "10-Wiki/entities/Escape.md",
        })
        self.assertEqual(status_of(response), 400)
        self.assertEqual(raw_before, raw_path.read_bytes())
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside")

    def test_lint_reports_required_phase2_rules_with_bounded_safe_issues(self):
        accepted = self.root / "10-Wiki" / "concepts"
        (accepted / "Broken.md").write_text(
            "---\nid: broken\ntitle: Broken\ntype: concept\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - fixture\n"
            "source_refs:\n  - [[missing-source]]\n---\n\n# Broken\n\n[[NoSuchPage]]\n",
            encoding="utf-8",
        )
        (accepted / "NoFrontmatter.md").write_text("# Missing frontmatter\n", encoding="utf-8")
        (accepted / "NoProvenance.md").write_text(
            "---\nid: no-provenance\ntitle: No provenance\ntype: concept\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - fixture\n---\n\n# No provenance\n",
            encoding="utf-8",
        )
        (accepted / "Malformed.md").write_text(
            "---\nid: malformed\ntitle: Malformed\ntype: mystery\nstatus: ???\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - fixture\n"
            "source_refs:\n  - [[10-Wiki/index]]\n---\n\n# Malformed\n",
            encoding="utf-8",
        )
        (accepted / "Secret.md").write_text(
            "---\nid: secret\ntitle: Secret\ntype: concept\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - fixture\n"
            "source_refs:\n  - [[10-Wiki/index]]\n---\n\napi_key: leaked-value\n",
            encoding="utf-8",
        )
        (accepted / "Oversize.md").write_text(
            "---\nid: oversize\ntitle: Oversize\ntype: concept\nstatus: active\n"
            "created: 2026-09-30\nupdated: 2026-09-30\ntags:\n  - fixture\n"
            "source_refs:\n  - [[10-Wiki/index]]\n---\n\n" + "x" * (plugin.OBSIDIAN_WIKI_PAGE_MAX_BYTES + 1),
            encoding="utf-8",
        )
        result = body_of(plugin.obsidian_lint(limit=200))
        self.assertEqual(result["status"], "ok")
        rules = {issue["rule"] for issue in result["issues"]}
        for rule in (
            "broken_wikilink", "missing_frontmatter", "missing_provenance",
            "malformed_type", "malformed_status", "oversized_page", "suspicious_credential",
            "missing_index", "orphan_page",
        ):
            self.assertIn(rule, rules, rule)
        self.assertLessEqual(len(result["issues"]), 200)
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(self.root), encoded)
        for issue in result["issues"]:
            self.assertIn(issue["severity"], {"error", "warning", "info"})
            self.assertTrue(issue["path"])
            self.assertTrue(issue["message"])
        self.assertEqual(result["counts"]["total"], len(result["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
