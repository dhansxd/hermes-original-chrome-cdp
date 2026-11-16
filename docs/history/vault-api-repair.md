# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# Unified vault API compatibility repair

Cause: upstream commit 3bf97898ac merged browser_vault_* registrations into browser_vault. Plugin registration referenced removed names; adapter also pinned the prior handler names/source hash.

Changed only plugin implementation, manifest and affected test fixtures. Unified tool keeps original schema; page actions borrow the selected observer and exact document transport. List/unlock delegate directly. Native source hash remains a fail-closed compatibility check, not removed.

Verification:
- RED: real isolated registration failed: native vault tool registration missing: browser_vault_fill.
- RED: migrated synthetic vault fixtures: 24 tests, 9 failures before adapter migration.
- GREEN: 24 vault tests pass; complete unit suite 107 tests pass.
- Real PluginContext registration, original schema equality, list/unlock passthrough, unbound page-action refusal and picker presence pass.
- Real disposable GUI Chrome: synthetic credential filled selected target only, same-origin comparison form untouched, no second peer/worker secret path, subsequent dialog observation works, cleanup passes, zero fixture processes remain.
- Native browser_exec in existing chat still reports unregistered provider. Current gateway has not reloaded the repaired plugin. Owner restart required; no agent/runtime restart performed.

Actual credentials, real payment and masked prompts were not exercised. No claim of native-chat recovery until restart and successful browser_exec.
