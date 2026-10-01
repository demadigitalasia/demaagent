import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path("/opt/data/mission-control")
SPEC = importlib.util.spec_from_file_location("mission_control_routing_test", ROOT / "routing.py")
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


LIVE_ROSTER = json.loads((ROOT / "agents.json").read_text(encoding="utf-8"))
LIVE_CONFIG = json.loads((ROOT / "workflows.json").read_text(encoding="utf-8"))


ROSTER = [
    {
        "id": "hermes-lead",
        "name": "Hermes",
        "active": False,
        "routing": {
            "capabilities": ["coordination", "verification"],
            "tags": ["lead"],
            "accepts": ["all"],
            "outputs": ["brief", "decision"],
            "parent_id": None,
            "runtime_owner": "hermes-lead",
            "runtime_mode": "lead",
            "approval_policy": "approval_required",
            "priority": 100,
            "availability": "on_demand",
        },
    },
    {
        "id": "backend-data",
        "name": "Backend",
        "active": False,
        "routing": {
            "capabilities": ["engineering-specialist", "backend", "verification"],
            "tags": ["specialist", "backend"],
            "accepts": ["code", "api"],
            "outputs": ["patch", "tests"],
            "parent_id": "agent-engineer",
            "runtime_owner": "hermes-lead",
            "runtime_mode": "specialist",
            "approval_policy": "approval_required",
            "priority": 80,
            "availability": "on_demand",
        },
    },
]


BASE = {
    "version": 1,
    "default_workflow": "coding",
    "routing_rules": [
        {"id": "code", "capability": "engineering-specialist", "keywords": ["api", "backend"], "priority": 10}
    ],
    "workflows": [
        {
            "id": "coding",
            "name": "Coding",
            "keywords": ["code", "api"],
            "capabilities": ["engineering-specialist"],
            "priority": 10,
            "approval_gates": ["external_write"],
            "stages": [
                {
                    "id": "specialist",
                    "name": "Engineering specialist",
                    "capabilities": ["engineering-specialist"],
                    "approval": "approval_required",
                    "depends_on": [],
                }
            ],
        }
    ],
}


class RoutingValidationTests(unittest.TestCase):
    def test_rejects_secret_absolute_path_and_traversal(self):
        for bad in (
            {**BASE, "notes": "api_key=do-not-store"},
            {**BASE, "notes": "/opt/data/private"},
            {**BASE, "notes": "../private"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(routing.RoutingValidationError):
                    routing.validate_config(bad, ROSTER)

    def test_rejects_duplicate_ids_and_invalid_self_loop(self):
        duplicate = {**BASE, "workflows": [BASE["workflows"][0], {**BASE["workflows"][0]}]}
        duplicate["workflows"][1]["id"] = "coding"
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(duplicate, ROSTER)
        loop = json.loads(json.dumps(BASE))
        loop["workflows"][0]["stages"][0]["depends_on"] = ["specialist"]
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(loop, ROSTER)

    def test_capability_preview_is_deterministic_and_unknown_safe(self):
        config = routing.validate_config(BASE, ROSTER)
        first = routing.preview_route(config, ROSTER, "Please fix the backend API", ["engineering-specialist"])
        second = routing.preview_route(config, ROSTER, "Please fix the backend API", ["engineering-specialist"])
        self.assertEqual(first, second)
        self.assertEqual(first["workflow"]["id"], "coding")
        self.assertEqual(first["stages"][0]["selected_agent_id"], "backend-data")
        unknown = json.loads(json.dumps(ROSTER))
        unknown[1]["id"] = "missing-agent"
        preview = routing.preview_route(config, unknown, "Please fix the backend API", [])
        self.assertEqual(preview["stages"][0]["selected_agent_id"], "missing-agent")
        self.assertNotIn("live_status", json.dumps(preview))

    def test_live_workflow_previews_use_metadata_filters_and_remain_configuration_only(self):
        config = routing.validate_config(LIVE_CONFIG, LIVE_ROSTER)
        cases = [
            (
                "coding-pipeline",
                "Fix the backend API and add tests",
                ["engineering-specialist"],
                [
                    ("lead-intake", "hermes-lead"),
                    ("engineering-plan", "agent-engineer"),
                    ("specialist", "backend-data"),
                    ("executor", None),
                    ("verification", "agent-engineer"),
                ],
            ),
            (
                "content-pipeline",
                "Create a content campaign from current trends",
                ["content"],
                [
                    ("research", "social-research-trends"),
                    ("content", "content-planner-copywriter"),
                    ("visual", "visual-ugc-designer"),
                    ("approval", "hermes-lead"),
                ],
            ),
            (
                "document-workflow",
                "Prepare a knowledge document brief",
                ["document"],
                [
                    ("research", "document-knowledge"),
                    ("document", "document-knowledge"),
                    ("approval", "hermes-lead"),
                ],
            ),
            (
                "finance-workflow",
                "Prepare a finance budget forecast",
                ["finance"],
                [
                    ("analysis", "finance-assistant"),
                    ("document", "finance-assistant"),
                    ("approval", "hermes-lead"),
                ],
            ),
            (
                "assistant-general",
                "Help organize my schedule",
                ["assistant"],
                [("assist", "personal-assistant"), ("review", "hermes-lead")],
            ),
        ]
        for workflow_id, task, hints, expected in cases:
            with self.subTest(workflow=workflow_id):
                preview = routing.preview_route(config, LIVE_ROSTER, task, hints)
                self.assertEqual(preview["workflow"]["id"], workflow_id)
                self.assertEqual(
                    [(stage["id"], stage["selected_agent_id"]) for stage in preview["stages"]],
                    expected,
                )
                self.assertFalse(preview["execution"]["launched"])
                self.assertFalse(preview["execution"]["external_writes"])

        coding = next(row for row in config["workflows"] if row["id"] == "coding-pipeline")
        coding_stages = {row["id"]: row for row in coding["stages"]}
        self.assertEqual(coding_stages["lead-intake"]["metadata_filters"], {"runtime_mode": "lead"})
        self.assertEqual(coding_stages["engineering-plan"]["metadata_filters"], {"runtime_mode": "planner"})
        self.assertEqual(coding_stages["verification"]["metadata_filters"], {"runtime_mode": "planner"})
        content = next(row for row in config["workflows"] if row["id"] == "content-pipeline")
        content_research = next(row for row in content["stages"] if row["id"] == "research")
        self.assertEqual(content_research["capabilities"], ["content-research"])
        self.assertEqual(
            next(row for row in content["stages"] if row["id"] == "approval")["metadata_filters"],
            {"runtime_mode": "lead"},
        )
        document = next(row for row in config["workflows"] if row["id"] == "document-workflow")
        self.assertEqual(next(row for row in document["stages"] if row["id"] == "research")["capabilities"], ["research"])

    def test_metadata_filter_rejects_unknown_keys(self):
        config = json.loads(json.dumps(BASE))
        config["workflows"][0]["stages"][0]["metadata_filters"] = {"unknown_field": "value"}
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(config, ROSTER)


class RoutingPersistenceTests(unittest.TestCase):
    def test_atomic_write_creates_backup_and_reads_back(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "workflows.json"
            routing.atomic_write_config(path, BASE)
            updated = json.loads(json.dumps(BASE))
            updated["default_workflow"] = "coding"
            routing.atomic_write_config(path, updated)
            self.assertTrue(path.is_file())
            self.assertTrue(path.with_name("workflows.json.bak").is_file())
            self.assertEqual(routing.load_config(path)["version"], 1)
            self.assertEqual(json.loads(path.with_name("workflows.json.bak").read_text())["version"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
