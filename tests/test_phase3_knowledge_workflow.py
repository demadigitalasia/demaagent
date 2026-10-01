import json
import re
import unittest
from pathlib import Path


ROSTER_PATH = Path('/opt/data/mission-control/agents.json')
VAULT = Path('/opt/data/obsidian-vault')
NOTE_PATH = VAULT / '10-Wiki/concepts/Agent Knowledge Workflow.md'
INDEX_PATH = VAULT / '10-Wiki/index.md'
LOG_PATH = VAULT / '10-Wiki/log.md'
PROTOCOL_MARKER = 'KNOWLEDGE WORKFLOW PROTOCOL'
REQUIRED_PROFILE_FIELDS = {
    'mission', 'authority', 'operating_mode', 'language', 'allowed_actions',
    'forbidden_actions', 'inputs', 'outputs', 'verification', 'escalation',
}


class TestPhase3AgentKnowledgeWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding='utf-8'))
        cls.by_id = {agent['id']: agent for agent in cls.roster}
        cls.note = NOTE_PATH.read_text(encoding='utf-8')
        cls.index = INDEX_PATH.read_text(encoding='utf-8')
        cls.log = LOG_PATH.read_text(encoding='utf-8')

    def test_current_knowledge_agents_have_unique_knowledge_skills_and_executor_boundary(self):
        target_ids = {
            agent['id'] for agent in self.roster
            if {'obsidian', 'llm-wiki'}.issubset(set(agent.get('skills', [])))
        }
        self.assertTrue(target_ids)
        self.assertEqual(set(self.by_id), {agent['id'] for agent in self.roster})
        for agent_id in target_ids:
            agent = self.by_id[agent_id]
            skills = agent.get('skills', [])
            self.assertEqual(len(skills), len(set(skills)), agent_id)
            self.assertIn('obsidian', skills, agent_id)
            self.assertIn('llm-wiki', skills, agent_id)
            self.assertIsInstance(agent.get('persona_profile'), dict, agent_id)
            self.assertEqual(set(agent['persona_profile']), REQUIRED_PROFILE_FIELDS, agent_id)
        if 'opencode' in self.by_id:
            self.assertEqual(self.by_id['opencode'].get('skills'), ['opencode'])
            self.assertNotIn('obsidian', self.by_id['opencode'].get('skills', []))
            self.assertNotIn('llm-wiki', self.by_id['opencode'].get('skills', []))

    def test_persona_profiles_are_separate_and_complete_for_knowledge_agents(self):
        target_ids = {
            agent['id'] for agent in self.roster
            if {'obsidian', 'llm-wiki'}.issubset(set(agent.get('skills', [])))
        }
        for agent_id in target_ids:
            agent = self.by_id[agent_id]
            self.assertIsInstance(agent.get('persona'), str)
            profile = agent.get('persona_profile')
            self.assertIsInstance(profile, dict, agent_id)
            self.assertEqual(set(profile), REQUIRED_PROFILE_FIELDS, agent_id)
            for field in REQUIRED_PROFILE_FIELDS:
                value = profile[field]
                if isinstance(value, list):
                    self.assertTrue(value, f'{agent_id}: {field}')
                else:
                    self.assertTrue(value.strip(), f'{agent_id}: {field}')
            combined = '\\n'.join([
                agent.get('persona', ''),
                json.dumps(profile, ensure_ascii=False),
            ])
            self.assertNotRegex(combined, r'(?i)(api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)')

    def test_protocol_note_frontmatter_links_index_and_log(self):
        self.assertTrue(NOTE_PATH.is_file())
        match = re.match(r'^---\n(.*?)\n---\n', self.note, flags=re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        for field in ('id:', 'title:', 'type: procedure', 'status: active', 'created:', 'updated:', 'tags:', 'source_refs:'):
            self.assertIn(field, frontmatter)
        for link in (
            '[[10-Wiki/SCHEMA]]',
            '[[10-Wiki/concepts/LLM Wiki Obsidian Architecture]]',
            '[[00-Hermes/Memory Index]]',
            '[[02-Agents/Team Overview]]',
            '[[01-Projects/Mission Control/Overview]]',
        ):
            self.assertIn(link, self.note)
        for phrase in (
            'Before durable work: retrieve context',
            'Source fact:',
            'Local system fact:',
            'Inference:',
            'Decision:',
            'POST /api/obsidian/ingest',
            'explicit approval',
            'OpenCode remains an executor worker',
        ):
            self.assertIn(phrase, self.note)
        self.assertIn('[[10-Wiki/concepts/Agent Knowledge Workflow]]', self.index)
        self.assertIn('## [2026-09-30] create | Agent Knowledge Workflow', self.log)


if __name__ == '__main__':
    unittest.main()
