#!/usr/bin/env python3
"""Focused roster readiness and read-only GET regression tests."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
_spec = importlib.util.spec_from_file_location("mission_control_roster_audit_test", PLUGIN)
plugin = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(plugin)


class RosterAuditTests(unittest.TestCase):
    def _cached_models(self, name, _ttl, builder):
        if name == "models":
            return {
                "plugin": "mission-control",
                "models": {
                    "total": 1,
                    "default": "provider/exact-model",
                    "providers": {"provider": ["exact-model"]},
                    "provider_details": {
                        "provider": {
                            "authenticated": True,
                            "sources": ["test"],
                        }
                    },
                },
            }
        return builder()

    def test_roster_get_does_not_provision_or_save_workspaces(self):
        agents = [{
            "id": "agent-one",
            "name": "Agent One",
            "role": "test",
            "model": "provider/exact-model",
            "skills": [],
            "persona": "persona",
            "active": False,
            "system": False,
            "drive_workspace": {"status": "pending", "name": "workspace"},
        }]
        with patch.object(plugin, "_load_agents", return_value=agents), \
             patch.object(plugin, "_ensure_all_agent_workspaces") as ensure, \
             patch.object(plugin, "_save_agents") as save, \
             patch.object(plugin, "_real_models_lookup", return_value={"provider": {"exact-model"}}), \
             patch.object(plugin, "_real_skill_names", return_value=set()), \
             patch.object(plugin, "_agent_live", return_value={"status": "standby", "sessions": None}), \
             patch.object(plugin, "_cached", side_effect=self._cached_models):
            result = plugin._build_roster()
        self.assertEqual(result["status"], "ok")
        ensure.assert_not_called()
        save.assert_not_called()

    def test_model_readiness_requires_exact_model_id_and_preserves_reference(self):
        agents = [
            {
                "id": "missing",
                "name": "Missing",
                "role": "test",
                "model": "provider/missing-model",
                "skills": [],
                "persona": "persona",
                "active": False,
                "system": False,
            },
            {
                "id": "exact",
                "name": "Exact",
                "role": "test",
                "model": "provider/exact-model",
                "skills": [],
                "persona": "persona",
                "active": False,
                "system": False,
            },
        ]
        with patch.object(plugin, "_load_agents", return_value=agents), \
             patch.object(plugin, "_real_models_lookup", return_value={"provider": {"exact-model"}}), \
             patch.object(plugin, "_real_skill_names", return_value=set()), \
             patch.object(plugin, "_agent_live", return_value={"status": "standby", "sessions": None}), \
             patch.object(plugin, "_cached", side_effect=self._cached_models):
            rows = plugin._build_roster()["agents"]
        missing = next(row for row in rows if row["id"] == "missing")
        exact = next(row for row in rows if row["id"] == "exact")
        self.assertEqual(missing["model"], "provider/missing-model")
        self.assertEqual(missing["model_provider"], "provider")
        self.assertEqual(missing["model_id"], "missing-model")
        self.assertTrue(missing["provider_catalog_available"])
        self.assertFalse(missing["model_catalog_available"])
        self.assertFalse(missing["model_available"])
        self.assertFalse(missing["model_connected"])
        self.assertTrue(exact["provider_connected"])
        self.assertTrue(exact["model_catalog_available"])
        self.assertTrue(exact["model_available"])
        self.assertTrue(exact["model_connected"])

    def test_roster_exposes_configured_and_live_state_separately(self):
        agent = {
            "id": "agent-one",
            "name": "Agent One",
            "role": "test",
            "model": "provider/exact-model",
            "skills": [],
            "persona": "persona",
            "active": False,
            "system": False,
        }
        live = {"status": "standby", "sessions": None, "detail": "not running", "source_status": "not_configured"}
        with patch.object(plugin, "_load_agents", return_value=[agent]), \
             patch.object(plugin, "_real_models_lookup", return_value={"provider": {"exact-model"}}), \
             patch.object(plugin, "_real_skill_names", return_value=set()), \
             patch.object(plugin, "_agent_live", return_value=live), \
             patch.object(plugin, "_cached", side_effect=self._cached_models):
            row = plugin._build_roster()["agents"][0]
        self.assertFalse(row["active"])
        self.assertFalse(row["configured_active"])
        self.assertEqual(row["live_status"], "standby")
        self.assertEqual(row["live_source_status"], "not_configured")
        self.assertEqual(row["live_detail"], "not running")


if __name__ == "__main__":
    unittest.main(verbosity=2)
