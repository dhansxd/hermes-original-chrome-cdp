# Serah-terima proyek Original Chrome for Hermes

Diperbarui pada 16 November 2026 untuk persiapan reset Mac milik pengelola proyek.

**Titik lanjut saat ini.** Baca [AGENTS.md](AGENTS.md) dan
[kontrak aktif PLAN.md](PLAN.md#kontrak-browser-dan-ekstensi) terlebih dahulu.
Serah-terima di bawah merekam baseline sebelum reset. Pada cabang perombakan,
browsing umum serta kontrol situs memakai `browser_exec` di halaman yang sama.
Contoh `browser_app` di bawah merekam cara pemanggilan pada versi lama.
[Hasil audit](PLAN.md#hasil-audit-acuan) dan
[rencana perbaikan](PLAN.md#urutan-perbaikan-dan-verifikasi) memuat hasil diskusi terbaru.

## Status saat dijeda

**Pengembangan lanjutan dijeda atas permintaan pengguna.** Tugas terakhir adalah
menyimpan kode, spesifikasi, keputusan, catatan dan petunjuk pemulihan ke GitHub.
Pekerjaan berikutnya menunggu pengguna meminta proyek dilanjutkan. Gemini,
penambahan fitur Flow, dan produksi film mengikuti jeda tersebut.

| Acuan | Nilai |
| --- | --- |
| Repo utama publik | <https://github.com/dhansxd/hermes-original-chrome-cdp> |
| Branch pengembangan utama | `main` |
| Baseline kode terakhir sebelum dokumentasi serah-terima | `6769518ccb7f0aae850a218b5ac310d7c5813ec6` |
| Versi plugin | `0.10.3` |
| Paket situs tersedia | Flow `0.3.0`, delapan file pada `site_apps/flow` |
| Paket Gemini | Masih dalam daftar implementasi terbuka |
| Baseline Hermes yang diuji | `b200f5bc60e31588ba2cb60e288029c4a54ba5fa` |
| Baseline Browser Harness yang diuji | `0.1.13`, 14 source Python cocok dengan RECORD |
| Lisensi repo ini | MIT |

Baseline menunjuk kode yang menghasilkan penerimaan terakhir. Commit dokumentasi
sesudahnya membawa dokumen ini dan pembaruan petunjuk melanjutkan. SHA terbaru
dapat diperiksa dengan `git log -1` dan daftar commit GitHub.

## Urutan membaca

1. Baca [AGENTS.md](AGENTS.md) dan bagian aktif [PLAN.md](PLAN.md)
   untuk aturan kerja, keputusan terbaru dan checklist terbuka.
2. Baca dokumen ini untuk riwayat keputusan, baseline dan langkah pemulihan.
3. Periksa commit dan bukti terakhir untuk bagian yang akan dikerjakan.
4. Gunakan [README.md](README.md) dan [tutorial](docs/TUTORIAL.md) untuk pemasangan,
   konfigurasi, lifecycle dan penggunaan.
5. Baca [kontrak rolling](docs/ROLLING.md) serta
   [panduan Flow](site_apps/flow/SKILL.md) sebelum mengubah operasi situs.

Dokumen kebutuhan dan checklist dipusatkan pada PRD tersebut. Informasi proyek
untuk melanjutkan pengembangan tersedia dalam repo tanpa bergantung pada riwayat
chat, direktori `state`, atau ingatan agen di komputer lama.

## Tujuan dan keputusan pengguna

### Browser dan profil

- Hermes memakai Google Chrome asli yang terpasang di macOS melalui CDP, dengan
  profil asli dan login yang dikelola Chrome. Cookie dan profil tetap berada
  pada penyimpanan Chrome pengguna.
- Pembukaan langsung menuju profil terpilih. Jendela pemilihan profil harus
  tetap tertutup. Penggunaan aplikasi Chrome menghasilkan satu ikon Chrome
  di Dock, termasuk ketika ikon aplikasi sudah terpasang di Dock.
- Startup mencakup Chrome mati total, Chrome hidup tanpa jendela, serta Chrome
  hidup dengan jendela agen lain atau jendela manual.
- Satu sesi agen mendapat satu jendela awal. Halaman untuk izin CDP dan
  pemeriksaan profil menjadi halaman kerja sesi tersebut. Target tambahan
  mengikuti permintaan operasi dan tetap dimiliki sesi yang membuatnya.
- Banyak agen dapat memakai satu profil yang sama atau beberapa profil secara
  bersamaan. Setiap sesi mempunyai jendela sendiri. Stop, perpindahan profil,
  penyelesaian dan cleanup menjaga target agen lain serta pemakaian manual.
- Inventori profil dibaca dinamis dari metadata Chrome. Penambahan, penghapusan,
  penggantian direktori dan perubahan nama profil harus ditangani sesuai hasil
  inventori terkini. Pembuatan dan penghapusan profil dilakukan melalui Chrome.
- Pengguna dapat mengatur default, pilihan per sesi/agen, aturan profil tetap
  atau acak, platform seperti WhatsApp/Telegram, dan pewarisan parent/child.
  Penggunaan satu profil bersama tetap tersedia setelah penambahan multiprofil.

Profil bersama mengikuti perilaku login dan penyimpanan Chrome bersama.
Logout atau perubahan data situs pada profil itu dapat memengaruhi sesi lain.
Kepemilikan target memberi pemisahan jendela serta routing perintah. Kode Python
agen dan extension berjalan dengan izin proses Hermes.

### Plugin dan extension situs

- Satu plugin Hermes menyediakan browser, profil, CDP, isolasi sesi dan cleanup.
  Integrasi memakai kontrak plugin Hermes yang didukung. Core Hermes dan source
  dependency yang dikelola Hermes dipertahankan.
- Plugin mendukung install, enable, disable, update dan remove melalui pengelola
  resmi Hermes. Pada versi 0.11.1 pengguna masih memilih browser melalui picker
  Hermes. [Kontrak aktif](PLAN.md#kontrak-browser-dan-ekstensi) mewajibkan
  enable memilih Chrome asli serta disable atau remove memulihkan pilihan
  browser sebelumnya secara otomatis. Pekerjaan ini masih terbuka di PLAN.
- Pada baseline sebelum reset, `browser_exec` adalah tool browser native Hermes,
  `chrome_profiles` mengatur profil, dan `browser_app` memuat paket situs.
  [Kontrak aktif](PLAN.md#kontrak-browser-dan-ekstensi) menempatkan kontrol
  situs di halaman aktif `browser_exec`.
- Extension situs berada di direktori pengguna di luar instalasi plugin.
  Pengguna bersama agennya dapat menambah atau memperbarui paket situs tanpa
  mengubah instalasi host. Paket awal yang direncanakan adalah Gemini dan Flow.
  Situs lain dapat ditambahkan melalui kontrak paket yang sama ketika diminta.
- Flow dan Gemini memakai browser context dari host. Lifecycle Chrome serta
  pemilihan profil tetap menjadi tanggung jawab plugin.
- Perilaku UI Gemini custom menjadi acuan operasi situs. Gunakan interaksi UI
  dan pembacaan DOM terarah. Pertahankan dokumen/jendela selama pekerjaan
  berlangsung. Navigasi, pembacaan ulang DOM dan pemulihan dilakukan sesuai
  kebutuhan langkah serta hasil inspeksi.
- Pada cabang aktif, Hermes membaca panduan operasi dari schema `browser_exec`,
  aksi `describe` melalui `site_control`, dan `SKILL.md` dalam paket.

### Rolling dan hasil produksi

- Rolling Flow dan Gemini terpisah dari kebijakan profil browsing umum dan
  terpisah antar layanan. Kredit/kuota akun dipakai sampai provider menunjukkan
  operasi yang diminta sudah kehabisan kuota, lalu pekerjaan diteruskan ke profil
  tersedia berikutnya. Inventori dinamis dan identitas akun mencegah pengulangan
  akun layanan yang sama melalui dua profil.
- Profil awal dapat dikunjungi kembali setelah ada bukti kuota tersedia lagi.
  Pengaturan urutan profil dan cursor kelanjutan mengikuti kontrak rolling.
- Pengguna mengizinkan pemakaian seluruh kredit, generation untuk pengujian dan
  produksi, serta pilihan native Agent untuk selalu menyetujui. Implementasi
  mengikuti pilihan itu. Pengingat biaya dapat memberi informasi. Batas kredit
  buatan dan persetujuan tambahan memerlukan arahan pengguna.
- Timeout dan hasil ambigu direkonsiliasi memakai job, akun sumber dan receipt
  yang sama. Simpan intent sebelum submit dan receipt sesudah diterima provider.
  Pengulangan generation mengikuti kepastian hasil permintaan sebelumnya.
- Kelanjutan lintas akun membawa konteks, pengaturan, definisi karakter/suara,
  file lokal, hasil yang selesai dan jumlah pekerjaan tersisa. Proyek serta ID
  aset tujuan dibuat pada akun tujuan. ID dan riwayat native mempunyai pemilik
  akun asal masing-masing.
- Hasil nyata memerlukan file asli, identitas hasil sesuai permintaan, hash,
  metadata dan pemeriksaan decode. Kualitas cerita, konsistensi karakter,
  ekspresi, dialog dan blocking adegan diperiksa pada pekerjaan produksi.

Produksi Layan dan Shadow pernah menjadi uji di fase sebelumnya. Pengguna telah
mengesampingkan produksi film untuk fokus pada implementasi. Film 21 shot serta
cerita percakapan di rumah tetap dijeda. Jika produksi itu diminta kembali,
dialognya memakai amiyyah Mesir, posisi duduk/interior konsisten lintas angle,
ekspresi mengikuti pemicu adegan dan karakter memperhatikan lawan bicara.

### Cara bekerja pada proyek

- Ikuti tujuan dan fitur yang diminta, gunakan perubahan sekecil yang memenuhi
  kebutuhan, dan periksa implementasi serta commit sebelumnya saat ada regresi.
- Nyatakan asumsi yang berpengaruh dan kriteria lulus yang dapat diperiksa.
  Gunakan kembali fungsi yang sudah ada dan sesuaikan verifikasi dengan dampak
  perubahan.
- Pisahkan pekerjaan fondasi browser, operasi situs dan produksi konten.
  Kesalahan konten generation serta kesalahan API/UI dicatat dengan atribusi
  sesuai bukti.
- Laporkan kegagalan nyata dan status pengujian secara akurat. Perbaikan baru
  mengikuti arahan pengguna pada tugas yang sedang berlangsung. Pengguna pernah
  meminta temuan produksi dilaporkan sebelum diperbaiki.
- Ikuti `AGENTS.md`, bekerja sendiri untuk proyek ini, dan gunakan fixture lokal
  untuk verifikasi browser. Penerimaan media memerlukan tugas produksi yang
  sedang diotorisasi pengguna.
- Commit, push dan verifikasi SHA remote untuk perubahan yang dipublikasikan.
  Source publik, dokumentasi dan riwayat harus bersih dari kredensial, identitas
  pribadi, data browser, media pribadi dan log runtime.
- Pengguna memilih menunggu update resmi untuk masalah supervisor native Hermes
  yang tercatat pada PRD. Arah ini menjadi acuan saat mengevaluasi temuan itu.

## Peta kode dan kontrak

| File/direktori | Tanggung jawab |
| --- | --- |
| `plugin.py`, `plugin.yaml`, `__init__.py` | Registrasi BrowserProvider, tools, hooks, lifecycle dan manifest |
| `startup.py`, `cdp_peers.py` | Peluncuran Chrome asli, ProcessSingleton dan pemeriksaan identitas peer |
| `consent.py`, `input_guard.py` | Izin debugging native dan pemeriksaan input/fokus milik plugin |
| `relay.py` | Relay CDP lokal, kepemilikan target, bootstrap halaman awal dan normalisasi keyboard |
| `profiles.py`, `profile_rules.py` | Inventori asli, pilihan/default dan resolusi aturan profil |
| `browser_apps.py` | Pemuat paket eksternal, context pemilik, lifecycle, checkpoint dan katalog |
| `rolling.py` | Jurnal job, lease, receipt, rolling, deduplikasi akun dan recovery |
| `site_apps/flow` | Template Flow, UI, referensi, karakter/suara, persiapan tujuan dan unduhan |
| `tests/test_*.py` | Regresi otomatis tanpa operasi produksi |
| `tests/live_*.py`, `tests/native_windows.py` | Penerimaan native Chrome, lifecycle, profil, extension dan rolling |

Paket pengguna default berada di `~/.hermes/browser-apps/<id>`. Setiap paket memakai
`app.json`, `app.py`, dan panduan opsional `SKILL.md`. Source dimuat pada panggilan
berikutnya dan terikat context agen pemiliknya. Penemuan awal menyalin template
Flow apabila paket tersebut belum tersedia, dengan menghormati pilihan lifecycle
serta source pengguna yang sudah ada.

Artifact, checkpoint, hasil dan jurnal rolling berada di direktori data plugin
yang disediakan Hermes, terpisah dari source paket. Pada baseline lama, `browser_app describe`
mengembalikan `data_directory` serta job milik percakapan yang dapat dipulihkan.
Konfigurasi berada pada profil Hermes aktif dan dapat memakai lokasi `HERMES_HOME`
yang berbeda. Detail itu perlu diperiksa pada instalasi tujuan.

## Implementasi dan penerimaan terakhir

### Fondasi browser

- Plugin `0.10.3` tersedia pada branch publik `main` dan sudah diaktifkan pada
  runtime lokal melalui mekanisme reload resmi Hermes sebelum jeda.
- Inventori/default/profil per sesi, aturan profil, extension eksternal serta
  rolling generik tersedia. Disable/remove mempertahankan checkpoint/artefak
  sesuai kontrak lifecycle yang terdokumentasi.
- Baseline `6769518` memperbaiki dua jendela awal dengan menyerahkan seed page
  satu kali kepada bootstrap driver. Pemeriksaan identitas/profil selesai
  sebelum handoff, dan permintaan target tambahan membuat target sendiri.
- Commit yang sama mengatasi jendela Tentang Mac Ini. Browser Harness `0.1.13`
  menyalin angka Windows ke `nativeVirtualKeyCode` macOS. Relay menghilangkan
  field yang mencerminkan encoding Windows itu, mempertahankan key/code,
  modifier, text, perintah editor dan encoding native eksplisit yang berbeda.
- Host `0.10.2` sebelumnya memperbaiki penolakan context ID profil persisten
  setelah last-used profile berubah. Jalur fallback membuka profil eksplisit
  melalui singleton yang identitasnya sudah diverifikasi.

### Flow

- Template `0.3.0` menyediakan `inspect`, `create_project`, `configure`,
  `generate_image`, `generate_video`, `upload`, `bind_reference`, `create_voice`
  dan `create_character`. Schema terkini tersedia pada `app.json` dan `describe`.
- Mode klasik dan Agent memiliki bukti gambar/video asli, referensi unggahan,
  Ingredients/Frames, karakter tersimpan dan suara kustom.
- Kontrol klasik mengikuti pilihan yang disediakan model. Agent mempunyai
  default model/rasio/jumlah hasil serta instruksi. Durasi dan resolusi Agent
  pada UI yang diuji merupakan permintaan prompt, dengan hasil diukur dari file.
- Rolling akun nyata mode klasik dan Agent lulus pada host `0.10.1`. Tujuan
  membuat proyek serta referensi miliknya, dan menghasilkan MP4 `720 × 1280`,
  video lima detik serta audio AAC. Hash dan decode penuh lulus.
- Hermes chat CLI juga menjalankan generation dan rolling Agent. Suara kustom
  menghasilkan WAV yang terdekode. Penilaian aksen, timbre dan naturalness
  mengikuti evaluasi pengguna atas sampel aslinya.
- Host `0.10.3` diuji melalui Hermes untuk inspeksi klasik → Agent → klasik
  pada satu dokumen. Hasil media di atas memiliki baseline penerimaan yang
  dicatat masing-masing pada PRD.

### Bukti terukur

| Pemeriksaan | Hasil tersimpan dalam PRD |
| --- | --- |
| Unit/regresi host `0.10.3` | 342 lulus |
| Startup Chrome cold/windowless/warm | Ketiga suite lulus, satu jendela awal per sesi |
| Profil, extension, rolling, enam pemilik native | Seluruh suite lulus pada profil sama serta campuran dua profil |
| Enam pemilik | Enam identitas task/conversation native melalui registry, satu jendela awal masing-masing |
| Input, Stop, akhir turn, target tambahan dan cleanup | Peer/manual terpelihara dan inventori kembali ke baseline |
| Probe pembanding keyboard | 1.212 event, nol event AboutThisMac pada encoding yang dinormalisasi |
| Inspeksi Flow melalui Hermes `0.10.3` | 657 inventori, maksimum satu jendela kerja tambahan, satu `time_origin`, peer `KEEP` terpelihara, inventori akhir nol |
| Dock selama penerimaan `0.10.3` | 13.171 sampel valid, masing-masing satu ikon Chrome, nol error baca |
| Log macOS sejak penerimaan terakhir | Nol event AboutThisMac dari Chrome |
| Distribusi bersih sebelum jeda | Validator Hermes safe, tanpa core override, scan secret dan identitas lulus |

Sebagian pengukuran awal AX sempat gagal sementara. Helper pengujian sekarang
mengamati ulang error AX yang dikenal dalam deadline tiga detik yang sudah ada,
mewajibkan inventori valid dan menggagalkan error persisten. Pengulangan akhir
inspeksi Hermes mempunyai nol gangguan baca. Pengamatan sisa jendela yang pernah
dilaporkan pengguna kemudian diklarifikasi sebagai layar kedua yang membeku.

Penerimaan enam identitas memakai fixture native registry. Penerimaan pesan kanal
nyata serta delegasi percakapan LLM penuh tetap mengikuti checklist terbuka.
Sampel pengukuran mempunyai cakupan waktu dan versi yang tercatat.

## Pekerjaan terbuka saat jeda

| ID PRD | Sisa pekerjaan |
| --- | --- |
| `EXT-01` | Template Gemini sebagai paket awal. Pemuat eksternal dan template Flow sudah tersedia. |
| `CTX-01`, `PRO-02` | Penerimaan melalui pesan kanal nyata, delegasi child nyata dan konfigurasi Hermes yang terpisah. Routing sintetis dan CLI sudah mempunyai bukti. |
| `GEM-01`–`GEM-05` | Implementasi paket Gemini untuk chat/model, upload/streaming/cancel, gambar, video dan rolling UI. |
| `FLO-04` | Mengamati reset/isi ulang kuota provider nyata, lalu kembali ke profil awal. Rolling akun habis ke akun tujuan sudah lulus. |
| `LIF-03` | Browser umum, Flow, Gemini dan manual bersamaan, sesudah paket Gemini tersedia. |
| `REL-01`–`REL-04` | Penerimaan rilis untuk kedua paket awal, update, panduan lengkap dan asal-usul/lisensi. Bukti rilis host/Flow yang sudah lulus tetap tercatat. |

Source Gemini mencantumkan AGPLv3. Host dan Flow berlisensi MIT. Periksa komponen
yang akan dipakai serta ketentuan distribusinya ketika Gemini dikerjakan. Catatan
pembatalan paralel Gemini juga mempunyai satu target pra-uji yang hilang tanpa
atribusi lengkap. Reproduksi terarah diperlukan untuk menetapkan penyebabnya.

Masalah reconnect supervisor native sesudah endpoint ditutup mengikuti update
resmi Hermes sesuai keputusan pengguna. Kompatibilitas Chrome, macOS dan API
publik Hermes perlu diuji saat versinya berubah. Bahasa dialog debugging yang
sudah dikenali adalah Inggris dan Indonesia. Crash atau penghentian paksa proses
sebelum cleanup selesai dapat menyisakan target yang perlu diperiksa pemiliknya.

Jika pengguna meminta melanjutkan, mulai dari checklist terbuka yang mereka
pilih, periksa diff sejak baseline dan gunakan pemeriksaan yang sesuai dampaknya.
PRD memuat urutan pengembangan. Status jeda ini berlaku sampai arahan lanjut.

## Referensi source yang sudah tersimpan di GitHub

| Repo | Commit/acuan yang diverifikasi | Penggunaan |
| --- | --- | --- |
| [Plugin ini](https://github.com/dhansxd/hermes-original-chrome-cdp) | `main`, baseline kode `6769518ccb7f0aae850a218b5ac310d7c5813ec6` | Produk aktif dan sumber instalasi plugin/Flow |
| [Gemini-API](https://github.com/dhansxd/Gemini-API) | `main` pada `957aed50f0352dba7b076871ce689fdbb682a4a0` | Repo privat pembanding Gemini, termasuk PLAN dan audit pilot UI |
| [google-flow-cdp](https://github.com/dhansxd/google-flow-cdp) | `main` pada `79d810a7c21953b95b2b2b7fde546a45689b850e` | Repo publik pembanding sesi Flow terminal |
| [google-flow-api](https://github.com/dhansxd/google-flow-api) | `main` pada `022be9c05d48770bfd37f37124ecb01698c92368`, branch `feat/flow-browser-session-20261114` pada `1b5a98ca9dd94daa0867a07a27f280023fa906f6` | Arsip privat implementasi Flow sebelumnya dan catatannya |

Repo privat memerlukan login GitHub pengelola setelah reset. Referensi tersebut
menyediakan bahan pembanding untuk pekerjaan berikutnya. Instalasi plugin dan
paket Flow saat ini berasal dari repo publik utama.

## Audit penyimpanan sebelum reset

Audit tanggal dokumen ini memeriksa checkout plugin terpasang, branch, worktree,
stash, source paket eksternal serta repo pembanding yang relevan.

- Seluruh 97 commit plugin sebelum dokumen ini sudah reachable pada `main`
  GitHub. Seluruh branch lokal plugin merupakan ancestor `main`.
- Seluruh worktree plugin bersih dari perubahan source yang belum di-commit.
  Tiga worktree lama memiliki `.DS_Store` sebagai file lokal tambahan.
- Stash plugin kosong. Clone publik lama pada direktori proyek juga bersih dan
  berada pada commit yang sudah tercakup riwayat `main` terbaru.
- Delapan file paket Flow yang terpasang pada direktori extension pengguna
  cocok byte-per-byte dengan template `site_apps/flow`. Direktori paket pengguna
  saat audit hanya berisi Flow.
- Checkout Gemini dan seluruh worktree Flow pembanding bersih. Seluruh branch
  Gemini tercakup `main` privat. Branch tambahan Flow yang membawa sesi browser
  sudah tersedia di remote privat. Commit historis lainnya tercakup main atau
  branch remote yang diperiksa.
- Catatan kebutuhan utama berada pada `PLAN.md`, README, tutorial, kontrak
  rolling dan panduan paket. Enam catatan diagnostik lokal lama dipertahankan
  dalam bentuk tersanitasi pada `docs/history`, beserta ringkasan berikut.
- Direktori `state`, log/receipt mentah, snapshot source sementara, browser data,
  media pribadi dan environment instalasi merupakan data lokal di luar paket
  publik. Prosedur serta hasil yang dibutuhkan untuk pengembangan dirangkum di
  dokumen ini, PRD dan suite yang terlacak Git.

### Pemeriksaan paket serah-terima

- Ekspor bersih dari index Git berisi 58 file, termasuk dokumen ini dan enam
  laporan historis yang sudah disanitasi.
- Sebanyak 342 tes otomatis lulus pada checkout kerja dan ekspor source bersih.
- Validator Hermes pada ekspor bersih lulus dengan security scan `safe`, schema
  sesuai registrasi dan pemeriksaan tanpa core override.
- Scan Gitleaks pada riwayat Git, perubahan staged dan ekspor source lulus.
  Pemeriksaan path/identitas pribadi serta tautan dokumen lokal juga lulus.
- HEAD dan seluruh 51 file pada tree baseline sebelum dokumentasi dibandingkan
  dengan GitHub dan cocok. Source Hermes tetap bersih pada commit baseline.
- Sesudah push `ba0982801372b6c4102e894381ccc83959b38cc1`, clone publik baru
  tanpa credential helper berhasil memulihkan 58 file serta 98 commit. Seluruh
  isi file cocok dengan checkout asal. Validator Hermes `safe`, 342 tes dan
  scan secret riwayat lulus dari clone tersebut. Unduhan publik dokumen ini
  pada SHA itu mengembalikan HTTP 200 dan byte yang sama. Clone memakai
  environment Hermes pada Mac yang sedang berjalan. Penerimaan pada Mac
  sesudah reset mengikuti langkah pemulihan di bawah.

Validator yang diarahkan ke seluruh direktori instalasi lama juga membaca file
diagnostik di luar Git. Pada lokasi itu terdapat diagnostic `caution` untuk
salinan HTML riset dan import internal pada runner sekali pakai di `state`.
Validasi distribusi memakai ekspor Git bersih agar memeriksa isi yang benar-benar
diterbitkan. Hasil `safe` di atas berasal dari paket bersih tersebut.

### Catatan diagnostik historis yang dipertahankan

Enam catatan berikut berasal dari fase arsitektur lama `0.1.8`. File seperti
`observer.py`, `worker.py`, `binding.py`, `vendor/helpers.py` dan `vault_adapter.py`
menggambarkan desain pada fase tersebut. Baseline `0.10.3` memakai provider native
serta relay yang dipetakan di atas. Catatan ini menyimpan penyebab, hasil dan
pelajaran diagnosis untuk menafsirkan riwayat.

| Catatan lokal lama | Isi substantif dan hasil historis |
| --- | --- |
| [VAULT-API-REPAIR.md](docs/history/vault-api-repair.md) | Registrasi vault upstream digabung menjadi satu tool dan nama lama gagal dimuat. Adapter serta schema saat itu disesuaikan. 24 tes vault dan 107 tes lengkap lulus, dengan fixture kredensial sintetis pada target tepat serta preservasi comparator. Aktivasi chat masih menunggu restart pada saat catatan ditulis. |
| [RESILIENCE-RESULT.md](docs/history/resilience-report.md) | Registrasi vault yang gagal dipisahkan dari provider, helper snapshot milik plugin dipakai oleh worker, dan fault injection loader namespaced ditambahkan. 112 tes serta tujuh fixture GUI disposable lulus. Chat native kemudian berhasil membaca halaman dua kali dan finish. Source pin serta pemeliharaan snapshot merupakan batas arsitektur lama. |
| [TIMEOUT-REPAIR-RESULT.md](docs/history/idle-timeout-repair.md) | Antrean event WebSocket yang penuh menahan pembacaan keepalive saat idle. Observer lama mendapat satu pemompa receive dengan lock bersama request, peminjaman vault dan finish. Kegagalan keepalive direproduksi pada traffic nyata saat jeda antarpanggilan. Hilangnya koneksi diakhiri tanpa replay. Catatan itu hanya mengatribusikan gejala yang direproduksi. |
| [RESUME-TIMEOUT-REPAIR-RESULT.md](docs/history/resume-timeout-repair.md) | Auto-attach lama mengirim `Runtime.runIfWaitingForDebugger` ke halaman tak terkait meskipun `waitingForDebugger=false`. Renderer tak responsif menahan setup pertama. Perubahan observer membatasi resume pada keadaan yang sesuai. Red/green melalui profil asli menghasilkan pembacaan pertama serta kedua yang benar dan tepat satu pembuatan target. Aktivasi runtime masih menjadi langkah tersendiri saat laporan awal dibuat. |
| [EVENT-OVERFLOW-REPAIR-RESULT.md](docs/history/event-overflow-repair.md) | Flag global overflow pada buffer 4.000 event meracuni metadata semua sesi. Gap lalu diatribusikan ke held session yang kehilangan event. Metadata terkini tetap terbaca, riwayat yang rusak dilaporkan eksplisit, detach dilacak terpisah dan gap worker diteruskan. 126 tes dan fixture overflow/vault/dialog/popup lulus. |
| [NATIVE-TIMEOUT-ACCEPTANCE.md](docs/history/native-timeout-acceptance.md) | Setelah restart pemilik, native `browser_exec` berhasil menavigasi, membaca ulang setelah idle, dan membaca metadata sesudah burst 3.000 fetch lokal. Pembacaan riwayat yang sudah hilang menghasilkan diagnostic eksplisit. Sesi baru membaca halaman situs terautentikasi dengan login tetap ada. Tugas video masih dijeda. |

Arsip mempertahankan isi laporan asal dengan penyuntingan identitas pribadi dan
penanda bahwa arsitekturnya historis. Pelajaran yang dipertahankan adalah
reproduksi pada jalur native sebenarnya,
atribusi event per pemilik, pembacaan observasi yang terserialisasi, pembedaan
source terpasang dengan source aktif, serta pemeriksaan receipt sebelum tindakan
yang mungkin sudah dijalankan diulang. Ringkasan historis ini menghilangkan path
pribadi, URL proyek pribadi dan ID target produksi dari laporan lokal asalnya.

Runner sekali pakai di `state/dynamic-profiles`, `state/parallel-acceptance`,
`state/single-window*` dan `state/flow-*` mengoordinasikan fase startup, pengukur
Dock, probe keyboard, inspeksi Hermes dan laporan media. Perilaku yang diuji
tercakup pada suite terlacak dan prosedur penerimaan di PRD. Path interpreter,
home uji, identitas akun, query dan receipt pada runner lokal mengikuti mesin
lama. Gunakan suite serta schema paket terkini saat mereproduksi hasil.

## Memulihkan proyek setelah reset Mac

### Ambil source dan baca titik lanjut

Pasang Git, Google Chrome asli dan Hermes dengan dukungan BrowserProvider pada
Mac tujuan. Petunjuk pemasangan Hermes tersedia pada dokumentasi proyek Hermes
yang ditautkan README. Clone repo ini untuk mendapatkan kode, riwayat dan dokumen.

```sh
git clone https://github.com/dhansxd/hermes-original-chrome-cdp.git
cd hermes-original-chrome-cdp
git status --short
git log -1 --oneline
```

Baca `HANDOFF.md`, `AGENTS.md` dan `PLAN.md`. Baseline kode sebelum jeda dapat
dibandingkan melalui `git show 6769518ccb7f0aae850a218b5ac310d7c5813ec6`.

### Siapkan Chrome serta Hermes

1. Buat atau login kembali ke profil asli Chrome yang diinginkan pada Mac tujuan.
   Identitas direktori profil dapat berbeda setelah reset.
2. Buka `chrome://inspect/#remote-debugging` dan aktifkan remote debugging.
3. Berikan Accessibility kepada aplikasi yang benar-benar meluncurkan Hermes.
4. Install dan aktifkan plugin melalui pengelola Hermes.

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-cdp
hermes plugins enable original-chrome-default
hermes tools
```

Pilih **Original Chrome · CDP**, aktifkan Browser Automation dan Terminal pada
permukaan Hermes yang akan dipakai, lalu ikuti kebutuhan aktivasi/reload yang
dilaporkan Hermes. Gabungkan konfigurasi contoh pada README ke config profil
Hermes aktif. Gunakan hasil `chrome_profiles list` untuk memilih direktori nyata
dan mengatur default, aturan per layanan serta urutan rolling yang diinginkan.

Untuk Flow, pasang FFmpeg beserta ffprobe pada PATH proses Hermes. Pada cabang
aktif, panggil aksi `list` lalu `describe` untuk `flow` melalui parameter
`site_control` pada `browser_exec`. Penemuan awal
menyiapkan source template eksternal. Panduan dalam paket menjelaskan parameter
yang sesuai versi terpasang. Source Gemini privat dapat di-clone dengan akun
GitHub pengelola ketika implementasinya dilanjutkan.

### Periksa pemulihan sesuai kebutuhan

```sh
hermes plugins list
hermes plugins validate .
hermes --run-module unittest discover -s tests -p 'test_*.py'
```

Jalankan dua perintah terakhir dari checkout repo dengan environment Hermes yang
tersedia. Untuk penerimaan native, gunakan Python environment Hermes beserta
module Hermes pada import path sebagaimana panduan pengembangan README.

```sh
python tests/live_native.py --check-native-focus --require-unmodified-harness
python tests/live_profiles.py
python tests/live_apps.py
python tests/live_rolling.py
python tests/live_parallel.py
```

Suite multiprofil memerlukan dua profil Chrome yang sudah tersedia. Fixture
memakai halaman lokal dan menutup resource miliknya. Matriks startup dilakukan
dari Chrome mati total untuk fase cold, Chrome tetap hidup sesudah cleanup untuk
fase windowless, lalu jendela pembanding yang dipertahankan untuk fase warm.
Periksa identitas proses, satu jendela awal per pemilik, preservasi pembanding,
inventori cleanup dan event macOS seperti kriteria PRD. Konfigurasi akun baru,
versi OS/browser/Hermes dan izin pada Mac tujuan memerlukan penerimaan di sana.

### Data lokal yang mempunyai kebutuhan pemulihan terpisah

GitHub menyimpan source, riwayat, spesifikasi dan panduan proyek. Login Chrome,
profil akun, konfigurasi pribadi Hermes, kredensial, media referensi/hasil,
checkpoint serta jurnal job merupakan data pribadi lokal. Untuk melanjutkan job
produksi lama, data plugin, konteks percakapan pemilik dan file referensinya
memerlukan salinan privat serta pemeriksaan ulang path/identitas pada Mac tujuan.
Pemulihan kode dari repo menyediakan instalasi baru dengan akun yang disiapkan
kembali. Status job lama hanya dapat direkonsiliasi apabila bukti sumbernya ada.

## Pesan siap pakai untuk agen setelah reset

> Lanjutkan proyek pada repo `dhansxd/hermes-original-chrome-cdp`. Baca
> `AGENTS.md` dan bagian aktif `PLAN.md` terlebih dahulu, kemudian `HANDOFF.md`,
> README dan panduan paket. Baseline pemulihan adalah host 0.10.3 dan Flow 0.3.0
> pada commit `6769518`. Tujuan tetap Chrome asli via CDP,
> profil dinamis, satu jendela awal per sesi dan pemisahan banyak agen/manual.
> Gunakan jalur `browser_exec` yang sudah berjalan. Ekstensi hanya memasok
> kontrol UI siap pakai pada halaman tugas tersebut.
> Periksa perubahan sejak baseline dan ikuti tugas lanjut yang sekarang saya minta.
> Pertahankan core Hermes, perilaku yang sudah lulus dan ruang lingkup yang
> disepakati. Catat bukti, checklist dan commit/push pada repo ini.
