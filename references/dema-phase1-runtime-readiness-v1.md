# DEMA Phase 1 Business Runtime Readiness Proposal

**Dokumentasi:** 2026-10-01
**Status:** readiness proposal / approval gate; bukan runtime rollout

## Artefak kanonik

- Manifest: `catalog/dema-phase1-runtime-readiness-v1.json`
- Focused contract tests: `tests/test_dema_phase1_readiness.py`
- Global architecture catalog: `catalog/dema-global-agent-catalog-v1.json`

## Cakupan Phase 1

Proposal ini mencakup delapan kandidat:

- Public entry/orchestrator: `dema-assistant`, `dema-lead`
- Core domain candidates: `dema-support`, `dema-sales`, `dema-crm`, `dema-commerce`
- Workflow candidates under Commerce: `dema-order`, `dema-booking`

`dema-order` dan `dema-booking` adalah workflow di bawah `dema-commerce`, bukan top-level runtime agents pada tahap awal. Rekomendasi runtime hanya memuat enam owner awal; dua workflow berbagi lifecycle Commerce.

## Status yang benar-benar diimplementasikan

- Manifest JSON kanonik dengan tepat delapan `candidate_entries`.
- Metadata eksplisit per kandidat, provider/model policy yang belum dipilih, permission boundary, knowledge scope, approval boundary, dan `autonomous_allowed: false`.
- Lifecycle eksplisit: semua kandidat berhenti di `design_candidate`; `configured`, `tested`, `on_demand_ready`, `approved_for_users`, dan `active` semuanya `false`.
- Dependencies dan acceptance gates untuk provider/model selection, persona contract, tool contract, knowledge boundary, tenant isolation, bounded smoke, cost/quota, audit, dan human approval.
- Recommendation-only runtime roster yang tidak diprovisionkan.
- Guard roster existing: sembilan ID, model literal, semua `active=false`, dan delapan namespace.
- Focused tests ditulis sebelum artifact untuk membuktikan RED lalu GREEN.

## Bukan provisioning

Artifact ini tidak menambah atau mengubah `agents.json`. Artifact ini juga tidak membuat cron, scheduler, profile, persistent MCP configuration, autonomous runtime, provider state, credential, authentication change, tenant user, personal agent, API, atau frontend. Tidak ada live business agent yang dijalankan.

`recommendation_only_not_provisioned` berarti keputusan runtime masih menunggu rollout approval terpisah. Katalog global juga tidak sama dengan runtime roster; personal agents tetap tenant/user-scoped.

## Unresolved product decisions

Keputusan berikut belum selesai dan memblokir konfigurasi atau user approval:

1. Provider dan exact model untuk setiap proposed runtime owner.
2. Persona contract, input/output contract, escalation, dan human-handoff behavior.
3. Tool contract dan batas read/write untuk CRM, commerce, order, serta booking.
4. Knowledge sources final, provenance, retrieval limits, dan tenant isolation proof.
5. Cost, token, rate, concurrency quota, serta refusal behavior.
6. Audit event schema yang cukup untuk operasional tanpa menyimpan nilai sensitif.
7. Siapa human approver dan target rollout: owner-only, trusted internal, atau public/multi-user.
8. Apakah workflow Order/Booking tetap shared di Commerce setelah bounded smoke atau kelak membutuhkan lifecycle terpisah.

## Acceptance boundary

Readiness tidak boleh dinaikkan hanya karena manifest, test, atau health check tersedia. Setiap candidate tetap `design_candidate` sampai dependency dan gate terkait memiliki bukti, lalu membutuhkan approval manusia eksplisit sebelum user exposure. Public/multi-user release tetap blocked sampai tenant identity, authorization, isolation, audit, dan shared-credential boundaries selesai diverifikasi.
