#!/usr/bin/env python3
"""Focused contract tests for DEMA Global Agent Catalog v1."""

import ast
import json
import re
import unittest
from pathlib import Path


BASE = Path("/opt/data/mission-control")
MANIFEST = BASE / "catalog" / "dema-global-agent-catalog-v1.json"
ROSTER = BASE / "agents.json"
PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")

BUSINESS_SOURCE = [
    "DEMA Lead", "Support", "Sales", "Order", "CRM", "Marketing", "Social",
    "Content", "Analyst", "Finance", "Booking", "Document", "Operations",
    "Inventory", "Procurement", "HR", "Recruiter", "Project", "Meeting",
]
PRODUCT_SOURCE = [
    "DEMA Social", "Content", "Analyst", "Finance", "Booking", "Document",
    "Operations", "Inventory", "Procurement", "HR", "Recruiter", "Project",
    "Meeting", "Email", "Assistant", "Research", "Commerce", "Retention",
    "Review", "Report",
]
PLATFORM_IDS = {
    "hermes-lead",
    "agent-engineer",
    "opencode",
    "sub-agent-back-end",
    "sub-agent-devops",
    "sub-agent-front-end",
    "sub-agent-ui-ux",
}
FROZEN_ROSTER = {
    "hermes-lead": ("openai-codex/gpt-5.6-luna", False),
    "agent-engineer": ("openai-codex/gpt-5.6-luna", False),
    "opencode": ("opencode-go/deepseek-v4-flash", False),
    "agent-socmed": ("opencode-go/deepseek-v4-flash", False),
    "news-agent": ("openrouter/nvidia/nemotron-3-super-120b-a12b:free", False),
    "sub-agent-back-end": ("opencode-go/deepseek-v4-flash", False),
    "sub-agent-devops": ("opencode-go/deepseek-v4-flash", False),
    "sub-agent-front-end": ("opencode-go/deepseek-v4-flash", False),
    "sub-agent-ui-ux": ("opencode-go/deepseek-v4-flash-vision-exp", False),
}
REQUIRED_ENTRY_KEYS = {
    "id", "display_name", "kind", "domain", "purpose", "primary_inputs",
    "primary_outputs", "runtime_owner", "parent", "visibility", "default_mode",
    "provider_model_policy", "skills", "tools", "knowledge_scope",
    "approval_required", "autonomous_allowed", "status", "notes",
}
ALLOWED_KINDS = {"orchestrator", "domain_agent", "workflow", "sub_agent", "platform_internal"}
SECRET_FIELD = re.compile(
    r"(?:secret|token|password|api[_-]?key|client[_-]?secret|credential|private[_-]?key|access[_-]?token)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|(?:ghp|github_pat|sk|xox[baprs])-[_A-Za-z0-9-]{12,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
    re.IGNORECASE,
)


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def walk_json(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(child, path + (str(index),))


def plugin_namespace_ids():
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "OBSIDIAN_AGENT_IDS":
                return tuple(ast.literal_eval(node.value))
    raise AssertionError("OBSIDIAN_AGENT_IDS assignment not found")


class TestDemaGlobalAgentCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest()
        cls.entries = cls.manifest["catalog_entries"]
        cls.by_id = {entry["id"]: entry for entry in cls.entries}

    def test_manifest_is_v1_and_has_required_top_level_sections(self):
        self.assertEqual(self.manifest["schema_id"], "dema-global-agent-catalog/v1")
        self.assertEqual(self.manifest["documented_on"], "2026-10-01")
        for key in (
            "design_sources", "catalog_entries", "source_mappings",
            "recommended_runtime_roster", "boundary", "frozen_runtime_guard",
        ):
            self.assertIn(key, self.manifest)
        self.assertIsInstance(self.entries, list)
        self.assertGreater(len(self.entries), 0)

    def test_every_entry_has_safe_explicit_metadata_and_unique_id(self):
        ids = [entry.get("id") for entry in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in self.entries:
            self.assertEqual(set(REQUIRED_ENTRY_KEYS), REQUIRED_ENTRY_KEYS & set(entry))
            self.assertRegex(entry["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            self.assertTrue(entry["display_name"].strip())
            self.assertIn(entry["kind"], ALLOWED_KINDS)
            self.assertTrue(entry["domain"].strip())
            self.assertTrue(entry["purpose"].strip())
            self.assertIsInstance(entry["primary_inputs"], list)
            self.assertIsInstance(entry["primary_outputs"], list)
            self.assertIsInstance(entry["runtime_owner"], str)
            self.assertTrue(entry["runtime_owner"].strip())
            self.assertTrue(entry["parent"] is None or entry["parent"] in self.by_id)
            self.assertIn(entry["visibility"], {"platform_internal", "public_catalog", "public_workflow"})
            self.assertTrue(entry["default_mode"].strip())
            self.assertIsInstance(entry["provider_model_policy"], dict)
            self.assertIsInstance(entry["skills"], list)
            self.assertIsInstance(entry["tools"], list)
            self.assertIsInstance(entry["knowledge_scope"], list)
            self.assertIsInstance(entry["approval_required"], bool)
            self.assertIs(entry["autonomous_allowed"], False)
            self.assertTrue(entry["status"].strip())
            self.assertTrue(entry["notes"].strip())
            self.assertTrue(entry.get("runtime_owner_reason", "").strip())

    def test_union_of_both_design_sources_is_explicitly_mapped(self):
        expected = {
            ("business_roster", name) for name in BUSINESS_SOURCE
        } | {
            ("product_catalog", name) for name in PRODUCT_SOURCE
        }
        mappings = self.manifest["source_mappings"]
        actual = {(row["source_set"], row["source_name"]) for row in mappings}
        self.assertEqual(actual, expected)
        self.assertEqual(len(mappings), len(expected))
        for row in mappings:
            self.assertIn(row["mapping_type"], {"canonical", "alias", "workflow_mapping"})
            self.assertIn(row["catalog_id"], self.by_id)
            self.assertTrue(row["reason"].strip())

    def test_platform_internal_and_public_business_catalog_are_separate(self):
        platform = {entry["id"] for entry in self.entries if entry["visibility"] == "platform_internal"}
        public = {entry["id"] for entry in self.entries if entry["visibility"] != "platform_internal"}
        self.assertEqual(platform, PLATFORM_IDS)
        self.assertTrue(public)
        self.assertTrue(platform.isdisjoint(public))
        self.assertTrue(all(self.by_id[item]["kind"] == "platform_internal" for item in platform))
        self.assertTrue(all(self.by_id[item]["status"] == "existing_runtime_frozen" for item in platform))
        self.assertTrue(all(self.by_id[item]["status"] == "catalog_only_recommended" for item in public))
        self.assertIn("dema-assistant", public)
        self.assertIn("dema-lead", public)
        self.assertTrue(any(self.by_id[item]["kind"] == "workflow" for item in public))

    def test_runtime_owner_is_one_explicit_owner_with_reason(self):
        roster_ids = set(FROZEN_ROSTER)
        recommended_ids = {row["id"] for row in self.manifest["recommended_runtime_roster"]}
        for entry in self.entries:
            owner = entry["runtime_owner"]
            self.assertIn(owner, roster_ids | recommended_ids, entry["id"])
            self.assertNotIn("runtime_owners", entry)
            self.assertNotIsInstance(owner, list)
            self.assertTrue(entry["runtime_owner_reason"].strip())
        for row in self.manifest["recommended_runtime_roster"]:
            self.assertEqual(row["provisioning"], "recommendation_only_not_provisioned")
            self.assertNotIn("active", row)

    def test_no_secret_shaped_fields_or_absolute_paths(self):
        for path, value in walk_json(self.manifest):
            if path:
                self.assertIsNone(SECRET_FIELD.search(path[-1]), "/".join(path))
            if isinstance(value, str):
                self.assertNotRegex(value, SECRET_VALUE)
                self.assertNotIn("/opt/data/", value)
                self.assertNotIn("/opt/", value)
                self.assertNotIn("/home/", value)
                self.assertNotIn("MEMORY.md", value if path[:1] != ("boundary",) else "")
        for entry in self.entries:
            for scope in entry["knowledge_scope"]:
                self.assertFalse(scope.startswith("/"), entry["id"])
                self.assertNotIn("..", Path(scope).parts, entry["id"])

    def test_roster_guard_keeps_frozen_nine_and_all_flags_false_with_approved_business_additions(self):
        current = json.loads(ROSTER.read_text(encoding="utf-8"))
        actual = {row["id"]: (row.get("model"), row.get("active")) for row in current}
        self.assertEqual(set(actual), set(FROZEN_ROSTER) | {"dema-assistant", "dema-lead"})
        for agent_id, expected in FROZEN_ROSTER.items():
            self.assertEqual(actual[agent_id], expected)
        self.assertEqual(actual["dema-assistant"], ("openai-codex/gpt-5.6-luna", False))
        self.assertEqual(actual["dema-lead"], ("openai-codex/gpt-5.6-luna", False))
        guard = self.manifest["frozen_runtime_guard"]
        self.assertEqual(guard["count"], 9)
        self.assertEqual(guard["ids"], list(FROZEN_ROSTER))
        self.assertEqual(guard["active_flags"], {agent_id: False for agent_id in FROZEN_ROSTER})
        self.assertEqual(guard["namespace_count"], 8)
        self.assertEqual(len(plugin_namespace_ids()), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
