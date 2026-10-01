# Mission Control Dashboard UI Audit

**Audit date:** 2026-10-01 (UTC)
**Target:** `https://agent.demadigitalasia.com`
**Scope:** usability/navigation, visual polish and hierarchy, responsive behavior, accessibility, design consistency, interaction feedback, information architecture/content clarity, public routing, served bundle/cache behavior, and static/source review of the authenticated dashboard.
**Status:** PARTIALLY_COMPLETE

## Executive summary

The public shell is stable and visually coherent: the login card is centered, responsive, and free of horizontal overflow at all requested viewport widths. The public route matrix and served bundle are healthy, and no browser-side errors were observed during unauthenticated navigation.

Authenticated owner access was not available: the browser vault contained no saved login and no existing authenticated browser session was present. Therefore Team, Routing, Models, Skills & Memory, Knowledge Base/Obsidian, Visual Office, Kanban, Documents, Schedule, Activity, Coolify, and authenticated modal/form flows were audited from the current React/CSS/build source rather than exercised against live owner data. No credentials were requested, entered, printed, or stored.

The highest-value improvements are shared accessibility primitives for dialogs/drawers, reliable live announcements for async states, keyboard access for Visual Office characters, and a more structured Routing editor. The main polish defects found in source/build are missing refresh animation styling and status chips that do not map their tone to the defined badge styles.

## Weighted score

| Dimension | Weight | Score | Rationale |
|---|---:|---:|---|
| Usability / navigation | 20 | 15 | Grouped navigation is understandable and mobile drawer behavior is designed, but tabs are local React state with no deep links/history and several owner flows remain unverified live. |
| Visual hierarchy / layout | 20 | 16 | Strong dark-card system, responsive grids, and clear status blocks; desktop content lacks a page-level heading and some metadata is too small/faint. |
| Responsiveness | 15 | 13 | Public login verified at 1440, 1024, 768, and 390 widths with no overflow; authenticated grids/modals were source-reviewed but not live-exercised. |
| Accessibility | 15 | 9 | Good `aria-label` coverage, focus-visible CSS, dialog roles, and mobile drawer semantics; modal focus trapping/restoration, live announcements, tab semantics, and SVG keyboard access are incomplete. |
| Consistency / design system | 10 | 7 | Reusable cards, buttons, badges, chips, and icons are present; status-tone class mismatch and mixed language/label conventions reduce consistency. |
| Interaction / feedback | 10 | 7 | Loading/empty/error states and most busy labels exist; some refresh controls do not animate, destructive confirmations are inconsistent, and session-expiry handling is uneven. |
| Information architecture / content clarity | 10 | 8 | Workspace/Agents/Infra grouping and explicit real/unknown/offline states are good; raw JSON routing, nested workspace concepts, mixed labels, and absent desktop page headings add cognitive load. |
| **Total** | **100** | **75** | **Good foundation with several cross-cutting accessibility and interaction fixes needed.** |

## Test evidence

### Public live browser checks

- Login shell loaded successfully at all requested widths:
  - `1440x900`: card `380px` wide, controls `322px` wide, no overflow.
  - `1024x768`: card `380px` wide, controls `322px` wide, no overflow.
  - `768x900`: card `380px` wide, controls `322px` wide, no overflow.
  - `390x844`: card at `x=16`, width `358px`; controls `300px`; no overflow.
- At each viewport, `document.documentElement.scrollWidth === innerWidth` and body width matched the viewport.
- Blank login submission produced `Username dan password wajib diisi.` without a network request; the error is visible but is not exposed as `role="alert"` or `aria-live`.
- Keyboard navigation on the login form reached Password → Masuk → document body → Username. Focus-visible styling resolved to a 2px sky outline plus 3px focus ring after keyboard navigation.
- Instrumented `window.onerror`, `unhandledrejection`, and `console.error`; no browser errors were captured during login, public 401 responses, or SPA fallback navigation.
- Public route behavior:
  - `/healthz` → HTTP 200, `{"status":"ok"}`.
  - `/auth/session` → HTTP 401 JSON unauthorized.
  - `/api/overview` → HTTP 401 JSON unauthorized.
  - `/nonexistent-panel` → HTTP 200 SPA/login shell.

### Served bundle / cache checks

- Live index served `/assets/index-Db3vdZS2.js` and `/assets/index-CoM_4f-a.css`.
- Served JS and local `/opt/data/mission-control/dist/assets/index-Db3vdZS2.js` were byte-identical: 324,752 bytes, SHA-256 prefix `c97fd02f46ae7e09`.
- Served CSS and local `/opt/data/mission-control/dist/assets/index-CoM_4f-a.css` were byte-identical: 32,238 bytes, SHA-256 prefix `926fae5e841ec70f`.
- `index.html` and non-asset responses use `Cache-Control: no-cache`; hashed assets use `public, max-age=31536000, immutable`. No served-bundle/cache mismatch was found.
- The frontend build was not rerun because the task prohibits application/build writes; the existing served bundle was compared directly with the current local `dist/` artifact.

### Source evidence reviewed

- `/opt/data/mission-control/frontend/src/App.jsx`
- `/opt/data/mission-control/frontend/src/index.css`
- `/opt/data/mission-control/frontend/index.html`
- `/opt/data/mission-control/frontend/package.json`
- `/opt/data/mission-control/dist/index.html`
- `/opt/data/mission-control/dist/assets/index-Db3vdZS2.js`
- `/opt/data/mission-control/dist/assets/index-CoM_4f-a.css`
- `/opt/data/mission-control/server.py`

## Findings

### MC-UI-001 — Dialogs do not trap or restore keyboard focus

- **Severity:** High
- **Category:** Accessibility / interaction quality
- **Affected areas:** Agent create/edit, persona/governance detail, task completion, memory/skill viewers and editors.
- **Observed evidence:** `App.jsx:1304-1322`, `1678-1695`, `2070-2121`, and shared `ManagedModal` at `2194-2215` render `role="dialog" aria-modal="true"` and support Escape, but do not trap Tab focus, mark the background inert, move focus to a dialog heading/control, or restore focus to the invoking control after close. Only the task-completion textarea uses `autoFocus`.
- **Expected behavior:** Opening a modal should move focus into it; Tab/Shift+Tab should remain inside; Escape/close should return focus to the trigger; background controls should be unavailable to keyboard and assistive-technology users.
- **Recommendation:** Introduce one tested dialog primitive with focus trap, initial-focus target, focus restoration, `aria-labelledby`, and inert/hidden background handling. Reuse it for every modal.
- **Effort:** M

### MC-UI-002 — Mobile drawer lacks a complete focus boundary and focus restoration

- **Severity:** High
- **Category:** Accessibility / mobile navigation
- **Observed evidence:** `App.jsx:4368-4386` locks body scroll, closes on Escape, and focuses the first drawer button after 60ms. `App.jsx:4451-4496` defines the drawer as a dialog, but there is no Tab focus trap and no focus restoration to the hamburger after closing. The backdrop is `aria-hidden`, but the underlying main content is not made inert.
- **Expected behavior:** Mobile navigation should behave as a modal drawer: focus stays inside until close, focus returns to the hamburger, and background content is not reachable while open.
- **Recommendation:** Share the dialog focus-management primitive with the drawer; add a regression test for Tab/Shift+Tab, Escape, backdrop click, and trigger restoration at 390px.
- **Effort:** S-M

### MC-UI-003 — Async status and error messages are not consistently announced

- **Severity:** Medium
- **Category:** Accessibility / feedback
- **Observed evidence:** Login error at `App.jsx:4613`, Team feedback at `844`, Coolify feedback at `1495-1497`, Kanban feedback at `1929-1931`, Agent form error at `1323`, and task completion error at `2099` render visual text without `role="alert"` or `aria-live`. Other panels use `role="status"` inconsistently.
- **Expected behavior:** Screen-reader users should hear validation, save, refresh, deploy, and failure outcomes without needing to re-scan the page.
- **Recommendation:** Standardize `StatusMessage` components: `role="alert"` for blocking/error feedback and `role="status" aria-live="polite"` for success/progress. Associate field-level validation with `aria-describedby`.
- **Effort:** S

### MC-UI-004 — Visual Office characters are mouse-only interactive SVG groups

- **Severity:** Medium
- **Category:** Accessibility / interaction quality
- **Observed evidence:** `PixelSprite` at `App.jsx:2558-2576` renders `<g role="button" aria-label={title}>` with an `onClick`, but no `tabIndex`, `onKeyDown`, or focus styling.
- **Expected behavior:** Every selectable agent in Visual Office should be reachable and activatable by keyboard and expose a visible focus state.
- **Recommendation:** Render each character as a keyboard-capable SVG group (`tabIndex=0`, Enter/Space handlers, focus ring) or provide a parallel accessible list of agents below the graphic.
- **Effort:** S

### MC-UI-005 — Team status chips do not use the defined tone styles

- **Severity:** Medium
- **Category:** Visual consistency / status clarity
- **Observed evidence:** Team cards append a raw tone string to `mc-chip` at `App.jsx:877-879`: `className={`mc-chip ... ${tone}`}` where `tone` is `ok`, `info`, `warn`, or `neutral`. The CSS defines `mc-badge-ok`, `mc-badge-info`, `mc-badge-warn`, and `mc-badge-neutral` at `index.css:39-66`, but no exact `.ok`, `.info`, `.warn`, or `.neutral` chip rules. The served CSS therefore does not map these raw tone classes to the intended status colors.
- **Expected behavior:** Running, Standby, Unknown, and Offline should have deliberate, consistent color treatment with the rest of the dashboard.
- **Recommendation:** Replace the raw chip class with the shared `Badge` component or map tone to the existing `mc-badge-*` classes. Keep the status dot as a secondary cue, not the only cue.
- **Effort:** S

### MC-UI-006 — Several refresh icons do not animate while work is in progress

- **Severity:** Medium
- **Category:** Interaction feedback / design system
- **Observed evidence:** Models refresh at `App.jsx:4068-4076`, Inbox refresh at `3751`, and Wiki lint refresh at `3789` use `className="mc-spin"` while busy. The current CSS contains the `@keyframes mc-spin` definition used by `.mc-spinner`, but no exact `.mc-spin` class that applies the animation. Other controls using Tailwind `animate-spin` are separate and work by class name.
- **Expected behavior:** A pressed refresh action should visibly indicate that the request is still running and should settle when complete.
- **Recommendation:** Add a shared `.mc-spin { animation: mc-spin .8s linear infinite; }` utility or use the existing `animate-spin` class consistently; add `aria-busy` to the associated region/button.
- **Effort:** S

### MC-UI-007 — Destructive confirmations are inconsistent and can persist stale state

- **Severity:** Medium
- **Category:** Interaction quality / safety
- **Observed evidence:** Team delete uses an inline second-click state at `App.jsx:898-910`; clicking the backdrop at `890` closes the menu but does not clear `del`, so reopening the same menu can still show `Yakin hapus?`. Memory and skill deletion use native `window.confirm` at `2429` and `2456`, while other destructive actions use in-app controls.
- **Expected behavior:** Destructive actions should have one consistent confirmation pattern, an explicit Cancel path, clear impact text, and no stale confirmation state after dismissal.
- **Recommendation:** Use one in-app destructive-confirmation modal with Cancel, explicit target/impact, loading state, and state reset on close. Avoid mixing native confirm dialogs with app modals.
- **Effort:** M

### MC-UI-008 — Panel selection is not represented in the URL or browser history

- **Severity:** Medium
- **Category:** Usability / navigation / information architecture
- **Observed evidence:** `MissionControlApp` stores the active panel only in `useState("overview")` at `App.jsx:4357-4360`; rendering switches on that local value at `4388-4400`. No route, hash, query parameter, history update, or panel-specific deep link exists.
- **Expected behavior:** Users should be able to bookmark a panel, refresh without losing context, use browser Back/Forward, and share a direct link to a specific dashboard area.
- **Recommendation:** Encode the tab in a query/hash or lightweight client router, validate unknown keys, and preserve the existing SPA fallback. Update document title and a page-level heading from the active panel.
- **Effort:** M

### MC-UI-009 — Routing editor is a raw JSON control plane with weak authoring support

- **Severity:** Medium
- **Category:** Usability / content clarity
- **Observed evidence:** `App.jsx:4281-4287` exposes durable workflow configuration and agent metadata as two raw `textarea` JSON documents. Save only parses JSON in `4221-4239`; there is no schema-aware field editor, line/field error location, dirty-state indicator, diff, inline help, or restore affordance in the UI.
- **Expected behavior:** Owner configuration should make valid edits discoverable and invalid edits recoverable, especially for capabilities, approval gates, runtime modes, and agent metadata.
- **Recommendation:** Add structured sections for workflow/stage/capability/approval fields, or wrap the JSON editor with formatting, schema validation, line-level errors, dirty-state warning, diff/readback, and a visible restore-from-backup action.
- **Effort:** L

### MC-UI-010 — Small faint metadata text is below normal-text contrast target

- **Severity:** Medium
- **Category:** Accessibility / visual polish
- **Observed evidence:** Tailwind config sets `mc.faint` to `#71717a`; the same color is used by `mc-footnote` and `mc-section-label` in `index.css:171-173` and `191-193`, often at 10–11px. Calculated contrast against `mc.card #18181b` is approximately 3.67:1, below the 4.5:1 WCAG AA target for normal text.
- **Expected behavior:** Secondary metadata remains readable in dark mode at its rendered size, including timestamps, source notes, status explanations, and footnotes.
- **Recommendation:** Lighten `mc.faint` or reserve it for larger text; use a higher-contrast secondary color for 10–12px text and verify with automated contrast checks.
- **Effort:** S

### MC-UI-011 — Login fields rely on placeholders instead of visible labels

- **Severity:** Low
- **Category:** Usability / accessibility
- **Observed evidence:** The public DOM exposes two inputs with `aria-label` and placeholders (`Username`, `Password`) but no `<label>` elements, matching `App.jsx:4587-4604`.
- **Expected behavior:** Field identity should remain visible after typing and be understandable in zoomed, translated, or autofill states.
- **Recommendation:** Add persistent visible labels, retain `autocomplete`, and connect validation text with `aria-describedby`.
- **Effort:** S

### MC-UI-012 — Mixed terminology and no desktop page-level heading reduce orientation

- **Severity:** Low
- **Category:** Information architecture / content clarity
- **Observed evidence:** Navigation labels mix English and Indonesian (`Workspace`, `Agents`, `Infra`, `Team`, `Models`, `Skills & Memory`, `Chat Logs`) at `App.jsx:4313-4339`, while panels use alternate names such as `Activity`, `Calendar`, and `Knowledge Base — Obsidian`. On desktop the content area begins with cards; the only persistent context is the sidebar footer `Panel: {activeLabel}` at `4431-4443`.
- **Expected behavior:** A stable page heading and a consistent glossary should make the active area obvious without comparing multiple labels.
- **Recommendation:** Choose one language policy, normalize menu/panel names (`Chat Logs` vs `Activity`, `Schedule` vs `Calendar`), and render an `h1` for the active panel in the content area.
- **Effort:** S

### MC-UI-013 — Session-expiry recovery is inconsistent for direct actions

- **Severity:** Medium
- **Category:** Interaction quality / reliability feedback
- **Observed evidence:** Several direct-action error handlers do not call `notifyUnauthorized`: Team roster load/action paths at `App.jsx:777`, `792-795`, and `819-821`; Agent form save at `1292-1295`; Coolify load/deploy at `1441` and `1467-1469`. `usePolling` does call it at `200-212`, so a later poll may recover, but an expired-session click can first leave an in-panel `unauthorized` error instead of returning to login.
- **Expected behavior:** Any 401 from any action should consistently transition to the login screen and preserve no ambiguous stale edit state.
- **Recommendation:** Centralize API error handling or ensure every catch path calls the same auth-expiry handler before rendering local errors.
- **Effort:** S

## Prioritized recommendations

1. **P1 — Build a shared accessible dialog/drawer primitive.** Add focus trap, initial focus, focus restoration, inert background, labelled headings, and keyboard regression coverage. This addresses MC-UI-001 and MC-UI-002 across the largest set of owner workflows.
2. **P1 — Standardize live feedback.** Create shared `StatusMessage`, `Loading`, and `Unavailable` primitives with appropriate `role`, `aria-live`, `aria-busy`, and field associations. Address MC-UI-003 and part of MC-UI-013.
3. **P1 — Make Visual Office keyboard-accessible.** Add keyboard activation and focus states to character selection, or provide an equivalent accessible list. Address MC-UI-004.
4. **P1 — Replace raw destructive confirmation patterns.** Use one in-app confirmation modal with Cancel and reset-on-close behavior for Team, memory, skills, and Coolify. Address MC-UI-007.
5. **P2 — Fix design-system class mapping and refresh feedback.** Map Team tone values to existing Badge styles and replace/add the missing `mc-spin` utility. Address MC-UI-005 and MC-UI-006.
6. **P2 — Add panel deep links and page context.** Encode active panel in the URL/history, render a content `h1`, and normalize terminology. Address MC-UI-008 and MC-UI-012.
7. **P2 — Improve Routing authoring.** Move from raw JSON-only editing toward a schema-aware form or add formatter, field-level errors, dirty-state protection, diff, and readback. Address MC-UI-009.
8. **P2 — Raise dark-theme secondary-text contrast.** Adjust `mc.faint` usage/color and verify at the actual 10–12px sizes. Address MC-UI-010.
9. **P3 — Improve login field affordance.** Add persistent labels and accessible validation association. Address MC-UI-011.

## What was not verified live

- No authenticated owner session or saved vault login was available; no credentials were requested or entered.
- Live owner flows were not clicked: Team roster CRUD, governance/persona editor, Routing save/preview, Models catalog, Skills & Memory CRUD, Knowledge Base/Obsidian search/write/approval/lint, Visual Office selection, Kanban create/complete/export, Documents/agent workspace, Schedule data, Activity feed, Coolify redeploy, and authenticated error/empty/loading states.
- Authenticated console/network behavior, modal focus behavior, mobile drawer behavior, authenticated overflow, and real dependency latency were source-reviewed rather than runtime-verified.
- No screenshot artifacts were created. DOM, HTTP, bundle, CSS, and source evidence were used instead, honoring the constraint that the only requested write artifact is this report.
- The repository had pre-existing uncommitted changes before this audit, including frontend/source and `dist/` changes. This audit did not modify application source, configuration, roster, workflows, cron, runtime, or deployment, and did not rerun the build because a rebuild would write application build artifacts.
