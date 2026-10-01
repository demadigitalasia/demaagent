# DEMA User Gateway Contract v1

Status: `not_enabled_yet`

Dokumen ini menjelaskan **foundation policy** untuk User Gateway DEMA. Implementasi saat ini bersifat pure policy dan tidak menambahkan endpoint, webhook, database, atau runtime baru.

## Yang sudah diimplementasikan

- Modul `business_gateway/tenant_boundary.py` yang independen dari FastAPI, database, scheduler, dan control plane.
- Kontrak identitas Telegram sebagai literal string ASCII digit sepanjang 1–20 karakter. Nilai tidak di-trim, di-cast, dinormalisasi, atau diperbaiki diam-diam.
- Context internal yang eksplisit: `user_id`, `tenant_id`, `role`, dan `status`.
- Registry mapping immutable dengan penolakan untuk identity tidak dikenal, mapping Telegram duplikat, mapping user/tenant ambigu, status nonaktif, dan role `platform_admin` pada boundary Telegram.
- Role boundary minimum:
  - `user`: request bisnis untuk user dan tenant sendiri.
  - `tenant_admin`: administrasi bisnis dalam tenant sendiri; tidak mendapat akses platform.
  - `platform_admin`: boundary owner/admin terpisah dan tidak diberikan oleh mapping Telegram atau default registration.
- Routing deterministik:
  `telegram_user → tenant_boundary → dema_assistant → dema_lead → approved_business_catalog_or_workflow`.
- Tenant context hanya berasal dari identity yang sudah di-resolve. Input request boleh dibandingkan untuk mendeteksi mismatch, tetapi tidak boleh memilih tenant baru.
- Allowlist terbatas pada catalog lookup, request routing, tenant-scoped business request, tenant business administration, dan proposal.
- Deny-by-default untuk global memory, global skill library, roster mutation, provider configuration, runtime-token mint/revoke, Coolify/deploy, Mission Control owner control plane, dan autonomous scheduling/cron.
- Artifact kontrak JSON: `catalog/dema-user-gateway-contract-v1.json`.
- Test TDD terfokus: `tests/test_dema_user_gateway_boundary.py`.

## Belum diaktifkan

Foundation ini **belum** menyediakan:

- Telegram webhook atau live Telegram bot integration.
- Persistent identity database atau penyimpanan mapping user/tenant.
- Public route atau public release.
- Session issuance untuk end user.
- Tenant user data.
- Runtime activation untuk DEMA Assistant, DEMA Lead, atau kandidat lain.

## Batas keamanan

Modul ini tidak memodifikasi `server.py`, frontend, owner auth, runtime ACL, roster, provider configuration, phase1 readiness proposal, cron, profile, persistent MCP, scheduler, atau credential. Modul juga tidak melakukan external write dan tidak mengaktifkan autonomous runtime.

Sebelum public release, gate berikut masih wajib diselesaikan: identity mapping yang durable dan diaudit, RBAC final, tenant isolation pada data layer, CSRF/session hardening, audit trail, deployment restrictions, approval workflow, serta verifikasi keamanan end-to-end.
