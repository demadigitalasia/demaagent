#!/usr/bin/env python3
"""Focused tests for explicit Hermes provider/model routing."""
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path("/opt/data/scripts/mission_control_provider_launcher.py")
_spec = importlib.util.spec_from_file_location("mission_control_provider_launcher_test", SCRIPT)
launcher = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(launcher)


ROSTER_MODEL_REFS = (
    "openai-codex/gpt-5.6-luna",
    "opencode-go/deepseek-v4-flash",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "opencode-go/deepseek-v4-flash-vision-exp",
)


class ProviderRoutingTests(unittest.TestCase):
    def test_parse_preserves_provider_and_nested_model_id(self):
        provider, model_id = launcher.parse_model_ref(
            "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
        )
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model_id, "nvidia/nemotron-3-super-120b-a12b:free")

    def test_every_unique_roster_model_gets_explicit_provider_and_model(self):
        for model_ref in ROSTER_MODEL_REFS:
            with self.subTest(model_ref=model_ref):
                provider, model_id = launcher.parse_model_ref(model_ref)
                argv = launcher.build_chat_argv(
                    model_ref=model_ref,
                    max_turns=1,
                    run_budget_s=17,
                )
                self.assertEqual(argv[0], launcher.HERMES_BIN)
                self.assertIn("--provider", argv)
                self.assertIn("--model", argv)
                self.assertEqual(argv[argv.index("--provider") + 1], provider)
                self.assertEqual(argv[argv.index("--model") + 1], model_id)
                self.assertNotIn(model_ref, argv)
                self.assertIn("--run-budget", argv)
                self.assertEqual(argv[argv.index("--run-budget") + 1], "17")
                self.assertNotIn("--token", argv)
                self.assertNotIn("Bearer", " ".join(argv))

    def test_invalid_model_refs_fail_closed(self):
        for value in ("", "gpt-5.6-luna", "/model", "provider/", " provider/model"):
            with self.subTest(value=value):
                with self.assertRaises(launcher.ProviderRoutingError):
                    launcher.parse_model_ref(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
