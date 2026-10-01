#!/usr/bin/env python3
"""Focused contract tests for the DEMA Phase 1 readiness proposal."""

import ast
import json
import re
import unittest
from pathlib import Path


BASE = Path("/opt/data/mission-control")
MANIFEST = BASE / "catalog" / "dema-phase1-runtime-readiness-v1.json"
ROSTER = BASE / "agents.json"
PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")

CANDIDATE_IDS = {
    "dema-assistant",
    "dema-lead",
    "dema-support",
    "dema-sales",
    "dema-crm",
    "dema-commerce",
    "dema-order",
    "dema-booking",
}
REQUIRED_TOP_LEVEL = {
    "schema_id",
    "version",
    "documented_on",
    "scope",
    "candidate_entries",
    "dependencies",
    "acceptance_gates",
    "workflow_mapping",
    "non_goals",
    "proposed_runtime_roster",
    "frozen_existing_roster_guard",
}
REQUIRED_CANDIDATE_KEYS = {
    "id",
    "display_name",
    "kind",
    "domain",
    "parent",
    "purpose",
    "source_catalog_ids",
    "proposed_runtime_owner",
    "proposed_provider_model_policy",
    "tools",
    "skills",
    "knowledge_scope",
    "permission_boundary",
    "approval_required",
    "autonomous_allowed",
    "lifecycle",
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
SECRET_FIELD = re.compile(
    r"(?:secret|token|password|api[_-]?key|client[_-]?secret|credential|private[_-]?key|access[_-]?token)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|(?:ghp|github_pat|sk|xox[baprs])-[_A-Za-z0-9-]{12,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
    re.IGNORECASE,
)
ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/])")


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


class TestDemaPhase1RuntimeReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest() if MANIFEST.exists() else None

    def require_manifest(self):
        self.assertIsNotNone(self.manifest, f"missing artifact: {MANIFEST}")
        return self.manifest

    def test_schema_and_required_metadata(self):
        manifest = self.require_manifest()
        self.assertEqual(set(REQUIRED_TOP_LEVEL), REQUIRED_TOP_LEVEL & set(manifest))
        self.assertEqual(manifest["schema_id"], "dema-phase1-runtime-readiness/v1")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertRegex(manifest["documented_on"], r"^2026-10-01$")
        self.assertTrue(manifest["scope"].strip())
        self.assertIsInstance(manifest["candidate_entries"], list)
        self.assertIsInstance(manifest["dependencies"], list)
        self.assertIsInstance(manifest["acceptance_gates"], list)

    def test_exactly_eight_candidate_entries_and_unique_ids(self):
        manifest = self.require_manifest()
        entries = manifest["candidate_entries"]
        self.assertEqual(len(entries), 8)
        ids = [entry["id"] for entry in entries]
        self.assertEqual(set(ids), CANDIDATE_IDS)
        self.assertEqual(len(ids), len(set(ids)))
        for entry in entries:
            self.assertEqual(set(REQUIRED_CANDIDATE_KEYS), REQUIRED_CANDIDATE_KEYS & set(entry))
            self.assertRegex(entry["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            self.assertTrue(entry["display_name"].strip())
            self.assertTrue(entry["domain"].strip())
            self.assertTrue(entry["purpose"].strip())
            self.assertIsInstance(entry["source_catalog_ids"], list)
            self.assertTrue(entry["source_catalog_ids"])
            self.assertTrue(entry["proposed_runtime_owner"].strip())
            self.assertIsInstance(entry["proposed_provider_model_policy"], dict)
            self.assertIsInstance(entry["tools"], list)
            self.assertIsInstance(entry["skills"], list)
            self.assertIsInstance(entry["knowledge_scope"], list)
            self.assertTrue(entry["permission_boundary"].strip())
            self.assertTrue(entry["approval_required"])
            self.assertIs(entry["autonomous_allowed"], False)

    def test_lifecycle_is_explicit_and_not_ready(self):
        manifest = self.require_manifest()
        lifecycle_keys = {
            "design_candidate",
            "configured",
            "tested",
            "on_demand_ready",
            "approved_for_users",
            "active",
        }
        for entry in manifest["candidate_entries"]:
            lifecycle = entry["lifecycle"]
            self.assertEqual(lifecycle["state"], "design_candidate", entry["id"])
            self.assertEqual(set(lifecycle_keys), lifecycle_keys & set(lifecycle))
            self.assertTrue(lifecycle["design_candidate"], entry["id"])
            for key in lifecycle_keys - {"design_candidate"}:
                self.assertIs(lifecycle[key], False, f"{entry['id']}:{key}")

    def test_order_and_booking_are_workflows_under_commerce(self):
        manifest = self.require_manifest()
        entries = {entry["id"]: entry for entry in manifest["candidate_entries"]}
        self.assertEqual(entries["dema-commerce"]["kind"], "domain_agent")
        for workflow_id in ("dema-order", "dema-booking"):
            self.assertEqual(entries[workflow_id]["kind"], "workflow")
            self.assertEqual(entries[workflow_id]["parent"], "dema-commerce")
            self.assertFalse(entries[workflow_id]["lifecycle"]["active"])
            mapping = manifest["workflow_mapping"][workflow_id]
            self.assertEqual(mapping["parent"], "dema-commerce")
            self.assertFalse(mapping["top_level_runtime_agent"])
            self.assertEqual(mapping["mapping_type"], "workflow_under_commerce")

    def test_no_candidate_allows_autonomy(self):
        manifest = self.require_manifest()
        self.assertTrue(manifest["non_goals"])
        for entry in manifest["candidate_entries"]:
            self.assertIs(entry["autonomous_allowed"], False)

    def test_no_secret_fields_values_or_absolute_paths(self):
        manifest = self.require_manifest()
        for path, value in walk_json(manifest):
            if path:
                self.assertIsNone(SECRET_FIELD.search(path[-1]), "/".join(path))
            if isinstance(value, str):
                self.assertIsNone(SECRET_VALUE.search(value), "/".join(path))
                self.assertFalse(ABSOLUTE_PATH.match(value), "/".join(path))
                self.assertNotIn("/opt/data/", value)
                self.assertNotIn("/home/", value)
        for entry in manifest["candidate_entries"]:
            for scope in entry["knowledge_scope"]:
                self.assertFalse(scope.startswith("/"), entry["id"])
                self.assertNotIn("..", Path(scope).parts, entry["id"])

    def test_non_goals_and_recommendation_only_boundary_are_explicit(self):
        manifest = self.require_manifest()
        non_goals = " ".join(manifest["non_goals"]).lower()
        for phrase in (
            "roster mutation",
            "autonomous runtime",
            "public release",
            "personal-agent provisioning",
        ):
            self.assertIn(phrase, non_goals)
        roster = manifest["proposed_runtime_roster"]
        self.assertEqual(roster["provisioning"], "recommendation_only_not_provisioned")
        self.assertTrue(roster["recommendation_only_not_provisioned"])
        self.assertTrue(roster["rows"])
        for row in roster["rows"]:
            self.assertEqual(row["provisioning"], "recommendation_only_not_provisioned")
            self.assertNotIn("active", row)
        self.assertNotIn("dema-order", {row["candidate_id"] for row in roster["rows"]})
        self.assertNotIn("dema-booking", {row["candidate_id"] for row in roster["rows"]})

    def test_dependencies_and_acceptance_gates_cover_required_decisions(self):
        manifest = self.require_manifest()
        expected = {
            "provider_model_selection",
            "persona_contract",
            "tool_contract",
            "knowledge_boundary",
            "tenant_isolation",
            "bounded_smoke",
            "cost_quota",
            "audit",
            "human_approval",
        }
        for key in ("dependencies", "acceptance_gates"):
            actual = {row["id"] for row in manifest[key]}
            self.assertTrue(expected <= actual, key)
            for row in manifest[key]:
                self.assertTrue(row["description"].strip(), key)

    def test_frozen_existing_roster_guard_and_namespace_count(self):
        manifest = self.require_manifest()
        current = json.loads(ROSTER.read_text(encoding="utf-8"))
        actual = {row["id"]: (row.get("model"), row.get("active")) for row in current}
        self.assertEqual(set(actual), set(FROZEN_ROSTER) | {"dema-assistant", "dema-lead"})
        for agent_id, expected in FROZEN_ROSTER.items():
            self.assertEqual(actual[agent_id], expected)
        self.assertEqual(actual["dema-assistant"], ("openai-codex/gpt-5.6-luna", False))
        self.assertEqual(actual["dema-lead"], ("openai-codex/gpt-5.6-luna", False))
        guard = manifest["frozen_existing_roster_guard"]
        self.assertEqual(guard["count"], 9)
        self.assertEqual(guard["ids"], list(FROZEN_ROSTER))
        self.assertEqual(guard["model_assignments"], {agent_id: model for agent_id, (model, _active) in FROZEN_ROSTER.items()})
        self.assertEqual(guard["active_flags"], {agent_id: False for agent_id in FROZEN_ROSTER})
        self.assertEqual(guard["namespace_count"], 8)
        self.assertEqual(len(plugin_namespace_ids()), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
