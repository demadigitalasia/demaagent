#!/usr/bin/env python3
"""TDD contracts for the reviewed content-intake roster migration."""

import json
import sys
import unittest
from pathlib import Path


BASE = Path("/opt/data/mission-control")
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from content_team_catalog import project_content_team_catalog  # noqa: E402
from group_catalog import load_validated_group_catalog  # noqa: E402
from routing import preview_route, validate_config  # noqa: E402
from workflow_group_catalog import load_validated_workflow_group_catalog  # noqa: E402


ROSTER_PATH = BASE / "agents.json"
ROUTING_PATH = BASE / "workflows.json"
GROUP_CATALOG_PATH = BASE / "catalog" / "dema-agent-groups-v1.json"
WORKFLOW_GROUP_CATALOG_PATH = BASE / "catalog" / "dema-workflow-groups-v1.json"


class ContentIntakeProvisioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        cls.routing = json.loads(ROUTING_PATH.read_text(encoding="utf-8"))
        cls.groups = json.loads(GROUP_CATALOG_PATH.read_text(encoding="utf-8"))
        cls.workflow_groups = json.loads(WORKFLOW_GROUP_CATALOG_PATH.read_text(encoding="utf-8"))
        cls.agent = next(
            (row for row in cls.roster if row.get("id") == "content-intake-concierge"),
            None,
        )

    def test_exactly_one_reviewed_agent_is_real_and_governance_gated(self):
        self.assertEqual(len(self.roster), 14)
        self.assertIsNotNone(self.agent)
        self.assertEqual(
            sum(row.get("id") == "content-intake-concierge" for row in self.roster),
            1,
        )
        self.assertEqual(self.agent["model"], "opencode-go/deepseek-v4-flash")
        self.assertIs(self.agent["active"], False)
        self.assertIs(self.agent["system"], False)
        self.assertNotIn("autonomous_allowed", self.agent)
        self.assertEqual(self.agent["created_at"], "2026-10-02")
        self.assertEqual(self.agent["updated_at"], "2026-10-02")
        routing = self.agent["routing"]
        self.assertEqual(routing["runtime_owner"], "hermes-lead")
        self.assertEqual(routing["availability"], "on_demand")
        self.assertEqual(routing["approval_policy"], "approval_required")
        self.assertEqual(set(routing["routing_domains"]), {"content", "public-intake"})
        self.assertEqual(routing["runtime_adapter"], "provider_oneshot")
        self.assertIn("content-intake", routing["capabilities"])
        self.assertTrue(self.agent["persona_profile"]["forbidden_actions"])

    def test_skills_are_installed_and_workspace_is_ready_after_owner_reconciliation(self):
        installed = {
            path.parent.name
            for path in Path("/opt/data/skills").rglob("SKILL.md")
        }
        self.assertTrue(set(self.agent["skills"]).issubset(installed))
        workspace = self.agent["drive_workspace"]
        self.assertEqual(workspace["status"], "ready")
        self.assertTrue(workspace["name"])
        for key in ("folder_id", "root_folder_id"):
            self.assertTrue(workspace.get(key))
        self.assertTrue(workspace.get("webViewLink") or workspace.get("link"))

    def test_group_catalog_has_exactly_one_membership_for_new_agent(self):
        validated = load_validated_group_catalog(self.roster, self.groups)
        memberships = [
            group["id"]
            for group in validated["groups"]
            if "content-intake-concierge" in group["member_agent_ids"]
        ]
        self.assertEqual(memberships, ["social-content-production"])
        all_members = [
            agent_id
            for group in validated["groups"]
            for agent_id in group["member_agent_ids"]
        ]
        self.assertEqual(len(all_members), len(self.roster))
        self.assertEqual(len(all_members), len(set(all_members)))
        self.assertNotIn("content-safety-reviewer", all_members)
        self.assertNotIn("video-production-editor", all_members)

    def test_content_intake_workflow_is_owned_and_configuration_only(self):
        config = validate_config(self.routing, self.roster)
        workflow = next(row for row in config["workflows"] if row["id"] == "content-intake-pipeline")
        self.assertEqual(workflow["approval_gates"], ["lead_review", "approval_required"])
        stage_ids = {stage["id"] for stage in workflow["stages"]}
        self.assertIn("intake", stage_ids)
        self.assertTrue(
            any(
                stage.get("candidate_agent_ids") == ["content-intake-concierge"]
                for stage in workflow["stages"]
            )
        )
        preview = preview_route(
            config,
            self.roster,
            "Submit a public content brief for social media intake and route it",
            ["content-intake"],
        )
        self.assertEqual(preview["workflow"]["id"], "content-intake-pipeline")
        self.assertFalse(preview["execution"]["launched"])
        self.assertFalse(preview["execution"]["external_writes"])
        selected = {stage["id"]: stage["selected_agent_id"] for stage in preview["stages"]}
        self.assertEqual(selected["intake"], "content-intake-concierge")

    def test_workflow_group_contract_and_content_team_separation(self):
        validated = load_validated_workflow_group_catalog(
            self.roster,
            self.routing,
            self.groups,
            self.workflow_groups,
        )
        contract = next(
            row for row in validated["contracts"]
            if row["workflow_id"] == "content-intake-pipeline"
        )
        self.assertEqual(contract["owner_agent_id"], "content-intake-concierge")
        self.assertEqual(
            contract["approval_boundary"],
            ["lead_review", "approval_required"],
        )
        self.assertIn("content-planner-copywriter", contract["supporting_agent_ids"])
        self.assertIn("social-research-trends", contract["supporting_agent_ids"])

        projection = project_content_team_catalog(self.roster)
        current_ids = {row["agent_id"] for row in projection["active_roster_member"]}
        recommendation_ids = {row["agent_id"] for row in projection["recommendation_only"]}
        self.assertIn("content-intake-concierge", current_ids)
        self.assertEqual(
            recommendation_ids,
            {"content-safety-reviewer", "video-production-editor"},
        )
        self.assertTrue(current_ids.isdisjoint(recommendation_ids))
        self.assertTrue(all("model" not in row for row in projection["recommendation_only"]))
        self.assertFalse(projection["external_write_disabled"] is False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
