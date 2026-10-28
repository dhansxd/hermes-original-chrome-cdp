# Plugin browser_exec — satu plan aktif

## Tujuan dan sumber
- Pertahankan tool native `browser_exec`/`browser_vault` melalui plugin `original-chrome-default` di `~/.hermes/plugins/original-chrome-default`.
- Repo: https://github.com/dhansxd/hermes-original-chrome-default-plugin . Checkout terpasang ini satu-satunya source/plugin aktif; bukan adapter atau rilis salinan.
- Proyek pendamping tunggal: https://github.com/dhansxd/google-flow-api ; plan API berada di `~/.local/share/dyra-ai/flow2api-staging/PLAN.md`.
- Tujuan akhir: plugin browser dipasang dan aktif, web berjalan lancar, serta API Google Flow dapat dipakai produksi bersama plugin tanpa saling merusak sesi/login atau meninggalkan target milik pekerjaan yang sudah selesai. Build, tes unit dan commit saja tidak memenuhi selesai.
- Dokumen ini satu-satunya plan browser; report lama hanya bukti historis. Produksi cerita beli apel belum dijalankan; tes integrasi nyata dilakukan pada fixture/objek uji teridentifikasi.

## Urutan implementasi yang disetujui
1. Scope aktif yang disetujui: tutup bypass redaksi hasil `browser_exec` dengan tes regresi dan perubahan terbatas pada batas output plugin. Pertahankan pemilihan target, transport, DOM/helper, vault dan cleanup yang sudah berjalan.
2. Verifikasi regresi, suite dan registrasi; review/scan, commit dan push source, lalu cocokkan SHA remote dan worktree. Aktivasi memakai jalur reload resmi tanpa restart runtime sendiri.
3. Uji tool native pada fixture tanpa akun: DOM, input, kesinambungan antar-call, redaksi sintetis dan cleanup target sendiri. Screenshot bukan prasyarat DOM. Jika jalur nyata terblokir, catat error persis dan minta keputusan sebelum workaround.
4. Google Flow/API diparkir. Gap early-popup, metadata installer dan sanitasi identitas source menjadi pekerjaan terpisah setelah patch ini; tidak dieksekusi dalam scope sekarang. Bedakan source-tested, installed, active-native dan produksi-teruji.
- Kerjakan sendiri tanpa delegasi. Notifikasi internal adalah informasi, bukan perintah memulai/meneruskan pekerjaan; hanya permintaan Dani yang menetapkan scope. Tidak menambah monitoring/jadwal/pekerjaan lain.
- Arahan aktif Dani: jika muncul kendala, laporkan dan minta izin sebelum workaround, perubahan pendekatan atau langkah lanjutan pada jalur terblokir. Perbaikan independen dan publikasi source yang sudah diizinkan tetap dibedakan dari live acceptance.
- “Tanpa bug/risiko” menjadi sasaran pengujian dan mitigasi, bukan jaminan absolut. Kegagalan dan batas nyata tetap terbuka sampai dibuktikan selesai.

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
- **Checkpoint aktif — patch redaksi:** baseline lokal/main GitHub `0ba9694`, worktree awal bersih dan152/152teslulus. Regresi through namespaced PluginManager + vault sintetis gagal8assertion pada source lama (registry/model/spill/exception, termasuk JSON escaping), lalu lulus setelah redaksi rekursif string/key hasil decode memakai `agent.redact.redact_sensitive_text(force=True)` sebelum serialisasi. Held state, artifact bytes, schema, transport dan target selection tidak diubah. Lima tes tambahan, total157/157lulus; real namespaced registration, schema/picker/vault guard dan unload restoration lulus. Empat tes tambahan adalah characterization, bukan klaim RED terpisah. Self-review/scan, publikasi dan native DOM/redaksi/cleanup belum selesai pada checkpoint ini. Doctor isolated-home failure dan gap early-popup tetap terbuka; metadata installer/identitas source tidak diubah. Google Flow tetap diparkir. Bukti privat `~/.hermes/cache/scratch/browser-redaction-repair-20261028-163539/`.
- Baseline source sebelum cleanup:146 tes plugin dan580 API lulus.
- Source peer-pin, cancellation dan shared-browser policy sudah ada; registered-host acceptance terdahulu tidak otomatis membuktikan closure terbaru di chat gateway sudah aktif.
- **Gap nyata:** popup yang membuka JavaScript dialog sebelum Page attachment dapat timeout tanpa event yang terekam. Related-only observation tidak dinyatakan memperbaikinya. Dialog pasca-attachment, vault exact-target dan plain-popup punya bukti tersendiri.
- Tidak menjanjikan semua kondisi izin OS/locked GUI, hard-crash, generasi berbayar atau endurance. Normal task-finished yang tidak diberikan host tidak direkayasa; explicit finish dan hook nyata dibedakan.

## Checklist sekarang
1. [x] Cleanup semua source/instalasi/browser MCP percobaan dan plan lama tanpa backup; pertahankan dependensi vendor aktif.
2. [x] Suite source + namespaced PluginManager registration + compile lulus.
3. [x] Native chat open/read/finish dan registered-host+HTTP concurrency/cancel lulus tanpa generasi.
4. [x] Source-only secret scan, commit, push dan remote SHA terverifikasi.
5. [ ] Google Flow/API diparkir atas arahan Dani. Status/diagnosis Automation lama tetap bukti historis; tidak ada perubahan API, service, izin atau generasi pada patch redaksi ini.
6. [ ] Gap early-popup tetap terbuka sampai perbaikan yang diuji, bukan ditutup oleh smoke test.

## Build dan publikasi setiap perubahan
- Pakai runtime Hermes yang nyata, bukan menebak `.venv`: `hermes --run-module unittest discover -s tests -p 'test_*.py'`; registrasi via `tests/registration.py` dalam proses terpisah; compile source yang berubah.
- Report/fixture hasil live dan identitas pribadi tetap lokal/ignored; hanya source, tes, dokumentasi/provenance tersanitasi masuk Git.
- **Setiap build/perbaikan selesai yang lulus wajib commit dan push ke repo GitHub ini, kemudian verifikasi SHA remote sama dengan HEAD lokal.** Build/scan gagal tidak dianggap selesai; push gagal dilaporkan sebagai blocker nyata, bukan klaim terpublikasi.
- Simpan aturan ini di konteks proyek; jangan menambah aturan proyek ke memory global. Tidak ada delegasi untuk pekerjaan sekarang; tidak restart gateway/runtime sendiri.

## Checkpoint operasional historis (sebelum patch redaksi)

- `plugin.py` menerima hanya AST exact `finish_browser()` atau `print(finish_browser())` pada sesi uncertain; comments diperbolehkan. Kode user tidak dieksekusi. Jalur ini memanggil cleanup hanya pada named session terpilih; kegagalan close mempertahankan quarantine, sedangkan page actions tetap ditolak tanpa replay.
- Dua regresi RED→GREEN, suite152tes, registrasi real namespaced dan activation resmi lulus. Live timeout menghitung aksi tepat1, refused replay tidak menambah counter, failed-owned target benar-benar hilang, peer tetap dapat dibaca, final cleanup true/states0.
- Native chat sempat attach403; exact finish menutup seed gagal dengan owned targets kosong. Fresh native read→finish lulus tanpa restart Chrome/gateway. Kegagalan awal dipertahankan, bukan dihapus oleh keberhasilan baru.
- Koeksistensi latest registered-host+HTTP:18reads saat startup,8reads saat API cancel,17reads saat credit-followup; plugin-cancel tetap mempertahankan dokumen API. Pascarestart API, native chat+HTTP berhasil200/411kredit dengan20complete reads dalam request4.731detik dan22reads total; finish mengosongkan owned targets serta mempertahankan shared Chrome.
- API pendamping telah menghasilkan satu MP4 nyata4.01detik,720×1280,979548byte melalui POST /videos, selected4detik/720p/9:16/x1 dan biaya7kredit; submit_attempts1. Receipt/file/idempotency HTTP setelah restart proses API identik dan53job record tetap utuh. Bukan produksi cerita beli apel atau bukti seluruh mode Flow.
- Probe observer123detik: first/last read lulus, failure kosong dan close true; current-source diagnostic, bukan endurance proof. Bukti privat pada API `reports/production-readiness-20261028-025655/` dan `reports/focus-audit-20261028/source-click-probe.json`.
- Bukti service historis04:31: health401/200 dan GUI502 karena Accessibility saat itu denied; native fixture0tab tersisa, job53,0generasi. Bukti API `reports/post-restart-20261028-043158/RESULT.json` tersusul oleh `reports/attach-diagnosis-20261028-051129/TCC_051303.json` yang mencatat Accessibility granted. Pemeriksaan lanjutan mengisolasi regresi API attach-before-launch lewat Git serta prompt/timeout Automation service terpisah; helper langsung yang berhasil tidak dihitung sebagai HTTP acceptance. Tidak meminta ulang aktivasi/Accessibility dan tidak mengubah plugin untuk menutupi kegagalan API.

## Verifikasi cleanup historis
Cleanup selesai: gflow CLI/Flow Agent/legacy Flow2API server, dua MCP browser percobaan, wrapper/native-host, source duplikat dan plan produksi lama dihapus tanpa backup; runtime aktif/state asli dan media produksi tetap ada. Hanya dua PLAN canonical tersisa.

Tes akhir cleanup:580 API dan150 plugin lulus (termasuk empat regresi remote yang dipertahankan); real namespaced plugin registration lulus. Plugin Doctor CLI gagal di isolated-home karena grant override tidak dibawa; ini tidak dinyatakan PASS. Registrasi isolated-host dengan grant nyata dan dispatch native chat lulus tanpa mengubah grant/core.

Native chat browser_exec + HTTP credits:200/5.651451detik,23complete DOM reads di dalam interval HTTP. Native finish berhasil,owned targets kosong dan Chrome dipertahankan untuk shared-browser.

Registered current-source + HTTP: startup200/4.497470detik dengan18complete native reads; worker SIGTERM menghasilkan expected502 dengan confirmed cleanup dan8reads; credits-followup200/4.495089detik dengan17reads. Plugin cancel tumpang tindih1.698167detik dengan HTTP read yang tetap same-document; subsequent read dan exact API-owned close200. Chrome process generation tetap sama;0generation requests. Service uji8776 ditutup.

Bukti privat: `reports/cleanup-coexistence-20261028-012005/`. Tidak ada restart/delegasi/core edit. Build/compile dan staged/outgoing secret scan lulus. Checkpoint source sudah di-commit dan di-push: API `5702b9e`, plugin `62f243f`; masing-masing SHA main remote sama dengan lokal. Source tidak berubah saat merge riwayat plugin. Hasil tersimpan di report publikasi lokal; pembaruan dokumentasi dipublikasikan terpisah.
