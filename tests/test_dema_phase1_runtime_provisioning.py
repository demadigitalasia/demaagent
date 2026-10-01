#!/usr/bin/env python3
"""Focused contract tests for the approved DEMA roster provisioning."""

import json
import re
import unittest
from pathlib import Path


ROSTER = Path("/opt/data/mission-control/agents.json")
ORIGINAL_IDS = {
    row["id"] for row in json.loads(ROSTER.read_text(encoding="utf-8"))
}
TARGET_IDS = {"dema-assistant", "dema-lead"}
FORBIDDEN_KEYS = {
    "autonomous_allowed",
    "cron",
    "crons",
    "scheduler",
    "schedule",
    "persistent_mcp",
    "tenant_id",
    "tenant_ids",
    "tenant_provisioning",
    "external_send",
    "external_write",
    "provider_credentials",
    "runtime_token",
    "runtime_tokens",
}
SECRET_VALUE = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|(?:ghp|github_pat|sk|xox[baprs])-[_A-Za-z0-9-]{12,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
    re.IGNORECASE,
)

def walk(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, path + (str(index),))


class TestDemaPhase1RuntimeProvisioning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = json.loads(ROSTER.read_text(encoding="utf-8"))
        cls.by_id = {row["id"]: row for row in cls.roster}

    def test_current_roster_is_configuration_source(self):
        self.assertEqual(set(self.by_id), ORIGINAL_IDS)
        self.assertEqual(len(self.roster), len(ORIGINAL_IDS))
        self.assertTrue(TARGET_IDS.isdisjoint(self.by_id))

    def test_current_roster_rows_have_no_unapproved_provisioning_fields(self):
        for agent_id, row in self.by_id.items():
            self.assertTrue(FORBIDDEN_KEYS.isdisjoint(row), agent_id)
            encoded = json.dumps(row, ensure_ascii=False)
            self.assertNotIn("/opt/data/", encoded, agent_id)
            self.assertNotIn("/home/", encoded, agent_id)
            self.assertIsNone(SECRET_VALUE.search(encoded), agent_id)
            self.assertNotIn("private_obsidian_namespace", encoded.casefold(), agent_id)
            self.assertNotIn("memory_namespace", encoded.casefold(), agent_id)

    def test_current_roster_agents_are_inactive_until_explicitly_configured(self):
        for agent_id, row in self.by_id.items():
            self.assertIs(row.get("active"), False, agent_id)
            self.assertTrue(row.get("name"), agent_id)
            self.assertTrue(row.get("role"), agent_id)
            self.assertTrue(row.get("skills"), agent_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
