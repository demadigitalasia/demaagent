#!/usr/bin/env python3
"""Focused backend tests for the read-only content team endpoint."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


BASE = Path("/opt/data/mission-control")
PLUGIN_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
ROSTER_PATH = BASE / "agents.json"


def load_plugin():
    spec = importlib.util.spec_from_file_location("mission_control_content_team_backend_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestContentTeamEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_plugin()
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))

    def test_build_content_team_separates_current_roster_and_recommendations(self):
        original = copy.deepcopy(self.roster)
        with patch.object(self.plugin, "_load_agents", return_value=copy.deepcopy(self.roster)):
            body = self.plugin._build_content_team()

        self.assertEqual(body["status"], "ok")
        self.assertIs(body["external_write_disabled"], True)
        self.assertEqual(body["configured"]["status"], "configured_read_only_catalog")
        self.assertEqual(
            {row["agent_id"] for row in body["active_roster_member"]},
            {"content-intake-concierge", "content-planner-copywriter", "social-research-trends", "visual-ugc-designer"},
        )
        self.assertEqual(
            {row["agent_id"] for row in body["recommendation_only"]},
            {"content-safety-reviewer", "video-production-editor"},
        )
        self.assertTrue(
            {row["agent_id"] for row in body["active_roster_member"]}.isdisjoint(
                {row["agent_id"] for row in body["recommendation_only"]}
            )
        )
        self.assertTrue(all("model" not in row for row in body["recommendation_only"]))
        self.assertEqual(
            [(row["id"], row["catalog_only"], row["external_write_disabled"]) for row in body["workflows"]],
            [
                ("content-intake-pipeline", True, True),
                ("social-post-package", True, True),
                ("short-video-package", True, True),
                ("content-safety-review", True, True),
                ("publication-gate", True, True),
            ],
        )
        self.assertEqual(self.roster, original)
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("authorization", "bearer ", "client_secret", "api_key", "/opt/data/"):
            self.assertNotIn(marker, encoded, marker)

    def test_invalid_catalog_returns_unavailable_without_fabricated_content_team(self):
        with patch.object(self.plugin, "_load_agents", return_value=copy.deepcopy(self.roster)), patch.object(
            self.plugin._content_team_catalog,
            "project_content_team_catalog",
            side_effect=self.plugin._content_team_catalog.ContentTeamCatalogError("invalid"),
        ):
            body = self.plugin._build_content_team()

        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["active_roster_member"], [])
        self.assertEqual(body["recommendation_only"], [])
        self.assertEqual(body["workflows"], [])
        self.assertIs(body["external_write_disabled"], True)

    def test_catalog_route_is_get_only_and_intake_route_is_explicit_post(self):
        catalog_matches = [route for route in self.plugin.router.routes if route.path == "/content-team"]
        self.assertEqual(len(catalog_matches), 1)
        self.assertEqual(set(catalog_matches[0].methods or set()), {"GET"})
        intake_matches = [route for route in self.plugin.router.routes if route.path == "/content-team/intake"]
        self.assertEqual(len(intake_matches), 1)
        self.assertEqual(set(intake_matches[0].methods or set()), {"POST"})

    def test_intake_endpoint_returns_bounded_draft_without_external_write(self):
        expected = {
            "status": "draft_ready",
            "agent_id": "content-intake-concierge",
            "approval_required": True,
            "external_write": False,
            "autonomous": False,
            "draft": {
                "normalized_brief": {"channel": "Instagram"},
                "missing_inputs": ["product link"],
                "routing_recommendation": "lead review",
                "escalation": "rights check",
            },
        }
        with patch.object(self.plugin, "_load_agents", return_value=copy.deepcopy(self.roster)), patch.object(
            self.plugin._content_intake, "run_content_intake", return_value=expected
        ) as run:
            body = self.plugin.content_team_intake({
                "brief": "Launch a blue linen shirt on Instagram.",
                "correlation_id": "intake-test-001",
            })
        self.assertEqual(body, expected)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["brief"], "Launch a blue linen shirt on Instagram.")

    def test_intake_endpoint_does_not_fabricate_when_agent_missing(self):
        with patch.object(self.plugin, "_load_agents", return_value=[]):
            response = self.plugin.content_team_intake({"brief": "A normal public brief"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["status"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
