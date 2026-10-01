# DEMA Global Agent Catalog v1

**Dokumentasi:** 2026-10-01
**Status:** implemented as a read-only architecture/catalog artifact

## Artefak kanonik

- Manifest: `catalog/dema-global-agent-catalog-v1.json`
- Focused contract tests: `tests/test_dema_global_agent_catalog.py`
- Logical knowledge scope reference: `10-Wiki` (shared); personal agent context tetap tenant/user-scoped.

Manifest ini adalah katalog produk dan arsitektur. Manifest **bukan** instruksi provisioning dan tidak dibaca sebagai daftar proses runtime.

## Cakupan nama dan mapping

Manifest menggabungkan dua sumber desain:

1. Business roster: DEMA Lead, Support, Sales, Order, CRM, Marketing, Social, Content, Analyst, Finance, Booking, Document, Operations, Inventory, Procurement, HR, Recruiter, Project, Meeting.
2. Product catalog: DEMA Social, Content, Analyst, Finance, Booking, Document, Operations, Inventory, Procurement, HR, Recruiter, Project, Meeting, Email, Assistant, Research, Commerce, Retention, Review, Report.

Tidak ada nama yang dihilangkan diam-diam. `source_mappings` menyimpan setiap pasangan source-set/name dan mengarahkannya ke catalog ID dengan alasan `canonical`, `alias`, atau `workflow_mapping`. Contoh: `Social` dan `DEMA Social` mengarah eksplisit ke `dema-social`; `Order`, `Booking`, `Recruiter`, `Meeting`, `Email`, `Research`, `Retention`, `Review`, dan `Report` dipetakan sebagai workflow/sub-capability bila tidak membutuhkan proses agent mandiri.

## Pemisahan boundary

- `platform_internal` terdiri dari tujuh entity existing: `hermes-lead`, `agent-engineer`, `opencode`, `sub-agent-back-end`, `sub-agent-devops`, `sub-agent-front-end`, dan `sub-agent-ui-ux`.
- Public/business catalog terdiri dari `DEMA Assistant`, `DEMA Lead`, serta domain functions seperti Support, Sales, CRM, Marketing, Social, Content, Analyst, Finance, Document, Operations, Inventory, Procurement, HR, Project, dan Commerce.
- Workflow catalog dipisahkan dari domain agent untuk Order, Booking, Recruiter, Meeting, Email, Research, Retention, Review, dan Report.
- Setiap entry memiliki metadata eksplisit: identity, kind, domain, purpose, input/output contract, single `runtime_owner`, parent, visibility, execution mode, provider policy, skills, tools, knowledge scope, approval boundary, autonomous flag, status, dan notes.

## Runtime owner dan rekomendasi roster

Setiap entry memiliki tepat satu `runtime_owner` string dan `runtime_owner_reason`. Shared ownership oleh `hermes-lead` adalah keputusan arsitektur yang disengaja untuk catalog-only business functions yang belum memiliki runtime product khusus. Social memakai `agent-socmed`; Research memakai `news-agent`; platform rows mempertahankan self-owner existing.

`recommended_runtime_roster` hanya rekomendasi top-level: `dema-assistant`, `dema-lead`, `dema-social`, `dema-research`, dan shared business workflows. Semua record ditandai `recommendation_only_not_provisioned` dan tidak ditulis ke roster aktif.

## Yang benar-benar diimplementasikan

- Manifest JSON v1 yang dapat diparse dengan 33 catalog entries dan 39 source mappings.
- Union coverage test untuk seluruh nama dari kedua sumber desain.
- Schema/metadata, uniqueness, platform/business separation, single-owner reasoning, no-secret/no-absolute-path, dan roster non-mutation tests.
- Frozen runtime guard untuk 9 roster IDs, literal model assignments, seluruh `active=false`, dan namespace count 8.
- Dokumentasi boundary bahwa jumlah produk/workflow yang terlihat user tidak sama dengan jumlah proses runtime.

## Yang masih berupa rekomendasi/keputusan produk

- Provisioning public DEMA agents ke `agents.json`.
- Menambah schedule, cron, profile, provider, credentials, MCP persistent configuration, autonomous runtime, atau authentication multi-user.
- Menentukan tenant/user runtime pribadi dan permission detail.
- Menambahkan API/UI catalog read-only; v1 sengaja memprioritaskan manifest, tests, dan dokumentasi tanpa memperluas surface API.

Tidak ada perubahan scheduler, cron, profile, provider state, authentication, autonomous runtime, atau roster aktif sebagai bagian dari katalog v1.
