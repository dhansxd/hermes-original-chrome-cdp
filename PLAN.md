# Plugin browser_exec — satu plan aktif

## Tujuan dan sumber
- Pertahankan tool native `browser_exec`/`browser_vault` melalui plugin `original-chrome-default` di `~/.hermes/plugins/original-chrome-default`.
- Repo: https://github.com/dhansxd/hermes-original-chrome-default-plugin . Checkout terpasang ini satu-satunya source/plugin aktif; bukan adapter atau rilis salinan.
- Proyek pendamping tunggal: https://github.com/dhansxd/google-flow-api ; plan API berada di `~/.local/share/dyra-ai/flow2api-staging/PLAN.md`.
- Fokus: browser bekerja normal dan berdampingan dengan API. Tidak menjalankan produksi/generasi video saat ini. Dokumen ini satu-satunya plan browser; report lama hanya bukti historis.

## Kontrak yang dipertahankan
- Browser asli Chrome GUI macOS, profil `Default` sesuai account binding yang sudah ditetapkan kode. Verifikasi metadata principal dan Profile Path sebelum navigasi; jangan memilih profil lain, first tab atau last-used sebagai fallback identitas.
- Chrome untuk agent; Safari pribadi tidak disentuh. Login/profil asli dan Keychain dipertahankan, tanpa cookie copy, reset Preferences/storage, atau flag bypass Keychain.
- Attach existing Chrome atau cold-launch melalui LaunchServices GUI yang terverifikasi dari pemanggilan tool normal. Kegagalan/perlu tindakan manusia dilaporkan; fallback tidak boleh disamarkan sebagai Chrome asli.
- Provider/menu dan tool override memakai API plugin resmi. Hermes core tidak diubah. `browser.backend=browser-use`, provider `original-chrome-default`, grant `tools.override` diperlukan.
- Parent memegang satu scoped observer/CDP; Python user tetap bounded worker. Helpers dari `vendor/` milik paket, dengan provenance; workspace helper, event/dialog, upload/screenshot dan native-vault compatibility dipertahankan.
- Native vault list/unlock tetap native; write meminjam exact held session/target/document setelah validasi. Jangan memakai target same-origin lain, koneksi kedua atau membocorkan secret melalui worker/output.
- Target baru milik plugin di-arm sebelum aksi; kepemilikan/checkpoint dikirim sebelum hasil final. Unknown/lost binding tidak di-replay atau diganti target lain.

## Koeksistensi dengan API
- Gunakan owned-root/related observation, bukan browser-wide attachment ke target API. Shared endpoint tidak berarti shared ownership.
- `finish_browser`, cancel/finalize/unload menutup target positif milik plugin dan transportnya saja. Browser Chrome tetap hidup untuk peer/API; jangan kembali ke perilaku full-browser exit lama.
- Koordinasi lintas proses hanya consent handshake/cancellation dan owned target-close. Reads/aksi normal berjalan bersamaan.
- Settled peer receipt harus membuktikan epoch/process/socket exact dan independent pin; pending atau unknown peer tidak dianggap aman.
- Buktikan progress native di tengah request API; cancel API tidak mematikan plugin, cancel/finish plugin tidak mematikan dokumen API; owned-close dan peer cleanup harus terkonfirmasi.

## Status dan gap
- Baseline source sebelum cleanup:146 tes plugin dan580 API lulus.
- Source peer-pin, cancellation dan shared-browser policy sudah ada; registered-host acceptance terdahulu tidak otomatis membuktikan closure terbaru di chat gateway sudah aktif.
- **Gap nyata:** popup yang membuka JavaScript dialog sebelum Page attachment dapat timeout tanpa event yang terekam. Related-only observation tidak dinyatakan memperbaikinya. Dialog pasca-attachment, vault exact-target dan plain-popup punya bukti tersendiri.
- Tidak menjanjikan semua kondisi izin OS/locked GUI, hard-crash, generasi berbayar atau endurance. Normal task-finished yang tidak diberikan host tidak direkayasa; explicit finish dan hook nyata dibedakan.

## Checklist sekarang
1. [x] Cleanup semua source/instalasi/browser MCP percobaan dan plan lama tanpa backup; pertahankan dependensi vendor aktif.
2. [x] Suite source + namespaced PluginManager registration + compile lulus.
3. [x] Native chat open/read/finish dan registered-host+HTTP concurrency/cancel lulus tanpa generasi.
4. [ ] Source-only secret scan, commit, push dan remote SHA terverifikasi.
5. [ ] Gap early-popup tetap terbuka sampai perbaikan yang diuji, bukan ditutup oleh smoke test.

## Build dan publikasi setiap perubahan
- Pakai runtime Hermes yang nyata, bukan menebak `.venv`: `hermes --run-module unittest discover -s tests -p 'test_*.py'`; registrasi via `tests/registration.py` dalam proses terpisah; compile source yang berubah.
- Report/fixture hasil live dan identitas pribadi tetap lokal/ignored; hanya source, tes, dokumentasi/provenance tersanitasi masuk Git.
- **Setiap build/perbaikan selesai yang lulus wajib commit dan push ke repo GitHub ini, kemudian verifikasi SHA remote sama dengan HEAD lokal.** Build/scan gagal tidak dianggap selesai; push gagal dilaporkan sebagai blocker nyata, bukan klaim terpublikasi.
- Simpan aturan ini di konteks proyek; jangan menambah aturan proyek ke memory global. Tidak ada delegasi untuk pekerjaan sekarang; tidak restart gateway/runtime sendiri.

## Verifikasi cleanup terbaru
Cleanup selesai: gflow CLI/Flow Agent/legacy Flow2API server, dua MCP browser percobaan, wrapper/native-host, source duplikat dan plan produksi lama dihapus tanpa backup; runtime aktif/state asli dan media produksi tetap ada. Hanya dua PLAN canonical tersisa.

Tes akhir cleanup:580 API dan150 plugin lulus (termasuk empat regresi remote yang dipertahankan); real namespaced plugin registration lulus. Plugin Doctor CLI gagal di isolated-home karena grant override tidak dibawa; ini tidak dinyatakan PASS. Registrasi isolated-host dengan grant nyata dan dispatch native chat lulus tanpa mengubah grant/core.

Native chat browser_exec + HTTP credits:200/5.651451detik,23complete DOM reads di dalam interval HTTP. Native finish berhasil,owned targets kosong dan Chrome dipertahankan untuk shared-browser.

Registered current-source + HTTP: startup200/4.497470detik dengan18complete native reads; worker SIGTERM menghasilkan expected502 dengan confirmed cleanup dan8reads; credits-followup200/4.495089detik dengan17reads. Plugin cancel tumpang tindih1.698167detik dengan HTTP read yang tetap same-document; subsequent read dan exact API-owned close200. Chrome process generation tetap sama;0generation requests. Service uji8776 ditutup.

Bukti privat: `reports/cleanup-coexistence-20261028-012005/`. Tidak ada restart/delegasi/core edit. Build/compile dan staged secret scan lulus. Publikasi checkpoint ini wajib commit+push lalu verifikasi SHA remote; hasil aktual ada di handoff dan report publikasi lokal.
