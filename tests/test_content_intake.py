#!/usr/bin/env python3
"""TDD contracts for bounded, approval-gated content intake."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


BASE = Path("/opt/data/mission-control")
MODULE_PATH = BASE / "content_intake.py"
_spec = importlib.util.spec_from_file_location("mission_control_content_intake_test", MODULE_PATH)
_content_intake = importlib.util.module_from_spec(_spec)
if _spec.loader is not None:
    _spec.loader.exec_module(_content_intake)


AGENT = {
    "id": "content-intake-concierge",
    "model": "opencode-go/deepseek-v4-flash",
    "active": False,
    "routing": {
        "runtime_adapter": "provider_oneshot",
        "runtime_mode": "specialist",
        "availability": "on_demand",
        "approval_policy": "approval_required",
    },
}


class ContentIntakeTests(unittest.TestCase):
    def test_build_argv_is_explicit_provider_bounded_and_safe_mode(self):
        argv = _content_intake.build_chat_argv(AGENT["model"])
        self.assertIn("--provider", argv)
        self.assertEqual(argv[argv.index("--provider") + 1], "opencode-go")
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "deepseek-v4-flash")
        self.assertIn("--safe-mode", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertEqual(argv[argv.index("--query-file") + 1], "-")

    def test_brief_rejects_credential_shaped_input(self):
        with self.assertRaises(_content_intake.ContentIntakeValidationError):
            _content_intake.validate_brief("api_key=secret-value; please publish this")

    def test_run_returns_structured_draft_with_approval_boundary(self):
        response = json.dumps({
            "normalized_brief": {
                "channel": "Instagram",
                "objective": "launch",
                "product": "blue linen shirt",
            },
            "missing_inputs": ["product link", "approved asset"],
            "routing_recommendation": "Route to content planner after lead review.",
            "escalation": "Escalate if rights or CTA remain unclear.",
        }) + "\n\nsession_id: hidden"
        fake = type("Proc", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with patch.object(_content_intake.subprocess, "run", return_value=fake) as run:
            result = _content_intake.run_content_intake(
                brief="Launch the blue linen shirt on Instagram by October 10, 2026.",
                agent=AGENT,
            )
        self.assertEqual(result["status"], "draft_ready")
        self.assertTrue(result["approval_required"])
        self.assertFalse(result["external_write"])
        self.assertFalse(result["autonomous"])
        self.assertEqual(result["draft"]["missing_inputs"], ["product link", "approved asset"])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--provider") + 1], "opencode-go")
        self.assertEqual(run.call_args.kwargs["input"].count("Launch the blue linen shirt"), 1)

    def test_run_accepts_escalation_list_from_provider(self):
        response = json.dumps({
            "normalized_brief": {"channel": "Instagram"},
            "missing_inputs": [],
            "routing_recommendation": "lead review",
            "escalation": ["rights check", "missing approval"],
        })
        fake = type("Proc", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with patch.object(_content_intake.subprocess, "run", return_value=fake):
            result = _content_intake.run_content_intake(brief="A normal public brief", agent=AGENT)
        self.assertEqual(result["draft"]["escalation"], ["rights check", "missing approval"])

    def test_run_rejects_agent_without_approval_gated_provider_contract(self):
        unsafe = dict(AGENT)
        unsafe["routing"] = dict(AGENT["routing"], approval_policy="none")
        with self.assertRaises(_content_intake.ContentIntakeBlockedError):
            _content_intake.run_content_intake(brief="A normal public brief", agent=unsafe)

    def test_malformed_provider_output_fails_closed(self):
        fake = type("Proc", (), {"returncode": 0, "stdout": "not-json", "stderr": ""})()
        with patch.object(_content_intake.subprocess, "run", return_value=fake):
            with self.assertRaises(_content_intake.ContentIntakeProviderError):
                _content_intake.run_content_intake(brief="A normal public brief", agent=AGENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
