# Mission Control Dashboard UI Audit — R2

- **Audit date:** 2026-10-01 UTC
- **Target:** `https://agent.demadigitalasia.com`
- **Repository reviewed:** `/opt/data/mission-control`
- **Status:** `PARTIALLY_COMPLETE`
- **Scope:** public live shell, routing/auth/cache behavior, console/runtime errors, responsive widths, keyboard paths, current frontend source/build review for all named panels and owner flows.

## Executive summary

The remediation is present in the current source and served bundle. The public shell is healthy at all requested widths, anonymous protected routes return JSON `401`, SPA fallback works, security headers are present, the served JS/CSS assets exactly match the current local `dist/` files, and a fresh browser navigation produced no captured runtime or console errors.

The remediation fixed the previous cross-cutting dialog/drawer focus defects, added focus restoration and background inerting, made Visual Office sprites keyboard-operable, added URL/history panel navigation and a page-level heading, fixed the Team status badge mapping, added the missing `mc-spin` utility, raised the faint-text token, added persistent login labels, and replaced several native/in-line destructive confirmations with shared modal primitives.

The remaining quality risk is concentrated in owner-only flows that could not be exercised live because no authenticated browser/vault session was available. Source review still finds incomplete feedback semantics in several ad-hoc error/success nodes, inconsistent session-expiry recovery for direct mutations, a Coolify status-chip design-system regression, raw JSON authoring in Routing, a preview affordance that does not communicate that it uses persisted rather than unsaved routing state, a misleading legacy skill-library fallback, incomplete ARIA tab semantics, and a mobile Visual Office canvas that deliberately requires internal horizontal scrolling. Blank login validation now falls through to browser-native English validation instead of the app's localized feedback path; this is a small regression from the prior audit.

No application source, configuration, roster, workflows, cron, runtime, deployment, data, or build artifacts were changed. The only requested artifact created by this audit is this report.

## Weighted score

| Dimension | Weight | Score | Rationale |
|---|---:|---:|---|
| Usability / navigation | 20 | 17 | Grouped navigation, mobile drawer, page heading, panel query parameter, and browser history are now present. Routing remains JSON-first and owner flows were not live-exercised. |
| Visual hierarchy / layout | 20 | 17 | Dark card hierarchy, status blocks, headings, responsive grids, and modal sizing are coherent. Some metadata remains dense/faint and Visual Office is a fixed-width canvas inside a scroll region. |
| Responsiveness | 15 | 13 | Public login was live-checked at 1440, 1024, 768, and 390 widths with no document overflow. Authenticated layouts are source-reviewed; the Office canvas intentionally has a 560px minimum width. |
| Accessibility | 15 | 12 | Shared modal focus trap/restoration/inerting, visible labels, live feedback primitives, and keyboard-capable sprites are improvements. Ad-hoc messages and ARIA tab semantics remain incomplete; login native validation is not localized. |
| Design-system consistency | 10 | 8 | Shared Badge/Modal/Feedback primitives are used broadly and Team status mapping is fixed. Coolify still attaches raw `ok/warn/bad` classes to `mc-chip`; terminology and status treatment are not fully uniform. |
| Interaction feedback / safety | 10 | 8 | Busy states, readback for governance edits, dirty-routing protection, CSRF client support, and shared confirmations are present. Coolify has no explicit Cancel state, and direct mutation 401 handling is inconsistent. |
| Information architecture / content clarity | 10 | 8 | The panel taxonomy and page context are clearer. Routing remains raw JSON, persisted-vs-draft preview state is not explicit, and the legacy skill fallback can label unknown assignment state as available. |
| **Total** | **100** | **83** | Strong remediation result; remaining issues are mostly Medium/Low and owner-flow verification is incomplete. |

## Live public evidence

### HTTP and routing matrix

All checks were made against the public target on 2026-10-01 UTC.

| Request | Result | Evidence |
|---|---:|---|
| `GET /healthz` | `200` | JSON body `{"status":"ok"}` |
| `GET /auth/session` without cookie | `401` | JSON unauthorized response |
| `GET /api/overview` without cookie | `401` | JSON unauthorized response |
| `GET /api/tasks` without cookie | `401` | JSON unauthorized response |
| `GET /nonexistent-panel` | `200` | SPA `index.html` fallback served |
| `GET /?panel=agents` | `200` | SPA shell served; panel parameter preserved at HTTP layer |

Observed public response headers included CSP with `style-src 'unsafe-inline'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, HSTS, strict referrer policy, and `Cache-Control: no-cache` for HTML/JSON. The server source also documents and implements `Secure`, `HttpOnly`, `SameSite=Lax` session cookies and a non-HttpOnly CSRF cookie.

### Public responsive checks

The live login shell was navigated and measured at each requested viewport. In each case `document.documentElement.scrollWidth === window.innerWidth` and `document.body.scrollWidth === window.innerWidth`.

| Viewport | Result | DOM evidence |
|---|---|---|
| `1440x900` | Pass | inner `1440x900`, document scroll `1440x900` |
| `1024x768` | Pass | inner `1024x768`, document scroll `1024x768` |
| `768x900` | Pass | inner `768x900`, document scroll `768x900` |
| `390x844` | Pass | inner `390x844`, document scroll `390x844` |

The public DOM exposes visible `Username` and `Password` labels, autocomplete values `username` and `current-password`, and the `Masuk` button. Keyboard traversal reached Password → Masuk → body → Username → Password. Focus-visible styles are present in `index.css:108-118`.

### Console/runtime and cache checks

- A fresh navigation to `/nonexistent-panel?audit=console` rendered the login shell with no captured `window.onerror`, `unhandledrejection`, or `console.error` entries.
- Live `index.html` referenced `/assets/index-BeHhXUdD.js` and `/assets/index-BFgr0B0b.css`.
- Served JS: `331443` bytes, SHA-256 `bdf7c4fc49d34a5ff6401895fc08baf7b410b7ea9d724b09052b6a862b5892ff`.
- Local `dist/assets/index-BeHhXUdD.js` matched the served JS byte-for-byte.
- Served CSS: `33021` bytes, SHA-256 `e0c8b39f3f1b0e5764b6b21e69a89c7d53d4c7615183c1f5faa315c03837115f`.
- Local `dist/assets/index-BFgr0B0b.css` matched the served CSS byte-for-byte.
- HTML and JSON responses were `no-cache`; hashed assets were `public, max-age=31536000, immutable`.

No screenshot files were created because the audit constraint allowed only the report artifact to be written. DOM, HTTP, bundle, CSS, and source evidence are recorded instead.

## Authenticated/source review coverage

No authenticated owner session or saved vault login was available. No credentials were requested, entered, printed, or stored. The following were reviewed from current `App.jsx`, `index.css`, `api.js`, `server.py`, `routing.py`, and the current served/local bundle:

- **Team roster:** roster cards, live status, agent creation/edit, persona/governance detail, model/skill selection, activation, deletion, profile readback.
- **Governance/persona editor:** structured ten-field governance editor, required-field validation, persona save, model catalog loading, skill chips, readback comparison.
- **Routing:** durable workflow and agent metadata editors, JSON formatting, dirty-state warning, before-unload protection, route preview, workflow summaries.
- **Models:** merged provider/catalog display, search, empty-provider handling, refresh busy state.
- **Skills & Memory:** memory preview/full-view/edit/append/delete, redaction acknowledgement, skill library search/filter/detail/edit/delete/create, assignment separation.
- **Knowledge Base / Obsidian:** note search, folder filter, note/graph reader, reviewed ingestion, proposal inbox, explicit approval, lint refresh, scoped agent workspace and proposal-only writes.
- **Visual Office:** data-derived states, workspace/lounge room switch, live activity, status sources, keyboard-capable SVG sprites, internal overflow wrapper.
- **Kanban:** create form, status table, JSON/CSV exports, completion modal requiring result evidence, polling refresh.
- **Documents:** global Drive metadata and per-agent workspace selection/read-only listing.
- **Schedule:** calendar empty/error/success states and external links.
- **Activity:** live feed, source status, empty/error states and polling label.
- **Coolify:** status list, health badges, redeploy two-step interaction, refresh, external links.
- **Shared primitives:** `Modal`, `ConfirmModal`, `Feedback`, `Loading`, `Unavailable`, `Badge`, focus-visible CSS, `ErrorBoundary`, CSRF-aware API wrapper.

## Prior-finding recheck

| Prior ID | Current status | Evidence |
|---|---|---|
| MC-UI-001 dialogs did not trap/restore focus | **Fixed** | Shared `Modal` in `App.jsx:176-290` moves focus inside, traps Tab/Shift+Tab, sets app shell inert/aria-hidden, locks body scroll, and restores the trigger. Source/bundle verified; not exercised with owner UI. |
| MC-UI-002 mobile drawer focus boundary | **Fixed** | Drawer now reuses `Modal` at `App.jsx:4709-4734`, with `mc-drawer`, `aria-modal`, focus handling, Escape close, body-scroll lock, and hamburger `aria-expanded/aria-controls`. Source verified; not live-auth exercised. |
| MC-UI-003 async feedback not announced | **Partially fixed** | `Feedback`, `Loading`, and `Unavailable` add roles/live regions (`App.jsx:144-170`). Several direct `mc-err`/`mc-ok` nodes remain without roles; see `MC-UI-R2-001`. |
| MC-UI-004 Visual Office sprites mouse-only | **Fixed** | `PixelSprite` has `role=button`, `tabIndex=0`, Enter/Space handling, `aria-pressed`, and focus-ring CSS (`App.jsx:2689-2722`, `index.css:239-247`). |
| MC-UI-005 Team tone class mismatch | **Fixed for Team; residual elsewhere** | Team now uses `Badge` (`App.jsx:1043-1045`). Coolify still has the same raw tone pattern on `mc-chip` (`App.jsx:1637-1640`, `1680`); see `MC-UI-R2-003`. |
| MC-UI-006 missing refresh animation | **Fixed** | `.mc-spin` is defined in `index.css:250-253`; current bundle contains it and refresh controls use it. |
| MC-UI-007 inconsistent/stale destructive confirmation | **Mostly fixed** | Team and memory use `ConfirmModal`; skill delete has explicit in-modal confirmation. Coolify redeploy still uses an irreversible-looking second click without an explicit Cancel control; see `MC-UI-R2-003` and `MC-UI-R2-006`. |
| MC-UI-008 panel state absent from URL/history | **Fixed** | `tabFromLocation`, `writeTabLocation`, `pushState`, and `popstate` are present (`App.jsx:4569-4643`). |
| MC-UI-009 raw JSON Routing editor | **Still present / improved** | Format buttons, parse errors, dirty warning, before-unload, backend validation and backups were added, but both durable control-plane documents remain raw textareas (`App.jsx:4505-4515`). |
| MC-UI-010 faint dark-theme text contrast | **Fixed in source** | `.text-mc-faint` overrides the former dim token with `#a1a1aa` (`index.css:256-260`). |
| MC-UI-011 login fields used only placeholders | **Fixed** | Visible labels and autocomplete are present (`App.jsx:4835-4859`). Native missing-field validation regression is tracked below. |
| MC-UI-013 inconsistent 401 recovery | **Partially fixed** | Polling and many read paths call `notifyUnauthorized`; several direct mutation catches still only render local errors (`App.jsx:954-958`, `1465-1467`, `1627-1629`). |

## Current findings

### MC-UI-R2-001 — Feedback semantics remain inconsistent outside shared primitives

- **Severity:** Medium
- **Category:** Accessibility / interaction feedback
- **Evidence:** Source. `Feedback` is correct at `App.jsx:144-154`, but direct messages remain unannounced or use the wrong role: overview/gateway and database errors at `538` and `551`, model-form load error at `1539`, Visual Office gateway error at `3347`, workspace detail error at `3474`, the already-processed lint success at `3924`, the ErrorBoundary message at `4136`, and several `mc-ok` lint/status nodes at `3940` have no live-region role. Obsidian error messages at `3475`, `3799`, `3872`, and `3925` use `role="status"` for both success and error, which is polite rather than assertive.
- **Expected behavior:** Every blocking/error outcome should be exposed as `role="alert"`/assertive; progress and success should use `role="status" aria-live="polite"`; messages should not depend on visual rescanning.
- **Recommendation:** Route all async outcomes through `Feedback`, `Loading`, `Unavailable`, or a shared field-message primitive. Use `aria-busy` on the affected region, not only on individual controls.
- **Effort:** S-M
- **Fixed/regression status:** Partial fix of MC-UI-003; residual cross-panel inconsistency remains.

### MC-UI-R2-002 — Direct mutation 401s do not consistently return to login

- **Severity:** Medium
- **Category:** Reliability / session recovery
- **Evidence:** Source. `apiFetch` raises `AuthError` on any `401` (`frontend/src/api.js:49-53`). Read/poll paths call `notifyUnauthorized`, but roster patch (`App.jsx:947-959`), agent form save (`1447-1467`), and Coolify deploy (`1606-1629`) catch errors without calling it. An expired session can therefore leave a local error in an owner panel instead of returning to the login screen; a later poll may recover only indirectly.
- **Expected behavior:** Every authenticated request that receives `401` should transition to the login screen and clear or preserve draft state intentionally.
- **Recommendation:** Centralize `safeFetchJSON` error handling or add `notifyUnauthorized(e)` to every direct-action catch before rendering local feedback. Add an explicit regression test for expired-session create/edit/delete/deploy paths.
- **Effort:** S
- **Fixed/regression status:** Partial fix of MC-UI-013.

### MC-UI-R2-003 — Coolify status chips still bypass the Badge design system

- **Severity:** Medium
- **Category:** Design-system consistency / status clarity
- **Evidence:** Source. `statusTone` returns `ok`, `warn`, or `bad` at `App.jsx:1637-1639`, then Coolify renders `className={`mc-chip text-[10.5px] ${statusTone(a.status)}`}` at `1680`. `index.css:68-71` defines only the neutral `mc-chip`; the exact `.ok`, `.warn`, and `.bad` chip selectors do not exist. Team was fixed to use `Badge`, but Coolify retains the residual raw-class defect.
- **Expected behavior:** Healthy/degraded/down statuses use the same deliberate tone mapping as every other status badge and remain understandable without relying on a dot or color alone.
- **Recommendation:** Render `Badge tone={statusTone(a.status)}` or map the class to `mc-badge-*`. Keep the status text and healthcheck label as redundant cues.
- **Effort:** S
- **Fixed/regression status:** Residual/new surface of prior MC-UI-005; not a regression in Team.

### MC-UI-R2-004 — Routing preview does not state that it uses persisted configuration

- **Severity:** Medium
- **Category:** Information architecture / owner safety
- **Evidence:** Source/inference. The Routing editor tracks draft `configText` and `metadataText` (`App.jsx:4339-4351`), but `runPreview` posts only `task_text` and `capability_hints` (`4462-4474`); it does not include either draft document. The UI labels the card `Route preview / simulation` and shows `unsaved changes`, but does not say that preview uses the last persisted backend configuration. The backend routing module defines preview over a supplied validated config, so the frontend request path is the only visible source of configuration for this control.
- **Expected behavior:** Preview should either evaluate the current draft, or explicitly say “preview persisted config” and disable/guard preview while drafts are unsaved.
- **Recommendation:** Add a draft payload and server-side validation for draft preview, or label the action as persisted-config preview and require save/discard before running it. Display the config revision/timestamp used.
- **Effort:** M
- **Fixed/regression status:** New residual discovered in the Routing remediation review.

### MC-UI-R2-005 — Legacy skill-library fallback labels unknown assignment state as available

- **Severity:** Medium
- **Category:** Content clarity / state integrity
- **Evidence:** Source. When `/api/skill-library` is unavailable, `SkillLibraryBlock` falls back to legacy skills and maps each row with `assigned_count: null` and `assigned_agents: []` at `App.jsx:2430-2436`. The same component then computes `assigned = Number(s.assigned_count || 0) > 0` at `2440` and displays `tersedia` for unassigned rows at `2462-2463`. The heading does show `Library tidak tersedia`, but the row-level status still presents an unknown as available.
- **Expected behavior:** If assignment metadata is unavailable, the row should say `status assignment tidak tersedia` or omit the assigned/available filter result rather than claim availability.
- **Recommendation:** Carry an explicit `assignment_status: "unknown"` in the fallback model and render a neutral/unknown badge; disable assignment filtering while metadata is unavailable.
- **Effort:** S
- **Fixed/regression status:** New residual discovered in the current source review.

### MC-UI-R2-006 — Coolify redeploy has confirmation but no explicit Cancel state

- **Severity:** Medium
- **Category:** Interaction feedback / destructive-action safety
- **Evidence:** Source. Coolify toggles the same button from `redeploy` to `yakin redeploy?` and sends the POST on the second click (`App.jsx:1704-1726`). There is no separate Cancel button or Escape/backdrop path for that confirmation state; the user must navigate away or reload to abandon it. The error path also does not call `notifyUnauthorized` (`1627-1629`).
- **Expected behavior:** High-impact redeploy should have an explicit confirmation surface with target name, impact, Cancel, confirm, disabled/busy, success/error, and session-expiry handling.
- **Recommendation:** Use the shared confirmation modal (or add a visible Cancel action) and centralize 401 handling. Preserve the selected target in the confirmation copy.
- **Effort:** S-M
- **Fixed/regression status:** Residual of MC-UI-007; Team/memory/skill confirmation patterns are better.

### MC-UI-R2-007 — ARIA tab semantics are incomplete for navigation and Visual Office rooms

- **Severity:** Low
- **Category:** Accessibility
- **Evidence:** Source. Main navigation uses `role="tablist"` and buttons with `role="tab" aria-selected` at `App.jsx:4671-4681` and `4722-4723`, but the tabs do not expose `aria-controls`, there is no corresponding `tabpanel`, and no managed roving `tabIndex`. Visual Office room buttons use `role="tab" aria-selected` at `3219-3225` without a tablist or controlled panel relationship.
- **Expected behavior:** Use native buttons without tab roles, or implement the complete ARIA tabs pattern with controlled panels and keyboard arrow behavior.
- **Recommendation:** Prefer native button navigation for the sidebar, or add `aria-controls`, `tabpanel`, and arrow-key behavior consistently. For rooms, wrap the controls in a tablist and expose the SVG region as the controlled panel.
- **Effort:** S-M
- **Fixed/regression status:** New accessibility residual; focus and selection visuals are present.

### MC-UI-R2-008 — Visual Office remains a 560px-minimum canvas on narrow screens

- **Severity:** Low
- **Category:** Responsiveness / long-narrow content
- **Evidence:** Source. `VisualOfficeSVG` sets `minWidth: "560px"` at `App.jsx:3094-3100`, with an `overflowX: "auto"` wrapper at `3236-3238`. This prevents document-level overflow but forces horizontal scrolling inside the card at 390px and below.
- **Expected behavior:** The visual should either scale to the available width, provide a clearly labelled horizontal canvas viewport, or offer a compact list alternative for narrow screens.
- **Recommendation:** Keep the scrollable canvas if pixel fidelity is required, but add a visible “geser horizontal untuk melihat ruangan” affordance and an accessible agent list/detail alternative below it. Consider a responsive compact SVG viewBox.
- **Effort:** M
- **Fixed/regression status:** Not a regression; the current wrapper is safer than page-level overflow but remains a mobile usability trade-off.

### MC-UI-R2-009 — Blank login submission bypasses localized app feedback

- **Severity:** Low
- **Category:** Login usability / accessibility / content consistency
- **Evidence:** Live + source. The live form inputs are `required` and, when `Masuk` is clicked blank, the browser prevents React `handleSubmit` from running; no `[role=alert]` node appears. The browser DOM reports native `validationMessage: "Please fill out this field."` in the audit browser. Source has the custom Indonesian error branch at `App.jsx:4797-4803`, but it is unreachable for missing required fields; fields also do not set `aria-invalid`.
- **Expected behavior:** Missing credentials should show a localized inline message associated with the relevant fields, while retaining native form semantics if desired.
- **Recommendation:** Either remove `required` and handle validation consistently in React, or add `onInvalid`/custom validity and `aria-invalid`/`aria-describedby` per field. Keep the visible Indonesian message and prevent any network request.
- **Effort:** S
- **Fixed/regression status:** Regression relative to the prior audit's observed Indonesian blank-submit message; persistent labels themselves are fixed.

## Prioritized recommendations

### P1 — Reliability and owner safety

1. Centralize `401` handling for every `safeFetchJSON` call, including roster PATCH, agent save, memory/skill mutations, Coolify deploy, and knowledge writes.
2. Replace Coolify's second-click redeploy with the shared confirmation primitive and explicit Cancel.
3. Finish the shared live-feedback primitive rollout so every blocking/error message is announced correctly and every busy data region exposes `aria-busy`.

### P2 — Authoring clarity and state integrity

1. Make Routing preview clearly draft-aware: preview the draft with validation or explicitly preview persisted config and block/label when unsaved.
2. Keep the raw JSON escape hatch, but add schema-aware field sections, line/field errors, diff/readback, revision/timestamp, and a visible discard/restore action.
3. Fix the skill-library fallback to represent unknown assignment state rather than `tersedia`.
4. Map Coolify statuses through `Badge` and normalize remaining status/terminology patterns.

### P3 — Accessibility and responsive polish

1. Simplify navigation to native buttons or complete the ARIA tabs pattern.
2. Add localized login invalid-field feedback and `aria-invalid`.
3. Add a narrow-screen Visual Office list/detail alternative or explicit canvas-scroll affordance.

## What was verified

- Public live shell rendered at `1440x900`, `1024x768`, `768x900`, and `390x844` with no document horizontal overflow.
- Public login labels, autocomplete attributes, keyboard focus traversal, and focus-visible CSS.
- Fresh browser navigation to SPA fallback with zero captured runtime errors, unhandled rejections, or console errors.
- `/healthz` `200`; anonymous `/auth/session`, `/api/overview`, and `/api/tasks` `401` JSON behavior.
- SPA fallback `200` for an unknown path and query-preserving HTML delivery.
- Current served JS/CSS asset names, byte counts, SHA-256 hashes, and byte equality against local `dist` assets.
- Security headers and cache policy on public responses.
- Current source/build evidence for Team, governance/persona, Routing, Models, Skills & Memory, Knowledge Base/Obsidian, Visual Office, Kanban, Documents, Schedule, Activity, Coolify, modal/drawer primitives, forms, confirmations, and async states.
- Previous remediation markers: shared modal focus logic, drawer reuse, SVG keyboard handlers, URL/history, page heading, Team Badge use, `.mc-spin`, faint-text override, visible login labels, and CSRF-aware API wrapper.

## Not verified live / limitations

- No authenticated owner/vault session was available. No credentials were requested or entered.
- Team CRUD, persona/governance editing, Routing save/preview, Models catalog, Skills & Memory CRUD, Obsidian search/write/approval/lint, Visual Office selection, Kanban create/complete/export, Documents/agent workspaces, Calendar data, Activity data, and Coolify status/redeploy were not clicked against live owner data.
- Authenticated console/network behavior, real polling latency, modal focus trapping in the live owner UI, mobile drawer interaction, authenticated overflow, and session-expiry transitions remain source-only evidence.
- No build was rerun because the audit must not change build artifacts; current `dist` and served bundle were compared directly.
- Existing repository changes outside this report were pre-existing and were not altered by the audit.
- No screenshot artifact exists; evidence is DOM/HTTP/source/bundle based.

## Final status

`PARTIALLY_COMPLETE` — the public shell and remediation artifacts are verified, but owner workflows were not live-tested because an authenticated session was unavailable. The score is **83/100** with no current Critical/High UI defects identified from live public or source evidence; Medium residuals remain in feedback semantics, session recovery, Coolify safety/consistency, Routing authoring/preview clarity, and degraded-state content accuracy.
