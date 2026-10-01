# Mission Control — Aplikasi Mandiri

Dashboard pemantauan + kanban Hermes sebagai aplikasi **berdiri sendiri** (bukan
plugin dashboard Hermes): server FastAPI sendiri di **:9120**, auth sendiri,
frontend React full-bundle, namun **data layer-nya REUSE plugin yang ada** —
tidak ada logika data yang disalin.

## Struktur

```
/opt/data/mission-control/
├── server.py            # FastAPI: auth (cookie sesi 12 jam) + mount router plugin di /api
├── frontend/            # Vite + React standalone (bundle sendiri, tanpa SDK dashboard)
│   └── src/App.jsx      # salinan/adaptasi UI plugin (7 panel + halaman login)
├── dist/                # hasil `vite build` (diserve server.py)
├── uvicorn-log.json     # konfigurasi log uvicorn -> /opt/data/logs/mission-control.log
├── server.pid           # pid proses berjalan (dibuat saat start)
└── README.md
```

Backend meng-import router dari
`/opt/data/plugins/mission-control/dashboard/plugin_api.py` (importlib, path
absolut) dan memount-nya di prefix `/api` → endpoint sama seperti plugin:
`/api/overview`, `/api/agents`, `/api/tasks`, `/api/calendar`, `/api/activity`,
`/api/memory`, `/api/office` + `POST /api/tasks/create` &
`POST /api/tasks/{id}/complete`.

## Auth

- `POST /auth/login` — body `{username, password}`; kredensial dibaca dari env
  `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`
  (sama dengan dashboard Hermes — jangan pernah dicetak).
- Sukses → cookie `mc_session` (HttpOnly, Secure, SameSite=Lax) dan cookie
  `mc_csrf` (Secure, SameSite=Lax, **bukan** HttpOnly), keduanya `Path=/`;
  token CSRF diikat ke sesi dan hanya dikirim ke server melalui header
  `X-CSRF-Token`.
- Semua `/api/*` wajib sesi; mutasi `POST`, `PUT`, `PATCH`, `DELETE` juga wajib
  header CSRF yang cocok. Safe method dan `/healthz` tidak memerlukan header itu.
  Unauthorized → `401 {"error":"unauthorized"}`; CSRF gagal →
  `403 {"error":"csrf_failed"}`.
- `POST /auth/logout` memvalidasi CSRF sebelum mencabut sesi, lalu menghapus
  kedua cookie. Runtime bearer `/runtime-api/*` tetap terpisah dan tidak
  menggunakan CSRF cookie.
- Sesi dan revocation disimpan durable pada SQLite lokal (`auth_state.db` atau
  `MISSION_CONTROL_AUTH_STATE_DB`); restart tidak menghapus state yang belum
  expired. Control plane masih owner-only; hardening ini bukan klaim kesiapan
  public/multi-user, tenant isolation, atau RBAC per pengguna.
- Throttle login gagal: 10 gagal/60 dtk per IP → 429.

## Runtime agent identity / ACL Phase 4

- `/api/*` tetap **owner control plane** dan selalu membutuhkan cookie
  `mc_session`. URL `agent_id` pada route owner hanya selector untuk dashboard;
  bukan bukti identitas runtime.
- `POST /api/obsidian/runtime-tokens` menerbitkan bearer token HMAC-SHA256
  sekali tampil untuk roster agent knowledge-capable. Claim minimum: `agent_id`,
  `sub`, `iss`, `aud`, `iat`, `exp`, `jti`, `scope`, dan `refresh_until`.
- `POST /api/obsidian/runtime-tokens/revoke` mencabut berdasarkan `token_id`
  tanpa menyimpan token mentah. Hash `token_id` dan expiry revocation yang
  disimpan; revocation tetap aktif setelah restart sampai token expired.
  `refresh_until` adalah batas absolut 24 jam sejak mint; refresh tidak pernah
  memperpanjang batas ini.
- `POST /runtime-api/auth/refresh` adalah endpoint bearer-only. Endpoint ini
  memvalidasi signature, issuer, audience, roster, scope, expiry, dan revocation,
  lalu menerbitkan token baru dengan agent/scope yang sama. Token lama tetap
  valid sampai expiry-nya sendiri; revocation owner tetap mencabut token per-ID.
  Token lama tanpa claim `refresh_until` tetap valid untuk route runtime sampai
  expiry, tetapi ditolak oleh endpoint refresh.
- Secret dibaca dari `MISSION_CONTROL_RUNTIME_TOKEN_SECRET` (minimal 32 byte)
  atau file fallback lokal `/opt/data/mission-control/.runtime_token_secret`
  yang diprovision atomik dengan mode 0600; file harus regular, bukan symlink,
  dan tidak boleh readable oleh group/other. Jika tidak ada secret valid, mint/decode
  gagal tertutup (fail closed).
- `/runtime-api/obsidian/workspace*` adalah router bearer-only terpisah, tanpa
  `mc_session` dan tanpa endpoint list-all-workspaces. Identitas caller berasal
  dari token tervalidasi; runtime hanya membaca namespace privat caller +
  `10-Wiki`, dan menulis proposal ke `40-Inbox/Agent-Workspace` dengan scope
  `proposal:create`. `MEMORY.md`, `USER.md`, namespace agent lain, path
  absolut/traversal, symlink, dan promosi note langsung ditolak.
- Response runtime menandai `runtime_identity=verified_service_token` dan
  `agent_runtime_acl=enforced`; response owner tetap `scope=owner_control_plane`.

## Runtime-token injection pilot

`/opt/data/scripts/mission_control_runtime_launcher.py` adalah utilitas lokal
control-plane untuk menjalankan satu command eksplisit dengan token runtime
sementara. Allowlist diturunkan saat runtime dari roster aktif dan agent yang
memiliki skill `obsidian` + `llm-wiki`; simbol `OBSIDIAN_AGENT_IDS` hanya
kompatibilitas import dan bukan sumber otorisasi. `opencode`, ID tidak dikenal,
dan agent roster yang bukan knowledge-capable selalu ditolak. Launcher tidak
membuat format token baru.

Contoh bounded probe:

```bash
/opt/data/scripts/mission_control_runtime_launcher.py \
  --agent-id <current-knowledge-agent-id> \
  --base-url http://127.0.0.1:9120 \
  --ttl 300 \
  -- /opt/hermes/.venv/bin/python /opt/data/scripts/mission_control_runtime_probe.py
```

Launcher memiliki shebang eksplisit ke `/opt/hermes/.venv/bin/python`, sehingga
pemanggilan executable langsung memakai dependency Mission Control yang benar.

Kontrak launcher:

- command wajib berada setelah `--`; token tidak pernah diterima dari argv.
- scope default hanya `workspace:read`; scope yang tersedia tetap `workspace:read`
  dan `proposal:create`.
- TTL pilot dibatasi 1–900 detik (default 300 detik), lebih ketat daripada batas
  encoder server. Token dibuat in-memory, tidak ditulis ke disk, roster, vault,
  prompt, atau log.
- child menerima `MISSION_CONTROL_RUNTIME_AGENT_ID`,
  `MISSION_CONTROL_RUNTIME_BASE_URL`, `MISSION_CONTROL_RUNTIME_REFRESH_URL`,
  `MISSION_CONTROL_RUNTIME_TOKEN`,
  `MISSION_CONTROL_RUNTIME_TOKEN_ISSUED_AT`,
  `MISSION_CONTROL_RUNTIME_TOKEN_EXPIRES_AT`,
  `MISSION_CONTROL_RUNTIME_TOKEN_REFRESH_UNTIL`, dan
  `MISSION_CONTROL_RUNTIME_SCOPES`. Nilai token di-redact bila child mencoba
  mencetaknya; owner dashboard credentials dan runtime secret tidak diteruskan.
- launcher tetap one-shot dan tidak melakukan refresh sendiri. Child long-lived
  harus memakai `mission_control_runtime_client.py`; client membaca kontrak env,
  refresh in-memory dengan safety margin yang dapat dikonfigurasi, mempertahankan
  agent/scope, dan retry request satu kali setelah 401. Rotasi tidak menulis token
  file atau mengubah env parent.
- `mission_control_runtime_refresh_probe.py` memaksa satu refresh terikat
  `refresh_until`, melakukan satu request workspace, dan hanya mencetak HTTP
  status plus verified `agent_id`.

Launcher adalah jalur lokal yang dikendalikan owner untuk mempersiapkan runtime;
launcher tidak memberikan `mc_session` atau kredensial owner kepada child.
Child hanya memiliki runtime bearer identity dan tetap terkurung pada namespace
agent sendiri, shared `10-Wiki`, serta proposal-only write sesuai ACL. Rollout
allowlist ini tidak menjadwalkan atau meluncurkan agent secara otomatis; cron,
profile, roster, scheduler, dan autonomous runtime tetap tidak berubah.

**Pilot status (2026-10-01):** allowlist launcher dihitung saat runtime dari seluruh
agent roster yang memiliki skill `obsidian` + `llm-wiki`, dengan rejection eksplisit
untuk `opencode`, ID tidak dikenal, dan roster non-knowledge. Token runtime kini
memiliki claim `refresh_until`
dengan batas absolut 24 jam; `/runtime-api/auth/refresh` mempertahankan identity/scope,
menolak token legacy/revoked/expired, dan tidak memberi owner privilege. Client
stdlib melakukan rotasi in-memory dengan retry satu kali; probe refresh hanya
mencetak status dan verified identity. Tidak ada cron, autonomous runtime,
profile, roster, atau scheduler yang diubah.

## Bounded Agent Engineer MCP bridge

Integrasi long-lived yang disetujui untuk `agent-engineer` adalah child stdio MCP
bridge yang dijalankan hanya melalui launcher dengan command eksplisit. Bridge
memanggil `RuntimeClient.from_env()` satu kali; token awal dan setiap hasil rotasi
hanya hidup di memori proses, tidak ditulis ke file, config, prompt, atau log.
Bridge tidak memiliki akses owner/control-plane, token mint/revoke, accepted-note
promotion, `MEMORY.md`, `USER.md`, namespace agent lain, atau arbitrary URL.

Tool yang diekspos hanya:

- `workspace_list` — daftar workspace privat caller dan bounded shared `10-Wiki`.
- `workspace_shared_context` — shared context `10-Wiki` yang sama, tanpa selector agent.
- `workspace_read` — baca satu note privat caller atau note shared yang diizinkan.
- `workspace_graph` — graph/context bounded pada scope caller + `10-Wiki`.
- `workspace_create_proposal` — proposal pending saja; tidak menulis accepted/private note.

Setiap proses memiliki `--max-duration-s` dan `--max-calls`; default bridge adalah
300 detik dan 50 tool calls, dengan batas maksimum durasi satu sesi 24 jam.
Input divalidasi dan error/response disanitasi agar token, credential, dan raw path
tidak keluar. Contoh child bounded:

```bash
/opt/data/scripts/mission_control_runtime_launcher.py \\
  --agent-id agent-engineer --ttl 300 -- \\
  /opt/data/scripts/mission_control_runtime_mcp_server.py \\
  --max-duration-s 300 --max-calls 50
```

Kontrak ini bukan autonomous runtime dan tidak mengubah Hermes persistent config,
profile, roster, cron, scheduler, atau proses terjadwal. Full LLM Hermes child
belum di-attach ke bridge; yang terverifikasi adalah bridge stdio long-lived,
RuntimeClient refresh in-memory, dan bounded live child smoke.

## Provider/model routing

Roster model references are preserved literally as `provider/model`, including model IDs that contain additional `/` characters. The bounded `mission_control_provider_launcher.py` splits only at the first slash and invokes Hermes with separate `--provider` and `--model` argv entries, a bounded `--run-budget`, and the prompt on stdin. It never uses shell interpolation, accepts no token argv, and redacts captured child output. This prevents a non-default provider from being silently routed through the default `openai-codex` provider. The launcher is one-shot and does not add agents, schedule work, or modify persistent Hermes configuration/profile state.

## Roster status and readiness semantics

`active` remains a backward-compatible configuration flag; `configured_active` is its explicit name. Runtime evidence is separate in `live_status`, `live_detail`, `live_sessions`, and `live_source_status`; `standby`/`unknown` are not claims that a process is running. Model readiness is catalog-based: `provider_catalog_available` reports provider membership, `model_catalog_available`/`model_available` require an exact model ID, and `provider_connected` is only populated when the catalog exposes explicit authentication evidence. The legacy `model_connected` field now means exact catalog match only; it is not a live network or process probe. `GET /api/agents/roster` only reads state; workspace provisioning/reconciliation remains on the explicit workspace route.

## Workflow and Obsidian readiness gates

Mission Control reports these states separately; none of them launches an agent:

- **Drive workspace ready**: persisted folder metadata exists and reads back. This is storage metadata, not runtime readiness or write permission.
- **Obsidian namespace ready**: the owner-approved private namespace directory and bounded `README.md` marker read back successfully. The current approved slice is exactly `hermes-lead`, `document-knowledge`, `social-research-trends`, and `content-planner-copywriter`; initialization is idempotent through `POST /api/obsidian/agent-workspaces/initialize` with the normal owner session and CSRF protection.
- **Runtime-ready**: `false` for this gate. No agent runtime, autonomous adapter, cron, or scheduler is activated.
- **Approved**: workflow stages remain approval-gated (`lead_review`, `approval_required`, and external-write/publish gates). Namespace initialization does not approve an agent for end users or external writes; private writes remain proposal-only.
- **Live**: `false`; roster `active=false` and route preview evidence is configuration-only (`launched=false`, `external_writes=false`).

The runtime/owner knowledge ACL is derived from current roster skills `obsidian` + `llm-wiki`, excludes OpenCode and legacy IDs, and does not infer authorization from a directory that happens to exist. Backend/Data and Frontend/Product UI remain ACL-eligible by skill metadata where applicable but are not provisioned in this namespace slice. Workflow stage selection uses capability plus validated metadata filters such as `runtime_mode=lead` or `runtime_mode=planner`; it does not require ordinary candidate-agent ID lists.

## Start / Stop

```bash
# start (dari /opt/data/mission-control):
cd /opt/data/mission-control
HERMES_DELEGATED_CHILD_CONTEXT= nohup /opt/hermes/.venv/bin/python -m uvicorn \
  server:app --host 0.0.0.0 --port 9120 --log-config uvicorn-log.json \
  >> /opt/data/logs/mission-control.log 2>&1 &
echo $! > server.pid

# stop:
kill "$(cat /opt/data/mission-control/server.pid)"

# cek kesehatan:
curl http://127.0.0.1:9120/healthz   # -> {"status":"ok"}
```

Catatan: `HERMES_DELEGATED_CHILD_CONTEXT=` sengaja dikosongkan — marker sesi
delegate-child membuat CLI `hermes kanban` menolak mutasi task (guard bawaan
Hermes, berlaku juga untuk plugin). Server mandiri yang dijalankan dari konteks
normal (lead/systemd/Coolify) tidak butuh baris itu.

## Rebuild frontend

```bash
cd /opt/data/mission-control/frontend && npm install && npm run build
```

## Catatan deployment (Coolify)

- Port **9120 belum di-expose** di Coolify — perlu dihandle lead agent/user:
  tambahkan proxy/domain ke port 9120 bila akses remot diinginkan.
- Server bind `0.0.0.0` dengan auth sendiri (401 tanpa sesi) — aman di-expose,
  disarankan lewat proxy HTTPS.
- Sesi owner dan revocation runtime durable pada SQLite lokal; restart server
  tidak mencabut state yang belum expired. Cookie sesi dan CSRF selalu memakai
  atribut `Secure`; deployment publik harus
  tetap melalui HTTPS.
