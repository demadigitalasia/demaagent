import json
import re
import unittest
from pathlib import Path


ROSTER_PATH = Path('/opt/data/mission-control/agents.json')
VAULT = Path('/opt/data/obsidian-vault')
NOTE_PATH = VAULT / '10-Wiki/concepts/Agent Knowledge Workflow.md'
INDEX_PATH = VAULT / '10-Wiki/index.md'
LOG_PATH = VAULT / '10-Wiki/log.md'
TARGET_IDS = {
    'hermes-lead',
    'agent-engineer',
    'agent-socmed',
    'news-agent',
    'sub-agent-back-end',
    'sub-agent-devops',
    'sub-agent-front-end',
    'sub-agent-ui-ux',
}
PROTOCOL_MARKER = 'KNOWLEDGE WORKFLOW PROTOCOL'


class TestPhase3AgentKnowledgeWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = json.loads(ROSTER_PATH.read_text(encoding='utf-8'))
        cls.by_id = {agent['id']: agent for agent in cls.roster}
        cls.note = NOTE_PATH.read_text(encoding='utf-8')
        cls.index = INDEX_PATH.read_text(encoding='utf-8')
        cls.log = LOG_PATH.read_text(encoding='utf-8')

    def test_eight_agents_have_unique_knowledge_skills_and_opencode_is_executor_only(self):
        self.assertEqual(len(self.roster), 11)
        self.assertEqual(set(self.by_id), TARGET_IDS | {'opencode', 'dema-assistant', 'dema-lead'})
        for agent_id in TARGET_IDS:
            agent = self.by_id[agent_id]
            skills = agent.get('skills', [])
            self.assertEqual(len(skills), len(set(skills)), agent_id)
            self.assertEqual(skills.count('obsidian'), 1, agent_id)
            self.assertEqual(skills.count('llm-wiki'), 1, agent_id)
            self.assertIn(PROTOCOL_MARKER, agent.get('persona', ''), agent_id)
        opencode = self.by_id['opencode']
        self.assertEqual(opencode.get('skills'), ['opencode'])
        self.assertNotIn('obsidian', opencode.get('skills', []))
        self.assertNotIn('llm-wiki', opencode.get('skills', []))
        self.assertNotIn(PROTOCOL_MARKER, opencode.get('persona', ''))

    def test_persona_profiles_separate_retrieval_proposal_approval_and_core_memory(self):
        required_persona_terms = (
            '10-Wiki/index.md',
            'authenticated reviewed ingestion',
            'approval eksplisit',
            'accepted wiki pages',
            'MEMORY.md/USER.md',
            'OpenCode',
        )
        for agent_id in TARGET_IDS:
            agent = self.by_id[agent_id]
            combined = '\n'.join([
                agent.get('persona', ''),
                json.dumps(agent.get('persona_profile', {}), ensure_ascii=False),
            ])
            for term in required_persona_terms:
                self.assertIn(term, combined, f'{agent_id}: {term}')

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
