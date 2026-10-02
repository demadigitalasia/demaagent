#!/usr/bin/env python3
"""TDD contracts for the bounded content safety/review gate."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


BASE = Path("/opt/data/mission-control")
MODULE_PATH = BASE / "content_review.py"
_spec = importlib.util.spec_from_file_location("mission_control_content_review_test", MODULE_PATH)
_review = importlib.util.module_from_spec(_spec)
if _spec.loader is not None:
    _spec.loader.exec_module(_review)


REVIEWER = {
    "id": "proposal-reviewer",
    "model": "openrouter/openai/gpt-6.1-sol",
    "routing": {
        "runtime_adapter": "provider_oneshot",
        "runtime_mode": "specialist",
        "availability": "on_demand",
        "approval_policy": "approval_required",
    },
}
DRAFT = {
    "normalized_brief": {"channel": "Instagram", "claim": "blue linen shirt launch"},
    "missing_inputs": ["product link"],
    "routing_recommendation": "lead review",
    "escalation": ["rights check"],
}


class ContentReviewTests(unittest.TestCase):
    def test_build_argv_uses_explicit_reviewer_provider_and_safe_mode(self):
        argv = _review.build_chat_argv(REVIEWER["model"])
        self.assertEqual(argv[argv.index("--provider") + 1], "openrouter")
        self.assertEqual(argv[argv.index("--model") + 1], "openai/gpt-6.1-sol")
        self.assertIn("--safe-mode", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")

    def test_review_returns_publish_gate_even_when_ready_for_approval(self):
        response = json.dumps({
            "overall_status": "ready_for_approval",
            "findings": [
                {
                    "category": "completeness",
                    "severity": "low",
                    "status": "pass",
                    "evidence": "Product and channel are stated; product link remains missing.",
                    "recommendation": "Confirm link before publication.",
                }
            ],
            "approval_blockers": [],
            "review_summary": "No blocking safety issue found; owner approval remains required.",
        }) + "\nsession_id: hidden"
        fake = type("Proc", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with patch.object(_review.subprocess, "run", return_value=fake) as run:
            result = _review.review_content_package(
                brief="Launch the blue linen shirt on Instagram.",
                draft=DRAFT,
                reviewer_agent=REVIEWER,
            )
        self.assertEqual(result["status"], "review_complete")
        self.assertEqual(result["review"]["overall_status"], "ready_for_approval")
        self.assertEqual(result["publish_gate"], "owner_approval_required")
        self.assertTrue(result["approval_required"])
        self.assertFalse(result["external_write"])
        self.assertFalse(result["autonomous"])
        self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--provider") + 1], "openrouter")

    def test_review_rejects_credential_shaped_evidence(self):
        with self.assertRaises(_review.ContentReviewValidationError):
            _review.review_content_package(
                brief="A normal brief",
                draft=DRAFT,
                evidence={"source": "access_token=secret-value"},
                reviewer_agent=REVIEWER,
            )

    def test_review_rejects_reviewer_without_approval_boundary(self):
        unsafe = dict(REVIEWER)
        unsafe["routing"] = dict(REVIEWER["routing"], approval_policy="external_write")
        with self.assertRaises(_review.ContentReviewBlockedError):
            _review.review_content_package(brief="A normal brief", draft=DRAFT, reviewer_agent=unsafe)

    def test_review_fails_closed_on_blocker_inconsistent_ready_status(self):
        response = json.dumps({
            "overall_status": "ready_for_approval",
            "findings": [{
                "category": "copyright",
                "severity": "critical",
                "status": "block",
                "evidence": "Rights are unknown.",
                "recommendation": "Obtain rights confirmation.",
            }],
            "approval_blockers": ["rights confirmation"],
            "review_summary": "Blocked.",
        })
        fake = type("Proc", (), {"returncode": 0, "stdout": response, "stderr": ""})()
        with patch.object(_review.subprocess, "run", return_value=fake):
            with self.assertRaises(_review.ContentReviewProviderError):
                _review.review_content_package(brief="A normal brief", draft=DRAFT, reviewer_agent=REVIEWER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
