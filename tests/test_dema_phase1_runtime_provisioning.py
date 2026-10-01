#!/usr/bin/env python3
"""Focused contract tests for the approved DEMA roster provisioning."""

import json
import re
import unittest
from pathlib import Path


ROSTER = Path("/opt/data/mission-control/agents.json")
ORIGINAL_IDS = {
    "hermes-lead",
    "agent-engineer",
    "opencode",
    "agent-socmed",
    "news-agent",
    "sub-agent-back-end",
    "sub-agent-devops",
    "sub-agent-front-end",
    "sub-agent-ui-ux",
}
TARGET_IDS = {"dema-assistant", "dema-lead"}
TARGET_MODEL = "openai-codex/gpt-5.6-luna"
SAFE_SKILLS = {"obsidian", "llm-wiki", "grounded-citations"}
EXTERNAL_SIDE_EFFECT_SKILLS = {
    "coolify",
    "codex",
    "google-workspace",
    "github",
    "gws",
    "xurl",
    "email-inbox-triage",
    "telegram",
    "social-posting",
    "deploy",
}
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

FROZEN_ORIGINAL = {
    "hermes-lead": {
        "model": "openai-codex/gpt-5.6-luna",
        "skills": [
            "hermes-agent", "google-workspace", "github", "agent-engineer", "opencode",
            "codex", "claude-code", "youtube-content", "obsidian", "xlsx", "docx", "pdf",
            "arxiv", "maps", "gif-search", "humanizer", "songwriting-and-ai-music",
            "email-inbox-triage", "mission-control", "grounded-citations", "llm-wiki",
        ],
        "active": False,
        "system": True,
    },
    "agent-engineer": {
        "model": "openai-codex/gpt-5.6-luna",
        "skills": [
            "agent-engineer", "github", "opencode", "codex", "claude-code",
            "systematic-debugging", "test-driven-development", "simplify-code",
            "requesting-code-review", "spike", "codebase-inspection",
            "github-release-binary-install", "mission-control", "obsidian", "llm-wiki",
        ],
        "active": False,
        "system": True,
    },
    "opencode": {
        "model": "opencode-go/deepseek-v4-flash",
        "skills": ["opencode"],
        "active": False,
        "system": True,
    },
    "agent-socmed": {
        "model": "opencode-go/deepseek-v4-flash",
        "skills": ["xurl", "dema-social-content", "obsidian", "llm-wiki"],
        "active": False,
        "system": False,
    },
    "news-agent": {
        "model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
        "skills": ["competitor-news-monitor", "arxiv", "grounded-citations", "obsidian", "llm-wiki"],
        "active": False,
        "system": False,
    },
    "sub-agent-back-end": {
        "model": "opencode-go/deepseek-v4-flash",
        "skills": [
            "test-driven-development", "systematic-debugging", "codebase-inspection",
            "requesting-code-review", "spike", "github", "mission-control", "obsidian", "llm-wiki",
        ],
        "active": False,
        "system": False,
    },
    "sub-agent-devops": {
        "model": "opencode-go/deepseek-v4-flash",
        "skills": [
            "coolify", "github", "github-release-binary-install", "mission-control",
            "codebase-inspection", "obsidian", "llm-wiki",
        ],
        "active": False,
        "system": False,
    },
    "sub-agent-front-end": {
        "model": "opencode-go/deepseek-v4-flash",
        "skills": [
            "claude-design", "popular-web-designs", "design-md", "dogfood", "spike",
            "mission-control", "obsidian", "llm-wiki",
        ],
        "active": False,
        "system": False,
    },
    "sub-agent-ui-ux": {
        "model": "opencode-go/deepseek-v4-flash-vision-exp",
        "skills": [
            "claude-design", "design-md", "popular-web-designs", "architecture-diagram",
            "dogfood", "mission-control", "obsidian", "llm-wiki",
        ],
        "active": False,
        "system": False,
    },
}


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

    def test_exact_original_roster_is_frozen_and_only_two_targets_added(self):
        self.assertEqual(len(self.roster), 11)
        self.assertEqual(set(self.by_id), ORIGINAL_IDS | TARGET_IDS)
        self.assertEqual(set(self.by_id) - ORIGINAL_IDS, TARGET_IDS)
        self.assertEqual(set(self.by_id) & ORIGINAL_IDS, ORIGINAL_IDS)
        for agent_id, expected in FROZEN_ORIGINAL.items():
            row = self.by_id[agent_id]
            for field in ("model", "skills", "active", "system"):
                self.assertEqual(row.get(field), expected[field], f"{agent_id}:{field}")

    def test_approved_entries_have_exact_model_and_inactive_non_system_state(self):
        for agent_id in TARGET_IDS:
            row = self.by_id[agent_id]
            self.assertTrue(row.get("name"), agent_id)
            self.assertTrue(row.get("role"), agent_id)
            self.assertTrue(row.get("persona"), agent_id)
            self.assertTrue(row.get("skills"), agent_id)
            self.assertEqual(row.get("model"), TARGET_MODEL, agent_id)
            self.assertIs(row.get("active"), False, agent_id)
            self.assertIs(row.get("system"), False, agent_id)
            self.assertEqual(set(row["skills"]), SAFE_SKILLS, agent_id)
            self.assertTrue(set(row["skills"]).isdisjoint(EXTERNAL_SIDE_EFFECT_SKILLS), agent_id)

    def test_personas_document_entry_and_coordination_boundaries(self):
        assistant = self.by_id["dema-assistant"]["persona"]
        lead = self.by_id["dema-lead"]["persona"]
        common_requirements = (
            "10-Wiki",
            "future tenant-scoped context",
            "proposal-only",
            "human approval",
            "no roster mutation",
            "no external send/write",
            "not ready for public/multi-user use",
        )
        for persona in (assistant, lead):
            lowered = persona.casefold()
            for phrase in common_requirements:
                self.assertIn(phrase.casefold(), lowered)
        self.assertIn("assistant entry boundary", assistant.casefold())
        self.assertIn("lead coordination boundary", lead.casefold())
        self.assertIn("handoff", assistant.casefold())
        self.assertIn("domain", lead.casefold())

    def test_new_entries_have_no_autonomy_tenant_or_external_side_effect_fields(self):
        for agent_id in TARGET_IDS:
            row = self.by_id[agent_id]
            self.assertTrue(FORBIDDEN_KEYS.isdisjoint(row), agent_id)
            encoded = json.dumps(row, ensure_ascii=False)
            self.assertNotIn("/opt/data/", encoded, agent_id)
            self.assertNotIn("/home/", encoded, agent_id)
            self.assertIsNone(SECRET_VALUE.search(encoded), agent_id)
            self.assertNotIn("private_obsidian_namespace", encoded.casefold(), agent_id)
            self.assertNotIn("memory_namespace", encoded.casefold(), agent_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
