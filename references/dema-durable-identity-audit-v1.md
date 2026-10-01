# DEMA Durable Identity dan Audit Metadata v1

Status: `not_enabled_yet`

Dokumen ini menjelaskan fondasi penyimpanan internal yang sudah dibuat untuk
mapping identity DEMA. Fondasi ini reusable untuk tahap security berikutnya,
tetapi **belum menjadi fitur user-facing** dan belum terhubung ke server.

## Yang sudah diimplementasikan

- Modul stdlib-only `business_gateway/identity_store.py` dengan SQLite.
- Path database wajib diberikan eksplisit oleh caller. Modul tidak memiliki
  default path live dan tidak membuat database production.
- Schema version v1 dengan dua tabel:
  - `identity_mappings`: literal `telegram_user_id`, `user_id`, `tenant_id`,
    `role`, `status`, `created_at`, dan `updated_at`.
  - `audit_events`: event id, timestamp, action, actor type/id, target type,
    fingerprint identity, result, dan metadata JSON terbatas.
- Role Telegram yang diterima hanya `user` dan `tenant_admin`. Role
  `platform_admin` ditolak karena tetap berada pada owner/admin boundary
  terpisah.
- Status yang divalidasi: `active`, `pending`, `suspended`, dan `disabled`.
- Telegram ID divalidasi sebagai string ASCII digit 1–20 karakter dan
  disimpan persis seperti input; tidak ada trim, cast, atau normalisasi.
- Duplicate Telegram mapping dan user yang akan menjadi ambigu lintas tenant,
  role, atau status ditolak.
- Mutasi mapping dan audit event memakai transaksi SQLite serta SQL
  berparameter. Kegagalan constraint atau audit tidak meninggalkan mapping
  setengah jadi.
- Audit tidak menyimpan raw Telegram ID. Audit memakai fingerprint SHA-256
  deterministik dan menolak metadata yang mengandung identity mentah atau
  nilai berbentuk password, token, API key, bearer, atau credential.
- Metadata audit dibatasi ukuran, kedalaman, jumlah item, dan tipe JSON.
- API internal yang tersedia: `initialize_identity_store(path)`, method
  `add_mapping`, `resolve_mapping`, `set_mapping_status`, dan
  `read_audit_events`.

## Tetap belum diaktifkan

Fondasi ini **tidak** menambahkan:

- wiring ke `server.py` atau `plugin_api.py`;
- Telegram webhook atau koneksi Telegram;
- public route atau public/multi-user release;
- session issuance;
- real users, real identities, atau tenant data;
- autonomous behavior, cron, scheduler, atau runtime activation.

Identity yang unknown atau tidak terdaftar tetap menghasilkan `None` pada
storage resolution dan tetap ditolak oleh pure policy layer yang sudah ada.

## Batas retention dan operasi

v1 hanya menetapkan bentuk storage dan bounded audit metadata. Belum ada
retention schedule, deletion policy, export workflow, atau live database.
Test dan operasi harus memakai database terisolasi yang path-nya diberikan
secara eksplisit dan tidak boleh diisi identity nyata.

## Verifikasi

Test terfokus berada di
`tests/test_dema_durable_identity_store.py`. Test mencakup persistence,
literal preservation, duplicate dan ambiguity rejection, pemisahan
`platform_admin`, status inactive, rollback transaksi, fingerprint audit,
penolakan metadata sensitif, unknown identity, serta invariant roster,
phase1, namespace, dan tidak adanya server wiring.

## Gate keamanan berikutnya

Sebelum ada wiring atau penggunaan live, perlu review dan approval untuk
retention/erasure, final RBAC, tenant isolation pada data layer, audit
redaction dan access control, session/CSRF hardening, operational backup dan
rotation, webhook authentication, rate limiting, serta end-to-end security
review. Semua gate harus selesai sebelum public release.
