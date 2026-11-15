# Project scope and verification

## Scope

Provide Original Chrome through Hermes's native BrowserProvider interface and
Browser Automation picker. Use the current macOS user's existing Chrome profiles
through CDP, including their saved website sign-ins.

Each session owns its windows, tabs, and opener-linked popups. Support Chrome
stopped, running without windows, and already in use. Agents and manual browsing
share the original Chrome application while retaining independent tab ownership.

Implementation work belongs in this plugin repository. Keep Hermes core and its
installed native browser helpers under Hermes's own management.

## Current implementation

- Native provider registration, configuration picker, and browser_exec dispatch.
- Explicit existing-profile startup and verified Chrome process/profile identity.
- Exact Accessibility consent and a loopback per-session CDP relay.
- Namespaced native sessions and owned-target routing.
- Plugin-owned input focus verification.
- Finalization, unload admission control, and retryable in-process cleanup.

## Dynamic profiles — approved 15 November 2026

Add fresh original-Chrome profile discovery, a configurable default and explicit
selection for each agent's named browser session. Keep each agent's own windows
when several agents choose one profile, and support concurrent different profiles.
Profile selection belongs to the plugin's session routing. Use its public plugin
configuration API for the default and a plugin-owned profile control alongside
native browser_exec.

Verify inventory additions, removals, renames and replaced directories, default
changes with active sessions, repeated selection, A/B/A switches, exact cleanup,
and isolation of same-profile and different-profile agents. Run the existing unit
and native four-agent acceptance plus multi-profile native fixtures. Keep source
and runtime evidence separate. Update installation and usage documentation, scan
the release, commit and push, and verify the remote revision and native loading.

Version 0.5.0 implements fresh directory-ID discovery and the chrome_profiles
control for list, select and set_default. Choices are agent/session scoped and
defaults use the existing profile_directory setting through the public writer.
An explicit switch retires the caller's old native connection and assigns a new
name, including A/B/A round trips. Repeating the current selection reuses it.

All 151 unit regressions pass. Native four-agent acceptance passes on one profile,
including Stop, input, screenshots, popups, exact cleanup and provider reload.
The separate multi-profile run verifies disjoint agent windows in two profiles,
default changes with active agents, repeated selection, round trips, in-flight
Stop, independent manual-fixture preservation and exact cleanup. It also verifies
tool unregistration and saved-default browsing after reload. Startup checks pass
from windowless Chrome and from a normal quit with zero windows and CDP clients.
The latter opens a different original profile in a new original Chrome process.

Native testing exposed the profile control's JSON result contract. Its registered
handler now serializes the result and has a regression test. A replaced-profile
preflight regression also reproduced incomplete cleanup before GUI launch.
Validation now runs before startup-file creation, and that cleanup case passes.
The new native script uses a canonical temporary Hermes home and releases native
driver caches before unregistering the provider, including on failed assertions.

Clean indexed-package validation passes with a safe source scan and matching
declared tools/hooks. All 14 native Browser Harness Python files retain their
distribution RECORD hashes. Account data and live observations stay in ignored
local evidence.

The installed Hermes gateway was reloaded through its native activation mechanism.
A fresh Hermes CLI session successfully listed profiles, opened Default and a
second existing profile through chrome_profiles and browser_exec, switched the
second session back to Default, and read back both sessions' actual profile IDs.
The peer session retained its native connection. The completed CLI process exited
successfully, and the external window monitor observed zero remaining windows.

Native Dock monitoring found a transient second application icon during startup.
The same observation reproduced with the existing 0.4.8 launcher. Direct binary
forwarding also reproduced it. The 0.5.0 verification left the single-Dock-icon
startup condition open. Its profile-routing and window-isolation results passed.

## Single Dock icon — approved 15 November 2026

Use the running original Chrome process for subsequent profile/window requests.
Replace forced LaunchServices instances with Chrome's local ProcessSingleton
notification for an already verified browser process. Verify its connected peer
PID, process creation time, and singleton nonce before sending startup arguments.
Use normal LaunchServices application startup when Chrome is stopped. Keep the
existing agent-owned window identification and actual profile-path verification.

Verify the launcher regression, malformed or changed IPC identity, fragmented and
failed acknowledgements, and exact selected-profile arguments. Monitor actual Dock
application items during cold, windowless, existing-window, same-profile and
multi-profile native tests. Retest native Hermes loading, agent isolation, manual
window preservation and cleanup before publishing this patch.

The history comparison covers d33aa03, ae83c2c, 0334304, 5c71477 and a91caec.
All contain forced-new-instance startup. The 0.4.8 and 0.5.0 startup files are
byte-identical. A plain warm LaunchServices experiment ignored the selected-profile
arguments and opened Chrome's profile picker. That experiment was removed from the
installed checkout. Verification continues in a separate development worktree.

Version 0.5.1 forwards warm requests through the verified original process's
ProcessSingleton socket. A private short socket alias supports Chromium's extended
macOS socket paths. Cold startup uses normal LaunchServices with the selected
profile arguments. Browser ownership and profile routing continue through the
existing provider and relay.

Controlled failure testing retains the verified endpoint identity for exact seed
cleanup. It reproduced a pre-existing post-close AXWindows read returning -25204.
The same code exists before multi-profile support. A bounded read-only observation
handles that transient result after the single close action. Regression tests
reproduce the failure and preserve unconfirmed results for other AX errors.

All 170 unit tests pass. Native four-agent and multi-profile acceptance pass,
including separate windows, Stop, round trips, saved defaults, exact cleanup,
manual-page preservation and reload. Cold startup passes with the default and
another existing profile, following normal quits with zero windows and CDP clients.
Windowless startup reuses the same original Chrome process. The controlled lost-
acknowledgement case confirms exact seed cleanup while preserving its peer.

The test machine has Chrome 157.0.8103.51 and one existing pinned Dock entry for
the original application. Native Dock monitoring observes one Chrome application
item throughout the tested startup and multi-agent phases. Profile-picker windows
remain absent from those observations. All 14 native Browser Harness Python files
retain their distribution RECORD hashes. Clean indexed-package validation and
secret scans pass.

The installed Hermes gateway reload succeeds. A fresh CLI task loads version 0.5.1
and uses its native chrome_profiles and browser_exec tools to read back the first
profile, a second profile, a switch back, and the preserved peer session. All four
browser calls succeed. External checks after task finalization confirm zero Chrome
windows and CDP clients before the final cold-start test.

The final native four-agent run starts after a normal quit of windowless Chrome.
It passes the same ownership, input, Stop, reload and cleanup checks in a new
original Chrome process. The final Chrome window count is zero. The separate
native package check verifies all 14 Browser Harness Python files again, and the
Hermes core checkout is clean at its original revision.

The complete observer log contains 16,939 valid Dock readings, each with one
Chrome application item, and zero observed profile-picker windows. The external
AX observer also records 84 Chrome-surface read errors and two incomplete Dock
readings. Successful native tool results and valid Dock readings establish the
reported acceptance results. Detailed logs remain in ignored local evidence.

## Profile guidance — approved 15 November 2026

Version 0.5.2 expands the model-facing chrome_profiles tool and parameter
descriptions. Explain fresh discovery, directory IDs, private agent/session
aliases, shared and different profiles, saved defaults, and the window cleanup
performed during a profile switch. Align the README and tutorial with those
descriptions.

Verify that the Python AST matches 0.5.1 after removing dictionary description
fields. Run the existing 170 unit tests, validate a clean package, scan the release,
and inspect the schema returned by Hermes's native tool_describe path. Verify the
installed description and remote Git revision after publication.

All 170 unit tests pass. The description-normalized Python AST matches version
0.5.1. Hermes's native tool_describe dispatcher returns the complete tool and
parameter descriptions from the new schema. The verification loads the plugin
in an isolated Hermes home and reads its model-facing definitions.

## Rencana profil dan integrasi Flow/Gemini — audit 15 November 2026

Status tahap ini adalah audit dan rancangan. Fitur pada bagian ini merupakan
pekerjaan implementasi berikutnya. Baseline browser yang diperiksa adalah 0.5.2.

### Hasil pemeriksaan kode

| Bagian | Perilaku yang sudah tersedia | Pekerjaan untuk kebutuhan terbaru |
| --- | --- | --- |
| Plugin browser | `chrome_profiles` menyediakan `list`, `select`, dan `set_default`. Pilihan tersimpan per agen/sesi bernama. Default dipakai saat sesi pertama kali browsing. Inventori membaca penambahan, penghapusan, rename, dan penggantian direktori. | Tambahkan aturan profil tetap, default per platform/subagent, dan pilihan acak sesuai pengaturan pengguna. |
| Konteks Hermes | Konfigurasi plugin mengikuti profil Hermes yang sedang melayani sesi. API publik menyediakan konteks sesi/platform serta hubungan parent/child. | Hubungkan aturan profil Chrome dengan konteks tersebut. Profil Hermes menyimpan konfigurasi agen. Profil Chrome merupakan direktori browser yang dipilih. |
| Flow mandiri | `next_profile()` menyegarkan inventori, memilih akun berikutnya, dan kembali ke awal urutan. Pemanggil menentukan saat berpindah berdasarkan kondisi Flow. | Tambahkan rolling otomatis pada pengendali layanan Flow dan simpan kelanjutan pekerjaan. |
| Gemini custom | `generate_with_profiles()` sudah menangani penolakan kuota, akun berbeda, dan handoff konteks/berkas. CLI mengaktifkannya melalui `--rotate-on-limit` pada `ask`/`reply`. | Perluas rolling ke operasi layanan yang diintegrasikan dan gunakan interaksi UI yang dipilih. |
| Pilot UI Gemini | Memiliki pemilihan tool, editor, unggahan, percakapan lanjutan, streaming, gambar/edit gambar, video, musik, dan tahapan Research. Sebagian hasil masih memakai pembacaan respons/riwayat lama di Chrome. | Adaptasi komponen sesuai operasi. Catat batas pilot, termasuk Argon/High, satu lampiran, serta hasil akhir Research yang masih pending pada catatan uji sumber. |

`profile_directory` saat ini merupakan default yang dapat diganti. Opsi tersebut
belum menerapkan penguncian profil per platform atau subagent. Pilihan per sesi
sudah memungkinkan agen utama dan child memakai profil berbeda melalui `select`.

Audit ini menjalankan 170 tes plugin, 118 tes Flow, dan 333 tes Gemini yang
mencakup routing, kuota, pilot UI, dan unggahan. Seluruhnya lulus secara offline.
Output uji memuat warning konfigurasi pytest-asyncio dan cleanup direktori temporer
implisit. Pengujian integrasi layanan di dalam plugin masih menjadi tahap berikutnya.

### Pemilihan profil browser umum

Gunakan pengaturan plugin dan kontrol profil yang sama untuk menyimpan aturan
berikut. Profil default yang sudah ada menjadi fallback untuk konfigurasi lama.

- Pilihan eksplisit untuk sesi atau agen tertentu.
- Binding profil untuk subagent yang ditentukan pengguna.
- Default atau binding platform, misalnya WhatsApp dan Telegram.
- Default yang diwarisi dari parent apabila child belum memiliki pilihan sendiri.
- Default global plugin.

Urutan tersebut merupakan usulan prioritas resolusi, dari paling khusus ke paling
umum. Binding subagent yang eksplisit mengalahkan default parent. Identitas sesi
dan parent/child berasal dari kontrak publik Hermes. Nama peran child dipakai
hanya bila menjadi aturan eksplisit pengguna. Format string ID internal menjadi
identitas opaque yang diteruskan apa adanya.

Pengaturan dapat memilih profil tetap, default yang dapat diganti, atau acak.
Profil tetap berlaku pada lingkup binding sampai pengaturannya diubah. Pilihan
acak dilakukan sekali saat sesi dibuat dari inventori yang masih valid. Sesi
tersebut kemudian memakai hasil pilihan itu sepanjang pekerjaannya. Beberapa
agen tetap dapat memperoleh profil yang sama dan masing-masing memiliki jendela.
Penguncian merupakan aturan pemilihan untuk lingkup tertentu, dengan kepemilikan
jendela yang tetap per agen/sesi.

Aturan yang tersimpan berlaku kembali pada turn berikutnya. Pilihan sementara
mengikuti umur sesi yang sekarang. Perubahan default dipakai oleh sesi baru.
Binding yang menunjuk profil terhapus menghasilkan laporan profil yang perlu
dipilih ulang. Inventori dan pemeriksaan identitas direktori dipakai kembali.

### Pemisahan browser umum, Flow, dan Gemini

Setiap agen memiliki sesi bernama tersendiri untuk browser umum, Flow, dan Gemini.
Contoh alias adalah `browser`, `flow`, dan `gemini`. Nama privat yang sekarang
dipakai plugin tetap mengikat setiap alias pada pemilik agen/percakapan/turn.

- Browser umum mengikuti binding/default/pilihan acak pada lingkupnya.
- Flow mempunyai profil awal, urutan kandidat, dan cursor rolling tersendiri.
- Gemini mempunyai profil awal, urutan kandidat, dan cursor rolling tersendiri.
- Rolling layanan menggunakan pemilihan profil pada sesi layanan tersebut.
  Default global disimpan hanya lewat tindakan pengubahan default pengguna.
- Agen utama dengan browser profil A dapat bekerja bersama child berprofil B.
  Pada waktu yang sama, Flow milik agen utama dapat bergulir ke C dan Gemini ke D.
  Seluruh sesi mempunyai jendela dan target milik masing-masing.

Keputusan layanan berasal dari entry point/helper Flow atau Gemini yang dipanggil.
Browsing URL kedua situs melalui sesi browser umum mengikuti aturan browser umum.
Binding browser umum pada A tetap memberi Flow/Gemini urutan layanan masing-masing.
Profil awal atau urutan khusus layanan mengikuti pengaturan pengguna jika tersedia.

### Rolling layanan ketika kredit atau limit habis

Rolling aktif pada entry point Flow dan Gemini untuk operasi layanan yang
diintegrasikan. Keputusan perpindahan dikerjakan kode pengendali layanan.
Panduan terbundel menjelaskan pemakaian dan cara membaca statusnya.

1. Mulai dari profil layanan yang dipilih. Ambil kandidat dari inventori Chrome
   terkini dalam urutan direktori alami, atau urutan yang ditentukan pengguna.
   Kandidat default mencakup seluruh profil yang dapat mengakses layanan terkait.
2. Gunakan akun aktif selama masih dapat melakukan operasi yang diminta. Saldo
   dapat dipakai sampai layanan menyatakan kredit/kuota habis atau tidak cukup
   untuk operasi tersebut. Kebijakan ini mengikuti otorisasi biaya pengguna.
3. Catat penolakan kuota yang benar-benar diamati, akun aktif, jenis operasi atau
   model yang terdampak, dan waktu pemulihan jika layanan menampilkannya. Informasi
   akun dari metadata Chrome menjadi petunjuk penemuan. Identitas akun layanan
   diperiksa pada situs yang sedang dipakai.
4. Setelah kuota habis terkonfirmasi, lanjutkan pekerjaan yang tersisa pada akun
   berikutnya. Profil berbeda yang sedang memakai akun layanan sama berbagi status
   kuota yang sama untuk operasi terdampak. Pemeriksaan ini mempertahankan
   kemungkinan beberapa agen memakai satu profil secara paralel.
5. Segarkan inventori sebelum memilih kandidat. Ikuti penambahan/penghapusan
   profil, perubahan akun aktif, dan pergantian identitas direktori.
6. Catat akun yang sudah diperiksa dalam putaran tersebut. Setelah seluruh kandidat
   habis, kembalikan status kuota habis beserta posisi pekerjaan dan informasi reset
   yang tersedia. Ketika ketersediaan pulih atau pekerjaan dilanjutkan, periksa lagi
   dari awal putaran sehingga profil pertama dapat dipakai kembali.

Status kuota disimpan menurut layanan, akun, dan operasi/model yang terdampak.
Setiap layanan memakai bukti kuotanya sendiri. Saldo bersama antarlayanan hanya
dianggap sama ketika sumber layanan benar-benar menunjukkannya.

Timeout, error CDP, kegagalan selector, dan respons yang masih ambigu masuk ke
diagnosis/rekonsiliasi permintaan asal. Permintaan yang sudah diterima mempertahankan
akun, proyek/chat, dan identitas hasil asal selama masih perlu dipantau atau diunduh.
Rolling menentukan tujuan pekerjaan berikutnya yang belum dijalankan atau yang
telah ditolak karena kuota. Hasil parsial yang sudah ada disimpan dan dipakai
untuk menentukan pekerjaan tersisa.

Pengendali layanan menyiapkan handoff dari konteks pekerjaan, instruksi yang masih
berlaku, pengaturan, dan berkas lokal yang tersedia. Pada akun tujuan, buka/buat
proyek atau chat tujuan, unggah kembali bahan yang diperlukan, dan ikat referensi
akun tujuan. ID proyek/chat/media dan riwayat native tetap milik akun sumber.
Koneksi asal dipertahankan selama pekerjaan yang sudah diterima masih memerlukannya.
Sesi bernama tambahan dapat memakai profil berikutnya sementara hasil asal ditunggu.

### Bentuk implementasi fitur situs

Fondasinya adalah provider Chrome plugin yang sekarang. Helper situs menerima
tab/koneksi milik sesi tersebut. Browser Harness menyediakan ekstensi
`agent_helpers.py`, dan Hermes menyediakan panduan terbundel melalui
`ctx.register_skill()`. Helper membaca DOM terkini secara terarah dan mengembalikan
pengaturan, status, atau hasil yang relevan. Pembacaan lebih luas membantu diagnosis
saat kontrol yang diharapkan berubah.

Rolling otomatis membutuhkan pengendali layanan tipis di dalam plugin. Pengendali
tersebut menghubungkan hasil helper, pemilihan profil, dan handoff pekerjaan.
Entry point layanan yang ringkas dapat didaftarkan melalui `ctx.register_tool()`
dan memanggil `browser_exec` lewat `ctx.dispatch_tool()` dengan identitas pemilik
yang sama. Penerusan task/session/turn, persiapan sesi privat plugin, dan pelaksanaan
hook tepat sekali harus dibuktikan sebelum transport ini dipilih untuk produksi.
`browser_exec` tetap menyediakan akses browser umum dan pemeriksaan UI yang fleksibel.

| Layanan | Perilaku yang dipertahankan dalam adaptor |
| --- | --- |
| Flow klasik | Pilih media/model, rasio, durasi, kualitas, jumlah hasil, unggah/reference/karakter/suara sesuai kontrol yang tersedia, Generate, pantau, dan ambil hasil asli. |
| Flow Agent | Pilih mode, kontrol yang tersedia, referensi, approval native sesuai pengaturan pengguna, percakapan/progres, dan hasil. Durasi/kualitas yang hanya berupa permintaan prompt dicatat sebagai permintaan. |
| Gemini | Pilih model/penalaran/tool, pasang lampiran, isi prompt, Kirim, ikuti chat yang sama, bedakan jawaban selesai dari streaming, lalu ambil gambar/video/media yang benar-benar dihasilkan oleh turn itu. |

Perilaku gambar/edit gambar dan video pada pilot Gemini menjadi acuan khusus yang
diminta pengguna. Pemilihan model memakai permintaan atau preset pengguna dan opsi
akun yang tersedia. Pembacaan respons aplikasi dapat melengkapi DOM ketika diperlukan
untuk streaming atau identitas hasil. Catat jalur UI dan pembacaan tambahan per fitur.
Rute rolling lama memakai SDK baseline. Penggabungan routing dengan pilot UI masih
merupakan pekerjaan implementasi dan verifikasi.

Repo Gemini yang diaudit mencantumkan AGPLv3. Plugin browser dan repo Flow memakai
MIT. Seleksi source Gemini untuk distribusi publik mencakup pemeriksaan asal-usul
kode dan lisensinya. Perilaku UI dapat dijadikan acuan bagi helper yang ditulis
untuk plugin. Pilih komponen interaksi situs secara terarah dari repo yang ada.

### Urutan pekerjaan dan penerimaan

1. Tetapkan binding profil dan ruang sesi layanan. Verifikasi prioritas aturan,
   pewarisan child, profil tetap/acak, perubahan inventori, dan isolasi enam agen.
2. Buktikan pengendali layanan melalui kontrak publik, termasuk identitas pada CLI,
   WhatsApp/Telegram, child, dan named session. Pertahankan penerusan konteks routed
   Hermes profile dan jalur konfigurasi publik plugin.
3. Tambahkan helper Flow dan Gemini serta panduan pemakaian yang terbundel. Uji
   pengaturan, unggahan, submit, hasil, dan unduhan melalui jendela milik sesi.
4. Hubungkan rolling otomatis. Fixture mencakup A -> B -> C, semua kuota habis,
   reset -> A, profil baru/dihapus, akun sama dalam beberapa profil, kuota berbeda
   antaroperasi, hasil parsial, dan permintaan yang masih belum pasti.
5. Buktikan handoff konteks/berkas dan hasil media sesuai mode/operasi yang diuji.
   Verifikasi sesi browser umum yang terikat A serta sesi layanan/agen lain selama
   salah satu layanan berganti profil, dihentikan, atau gagal.
6. Jalankan regresi startup Chrome mati/windowless/sudah dipakai, pemilihan profil
   langsung, satu ikon Dock, kepemilikan jendela, Stop, dan cleanup. Publikasi mengikuti
   pemeriksaan paket, lisensi, secret scan, Git bersih, dan SHA remote yang cocok.

Pengelolaan supervisor native Hermes mengikuti pembaruan resmi Hermes. Integrasi
menggunakan kontrak publik plugin dan komponen Chrome milik plugin.

### Sumber riset

- Konteks sesi dan hubungan child memakai kontrak lifecycle yang didokumentasikan.
  [Hermes observer hooks](https://hermes-agent.nousresearch.com/docs/developer-guide/observer-hooks)
- Konfigurasi, bundled skills, tool registration, dan dispatch memiliki API plugin.
  [Panduan plugin Hermes](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- Browser Harness memisahkan primitive CDP, helper workspace, dan domain skills.
  [Struktur upstream](https://github.com/browser-use/browser-harness/blob/main/AGENTS.md)
- Proyek komunitas Gemini menyediakan rujukan penemuan profil, pemilihan akun, dan
  pembacaan limit melalui UI. Pilihan lifecycle pada implementasi ini mengikuti
  provider plugin yang sudah diuji.
  [Google Gemini CLI](https://github.com/Zahed316/google-gemini-cli)

## Verification baseline

The 0.4.4 baseline passes 114 unit tests and native four-agent Chrome acceptance.
Coverage includes input/click, screenshots, iframe/shadow DOM, popups, existing
sign-in observations, overlapping operations, and peer-preserving cleanup.
Lifecycle transition tests use an isolated Hermes home. Simulated dependency
publication and gateway notifications in those tests are distinct from actual
plugin installation and reload checks.

The tested Hermes source revision is b200f5bc60e31588ba2cb60e288029c4a54ba5fa,
with browser-harness 0.1.13. Recheck compatibility when upgrading Hermes.

## Distribution preparation

Version 0.4.5 adds distribution documentation, licensing, and macOS dependency
markers. A fresh-install test reproduced a universal resolver conflict with
Hermes's Android psutil dependency. Qualifying this macOS plugin's requirements
keeps those constraints local to its supported platform. A manifest regression
test raises the unit-suite total to 115. Runtime implementation files retain the
tested 0.4.4 behavior.

Fresh-home native installation and enablement pass with the qualified requirements.
The newly built dependency environment passes all 115 unit tests and the native
four-agent local-fixture acceptance, including exact cleanup and stock harness
RECORD validation. All test-owned provider sessions close successfully.

- Document installation, permissions, configuration, operation, and lifecycle.
- Include the MIT license and a step-by-step tutorial.
- Keep examples and fixtures independent of personal accounts and local paths.
- Scan the release tree and reachable Git history for secrets and private identity.
- Validate a clean checkout through the native Hermes loader and regression tests.
- Verify the published Git revision against the reviewed revision.

## Known lifecycle behavior

Version 0.4.6 preserves the foreground window when native provider helpers request
CDP activation. Target routing and actions continue through owned attachments.
Cleanup marks each finishing agent while releasing the provider lock around native
I/O. Queued window creation rechecks closure under the shared consent guard, and
closed endpoints reject new clients. New targets retain `newWindow=True` and the
selected original profile.

All 121 unit tests pass. Native four-agent acceptance verifies disjoint Chrome
window IDs in one profile, input/click, screenshots, popups, and exact cleanup.
Real testing covers running Chrome without windows and with an independent manual
fixture window. The foreground fixture stays selected during a native new-window,
typing, screenshot, and bring-to-front sequence. Cold startup received code review.
These live runs began with the user's original Chrome already running.

Version 0.4.7 records the task-local route for each admitted native browser name.
A dedicated Stop callback matches Hermes's `session_key` payload and closes only
its snapshot of owned names. Creation of finalized native names is rejected.
Hermes's existing turn identity separates replacement names from delayed calls.
The README describes the English and Indonesian debugging-dialog matching.

All 126 unit tests pass. The native four-agent test now sends the actual Stop
payload, verifies exact cleanup and peer/manual preservation, rejects late native
creation, and confirms a replacement turn can browse with an independent name.

Version 0.4.8 removes all six private Hermes helper imports introduced by
`d33aa03` and `ea4754b`. Runtime integration uses the documented BrowserProvider,
configuration, task-local session context, and CDP supervisor APIs. The plugin
cleans its own Chrome targets and relay. Hermes manages its native driver
processes and session cache through its own lifecycle.

All 128 unit tests pass, including a public-runtime-import regression check.
Native four-agent acceptance verifies separate windows in one profile, Stop
during an in-flight request, late-session rejection, replacement turns, and exact
target cleanup. An independent simulated manual window retains its page and input.
All 14 native harness Python files match their package RECORD hashes.

Removing private cache cleanup exposed same-turn provider reload reusing a retired
endpoint. A native test reproduced the failure. Including provider-instance
identity in native session names keeps reload independent of Hermes's private
cache management. Unit and native tests cover browsing again after reload.

The user also completed a cold-start browse successfully on 14 November 2026.
Hermes's successful browser_exec result and the new original Chrome process start
corroborate that manual run. Automated runs for this patch began with Chrome
running without windows and added independent fixture windows.

Hermes manages plugin activation and browser selection separately. Select Local
in its browser picker before disabling or removing this provider. Apply the
supported plugin reload when the active Hermes surface requires it.

Cleanup recovery records live in process memory. A process that ends before
cleanup succeeds can leave an owned tab behind. Shared-profile website storage
follows Chrome's normal profile-wide behavior.
