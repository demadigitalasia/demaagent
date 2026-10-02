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
            "parent_id": "hermes-lead",
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
                    ("research", "social-research-trends"),
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
                    ("document", "document-knowledge"),
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

    def test_routing_collision_matrix_uses_domain_selectors_and_narrow_workflow_intent(self):
        config = routing.validate_config(LIVE_CONFIG, LIVE_ROSTER)
        cases = [
            (
                "frontend",
                "Build a frontend React product UI and add accessibility tests",
                ["engineering-specialist"],
                "coding-frontend-pipeline",
                {"specialist": "frontend-product-ui"},
            ),
            (
                "devops",
                "Prepare a DevOps deployment health check and rollback runbook",
                ["engineering-specialist"],
                "coding-devops-pipeline",
                {"specialist": "devops-sre"},
            ),
            (
                "content-caption",
                "Write an Instagram caption for the approved campaign",
                ["content"],
                "content-pipeline",
                {"content": "content-planner-copywriter"},
            ),
            (
                "generic-document",
                "Prepare a generic document research brief",
                ["document"],
                "document-workflow",
                {"research": "social-research-trends", "document": "document-knowledge"},
            ),
            (
                "generic-research",
                "Research current trends and cite sources",
                ["research"],
                "document-workflow",
                {"research": "social-research-trends", "document": "document-knowledge"},
            ),
            (
                "finance-invoice",
                "Analyze this finance invoice and prepare a finance report",
                ["finance"],
                "finance-workflow",
                {"analysis": "finance-assistant", "document": "document-knowledge"},
            ),
            (
                "media-monitoring",
                "Monitor media and social listening for this issue",
                ["media-monitoring"],
                "media-monitoring-pipeline",
                {"online-media-monitoring": "social-research-trends"},
            ),
            (
                "apify",
                "Use Apify Actor for media monitoring",
                ["media-monitoring"],
                "apify-media-monitoring-pipeline",
                {"apify-collection": "social-research-trends"},
            ),
        ]
        for label, task, hints, workflow_id, expected_stages in cases:
            with self.subTest(case=label):
                preview = routing.preview_route(config, LIVE_ROSTER, task, hints)
                self.assertEqual(preview["workflow"]["id"], workflow_id)
                selected = {stage["id"]: stage["selected_agent_id"] for stage in preview["stages"]}
                for stage_id, agent_id in expected_stages.items():
                    self.assertEqual(selected.get(stage_id), agent_id)
                self.assertFalse(preview["execution"]["launched"])
                self.assertFalse(preview["execution"]["external_writes"])

        media = routing.preview_route(
            config, LIVE_ROSTER, "Write a content caption for Instagram", ["content"]
        )
        self.assertEqual(media["workflow"]["id"], "content-pipeline")

    def test_routing_selector_fields_are_validated_and_unknown_refs_fail_closed(self):
        config = json.loads(json.dumps(LIVE_CONFIG))
        workflow = next(row for row in config["workflows"] if row["id"] == "coding-pipeline")
        self.assertIn("routing_capabilities", workflow)
        specialist = next(stage for stage in workflow["stages"] if stage["id"] == "specialist")
        self.assertIn("routing_domains", specialist)
        backend = next(row for row in LIVE_ROSTER if row["id"] == "backend-data")
        self.assertIn("routing_domains", backend["routing"])

        unknown_workflow = json.loads(json.dumps(config))
        unknown_workflow["workflows"][0]["routing_capabilities"] = ["not-declared"]
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(unknown_workflow, LIVE_ROSTER)

        unknown_agent = json.loads(json.dumps(config))
        unknown_agent["workflows"][0]["stages"][0]["candidate_agent_ids"] = ["not-in-roster"]
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(unknown_agent, LIVE_ROSTER)

    def test_apify_workflow_is_explicit_and_does_not_steal_baseline_route(self):
        config = routing.validate_config(LIVE_CONFIG, LIVE_ROSTER)
        workflow = next(row for row in config["workflows"] if row["id"] == "apify-media-monitoring-pipeline")
        self.assertEqual(workflow["priority"], 89)
        self.assertEqual(workflow["approval_gates"], ["external_write"])
        self.assertEqual(
            [stage["id"] for stage in workflow["stages"]],
            [
                "lead-intake",
                "watch-contract",
                "apify-collection",
                "dataset-readback",
                "normalize-dedupe",
                "evidence-review",
                "briefing",
                "archive",
                "owner-approval",
            ],
        )
        apify_stage = next(stage for stage in workflow["stages"] if stage["id"] == "apify-collection")
        self.assertEqual(apify_stage["candidate_agent_ids"], ["social-research-trends"])
        self.assertEqual(apify_stage["executor_ref"], "collector:apify")
        task = "jalankan media monitoring Bupati Cianjur menggunakan Apify Actor untuk social listening"
        for hints in (["media-monitoring"], ["research"]):
            with self.subTest(hints=hints):
                preview = routing.preview_route(config, LIVE_ROSTER, task, hints)
                self.assertEqual(preview["workflow"]["id"], "apify-media-monitoring-pipeline")
                self.assertFalse(preview["execution"]["launched"])
                self.assertFalse(preview["execution"]["external_writes"])
                self.assertEqual(
                    [(stage["id"], stage["selected_agent_id"]) for stage in preview["stages"]],
                    [
                        ("lead-intake", "hermes-lead"),
                        ("watch-contract", "social-research-trends"),
                        ("apify-collection", "social-research-trends"),
                        ("dataset-readback", "social-research-trends"),
                        ("normalize-dedupe", "proposal-reviewer"),
                        ("evidence-review", "proposal-reviewer"),
                        ("briefing", "content-planner-copywriter"),
                        ("archive", "document-knowledge"),
                        ("owner-approval", "hermes-lead"),
                    ],
                )
        baseline = routing.preview_route(
            config,
            LIVE_ROSTER,
            "jalankan media monitoring Bupati Cianjur untuk social listening",
            ["media-monitoring"],
        )
        self.assertEqual(baseline["workflow"]["id"], "media-monitoring-pipeline")

    def test_metadata_filter_rejects_unknown_keys(self):
        config = json.loads(json.dumps(BASE))
        config["workflows"][0]["stages"][0]["metadata_filters"] = {"unknown_field": "value"}
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(config, ROSTER)

    def test_agent_metadata_rejects_unknown_and_unsafe_runtime_contract_fields(self):
        metadata = json.loads(json.dumps(ROSTER[0]["routing"]))
        bad_rows = (
            {**metadata, "unknown_field": "must-fail"},
            {**metadata, "runtime_mode": "autonomous"},
            {**metadata, "approval_policy": "none"},
            {**metadata, "available": "yes"},
            {**metadata, "runtime_adapter": "unsupported_adapter"},
        )
        for bad in bad_rows:
            with self.subTest(bad=bad):
                with self.assertRaises(routing.RoutingValidationError):
                    routing.validate_agent_routing_metadata(bad, {row["id"] for row in ROSTER})

    def test_roster_rejects_ambiguous_parent_cycle(self):
        roster = json.loads(json.dumps(ROSTER))
        roster[0]["routing"]["parent_id"] = "backend-data"
        roster[1]["routing"]["parent_id"] = "hermes-lead"
        with self.assertRaises(routing.RoutingValidationError):
            routing.validate_config(BASE, roster)

    def test_routing_schema_rejects_unknown_fields_at_each_contract_level(self):
        cases = []
        top_level = json.loads(json.dumps(BASE))
        top_level["unknown_field"] = "must-fail"
        cases.append(top_level)
        rule = json.loads(json.dumps(BASE))
        rule["routing_rules"][0]["unknown_field"] = "must-fail"
        cases.append(rule)
        workflow = json.loads(json.dumps(BASE))
        workflow["workflows"][0]["unknown_field"] = "must-fail"
        cases.append(workflow)
        stage = json.loads(json.dumps(BASE))
        stage["workflows"][0]["stages"][0]["unknown_field"] = "must-fail"
        cases.append(stage)
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(routing.RoutingValidationError):
                    routing.validate_config(bad, ROSTER)


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
