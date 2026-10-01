# Workflow and Obsidian readiness gate

This gate is configuration and bounded filesystem readiness only. It does not activate an agent, autonomy, cron, scheduler, model, provider, or external write.

## Workflow selection

`workflows.json` remains capability-based and owner-editable. Stage selection may narrow capability candidates with validated `metadata_filters`; ordinary stages do not require `candidate_agent_ids`.

- Lead intake and owner approval/review stages use `metadata_filters.runtime_mode: lead`.
- Coding planning and verification use `metadata_filters.runtime_mode: planner`.
- The OpenCode stage remains executor-only through `executor_ref: executor:opencode` and has no roster runtime identity.
- Content research requires `content-research`; generic document research continues to require `research`.
- Route preview is deterministic and configuration-only: `execution.launched=false` and `execution.external_writes=false`.

## Private namespace slice

The owner-approved initialization slice is exactly:

- `hermes-lead`
- `document-knowledge`
- `social-research-trends`
- `content-planner-copywriter`

`POST /api/obsidian/agent-workspaces/initialize` is mounted under the existing owner session and CSRF-protected `/api` router. It creates only a minimal `README.md` marker under the selected namespace, uses atomic filesystem writes, reads back the result, and is idempotent. Existing approved markers are preserved rather than overwritten.

The runtime/owner ACL is not derived from directory existence. It is resolved from current roster membership plus both `obsidian` and `llm-wiki` skills; OpenCode and legacy IDs are excluded. The approved namespace slice is narrower than the skill-derived ACL: backend/data and frontend/product UI are not initialized in this gate, and Agent Engineer is not granted knowledge access merely because a legacy directory exists.

Private writes remain proposal-only. `MEMORY.md`, `USER.md`, accepted wiki pages, shared `10-Wiki`, unrelated namespaces, and legacy markers are not modified by initialization.

## Readiness vocabulary

| State | Meaning | This gate |
|---|---|---|
| Drive workspace ready | Persisted Drive folder metadata read back | Existing metadata only |
| Obsidian namespace ready | Approved private directory and marker read back | Four selected namespaces |
| Runtime-ready | Bounded runtime adapter is configured for execution | `false` |
| Approved | Human approval boundary permits the next action | Workflow gates remain required |
| Live | Agent process/session is active | `false`; all roster `active=false` |
