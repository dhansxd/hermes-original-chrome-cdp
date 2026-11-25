# PRD — Original Chrome for Hermes dan extension situs

Revisi PRD 31, 22 November 2026.

## 1. Status dan langkah berikutnya

Host 0.13.1 menyediakan browsing umum, kontrol situs, dan tindakan jendela
lintas giliran melalui satu `browser_exec`. Jalur distribusi publik memakai
[URL Git](README.md#install). Pilih dan pulihkan browser secara manual melalui
Hermes. [AGENTS.md](AGENTS.md) dan kontrak di bawah menjadi acuan.
[HANDOFF.md](HANDOFF.md) mencatat perilaku versi sebelumnya.

### Chrome di perangkat lain

- Hermes memakai satu perangkat Chrome aktif melalui `browser_exec`. Pilih
  Mac lokal atau satu perangkat Windows lewat `chrome_profiles set_device`.
  Pemilihan profil berlaku di perangkat aktif. Jika perangkat itu gagal,
  laporkan error akses Chrome. Perpindahan otomatis ke Mac ditunda.
- Selesaikan atau tutup jendela tugas milik plugin sebelum mengganti perangkat.
  Jendela Chrome yang dibuka pengguna tetap di bawah kendali pengguna.
- Siapkan Windows sekali dengan Chrome, akun desktop aktif, dan OpenSSH.
  Gunakan SSH lewat LAN atau Tailscale. Rilis memuat skrip dan [panduan setup](docs/WINDOWS.md).
- [x] Pada 0.13.0, uji LAN dan Tailscale saat Chrome sudah punya jendela.
  Dua tugas memakai profil yang sama dengan jendela terpisah. Cleanup satu
  tugas mempertahankan jendela tugas lain. Unduhan Chrome terverifikasi di Mac.
- [x] Pada 0.13.1, uji langsung via `browser_exec` saat Chrome tertutup total
  dan saat Chrome aktif tanpa jendela. Keduanya memilih profil yang diminta,
  menyetujui dialog koneksi secara otomatis, serta memakai satu jendela yang
  sama untuk membaca DOM dan mengambil screenshot. Cleanup menutup jendela
  tugas. Pada kondisi tanpa jendela, PID Chrome tetap sama selama tugas.
- Uji startup dari kondisi tertutup menemukan bahwa Chrome dapat memakai
  kembali port lama sebelum memperbarui alamat WebSocket di
  `DevToolsActivePort`. Companion Windows memeriksa waktu perubahan file
  sebelum dan sesudah pembacaan. Chrome perlu menerbitkan alamat stabil
  untuk proses yang baru sebelum plugin membuka koneksi.
- [x] Pada host 0.13.2 dan Flow 0.4.5, kontrol unggah memakai SFTP untuk
  menyalin referensi dari Mac ke Chrome Windows. Uji `browser_exec` pada
  halaman terkontrol membaca ulang semua 767 byte PNG dari pemilih file native.
  Transfer dengan SHA-256 yang salah ditolak. Salinan sementara di Windows
  terhapus setelah konfirmasi. Pada Chrome Windows dengan profil yang dipilih,
  kontrol Flow juga mengonfirmasi PNG muncul di pemilih aset proyek uji
  Google Flow. Uji ini hanya mengunggah referensi.
- [x] Pada 0.13.3, panggilan native pertama dengan alias yang sama mengenali
  profil situs yang sudah dipilih sebelum Chrome membuka jendela tugas. Uji
  CLI dengan macOS sebagai default memilih profil Windows terlebih dahulu,
  lalu `browser_exec` biasa mengembalikan platform Windows. Jika satu alias
  memiliki beberapa pilihan perangkat/profil, gunakan ID sesi yang tepat.
- [x] Pada 0.14.0, uji CLI mengganti perangkat aktif ke Windows sebelum membuka
  jendela. Permintaan memilih profil Mac ditolak. Dua panggilan native memakai
  satu jendela Chrome Windows. Percobaan pergantian saat jendela milik tugas
  aktif ditolak. Setelah jendela ditutup, perangkat Windows uji yang tidak
  dapat dihubungi menghasilkan error dan tidak membuat sesi Chrome lokal.
- [x] Pada host 0.14.1, kontrol Gemini dan Flow mengunduh MP4 H.264 dari
  halaman uji terkontrol di Chrome Windows. Masing-masing memakai satu
  jendela milik tugas. File di Mac cocok ukuran dan SHA-256 dengan sumber
  serta lulus dekode FFmpeg. Pada Flow 0.4.6, unduhan yang ditunda dilanjutkan
  dari tanda terima Chrome yang sama dan server menerima satu permintaan.
  Bukti ini hanya mencakup jalur kode kedua paket pada halaman terkontrol.
- [x] Pada host 0.14.2, uji Gemini di Hermes CLI v0.23.2 dengan Chrome 157
  Windows memakai satu video lama dan satu jendela tugas. Pada pembanding
  `ac1ca2e`, Chrome menyimpan 6.616.052 byte tanpa event unduhan pada koneksi
  CDP halaman, sehingga transfer tetap menunggu. Pada kandidat, plugin
  menemukan tanda terima baru dari riwayat unduhan Chrome untuk halaman
  yang sama. MP4 1280 × 720 berdurasi 10,03 detik sampai ke Mac, lulus
  pemeriksaan SHA-256 dan dekode FFmpeg. Fixture event CDP lulus pada kedua
  versi dengan satu klik dan GUID yang sama. Regresi juga memeriksa pembacaan
  ulang tanpa klik tambahan serta penolakan tanda terima ambigu. Pembacaan
  riwayat berlangsung di Windows dan hanya dipakai jika URL dapat dikaitkan
  ke satu jendela tugas pada profil itu.
- [x] Pada kandidat yang sama, uji Google Flow 0.4.6 di Chrome Windows
  mengunduh video lama melalui kontrol **Ukuran asli**. Satu klik menghasilkan
  tanda terima CDP dan MP4 720 × 1280 sebesar 3.703.616 byte di Mac.
  Pemeriksaan SHA-256 dan dekode penuh FFmpeg lulus. Batas waktu panggilan
  browser tetap seperti pembanding agar kontrol yang lambat bisa selesai.
  Seluruh 454 tes unit lulus.
- [x] Pada host 0.14.3, cleanup Windows memulihkan penanda awal dan ID target
  yang belum tertutup. Pembanding `09729fa` dan kandidat memakai Chrome
  Windows asli, profil yang sama, dan OpenSSH. Uji menyimulasikan jawaban
  startup hilang setelah Chrome membuka jendela dan CDP putus setelah
  jendela terdaftar. Pembanding menyisakan satu jendela pada masing-masing
  gangguan. Kandidat menyisakan nol. Cleanup normal berhasil pada
  keduanya. Kandidat juga memulihkan catatan cleanup saat sesi baru
  terhubung setelah simulasi Windows tidak dapat dijangkau. Jendela
  pembanding di luar plugin dan jendela sesi agen lain tetap terbuka
  pada semua skenario. Seluruh 458 tes unit lulus.

### Update Chrome di macOS

- Pada host 0.14.4, pembanding `09b47e1` menolak salinan aplikasi Chrome
  158.0.8127.38 yang masih membawa metadata Finder di framework versi 157.
  Pada macOS 27.2.1, kandidat menerima salinan yang sama dan menolak salinan
  setelah satu resource yang disegel tanda tangan diubah. Verifikasi tetap
  memeriksa tanda tangan Google, ID aplikasi, dan symlink.
- Penolakan identitas sebelum Chrome menerima permintaan jendela langsung
  melepas penanda startup lokal. Jika permintaan sudah dikirim, cleanup tetap
  memakai identitas jendela yang dimiliki. Dua regresi baru gagal pada
  pembanding, lalu lulus pada kandidat. Seluruh 460 tes unit lulus.
- Uji Chrome asli melalui Hermes CLI dengan enam agen dan profil yang sama
  maupun dua profil lulus di `09b47e1` dan kandidat. Tiap agen memakai satu
  jendela. Stop dan giliran selesai menutup jendela milik agen tersebut serta
  mempertahankan jendela pembanding. Jumlah jendela kembali ke kondisi awal.

### Katalog klik otomatis di Mac

- Di 0.16.0, `browser_exec` belajar dari tautan satu origin yang membuka
  tujuan yang diharapkan pada tab yang sama. Katalog menyimpan hash path
  tujuan. Tombol dengan `aria-controls` atau `popovertarget` bisa dipakai
  ulang setelah panel yang dirujuk menjadi terlihat. Bukti aksi searah
  seperti Kirim tetap menunggu pemeriksaan hasil yang sesuai.
- Di Hermes `ae2a81ccc0`, macOS 27.2.1 dan Chrome 158.0.8127.38, pembanding
  `77eab10` membuka halaman tujuan dan panel, tetapi tidak menyimpannya.
  0.16.0 menyimpan serta memakai ulang tautan muat penuh dan navigasi SPA,
  serta panel dari klik screenshot pada zoom 1,2. Tautan yang dibatalkan
  tidak dipelajari, dan perubahan tujuan ditolak sebelum klik. Kedua versi
  lulus regresi tombol ARIA dari DOM dan screenshot. Kandidat lulus 467
  tes unit dan uji enam agen pada satu dan dua profil. Cleanup mengembalikan
  jumlah jendela ke kondisi awal.
- Pada branch `feature/windows-chrome`, 0.15.0 tahap pertama mendaftarkan
  situs dari halaman milik agen. Pengamatan sepanjang panggilan DOM
  menghasilkan kandidat tombol dan menyimpan kontrol siap pakai ketika label
  unik dan perubahan keadaan tombol terkonfirmasi. Katalog tersimpan di data
  plugin. Pengamatan tidak mengganti skrip, pesan, atau alur browsing native.
- Pada kunjungan baru, pakai kontrol dari katalog lewat `browser_exec`
  di halaman yang sudah terbuka. Jika lokasi atau tombol gagal dicocokkan,
  lanjut dengan DOM dan screenshot di jendela yang sama. Perbarui pemetaan
  otomatis setelah klik pengganti terkonfirmasi. Periksa keadaan halaman
  sebelum mengulang aksi yang mungkin sudah dikirim.
- Pada host 0.15.1, katalog Mac juga mempelajari klik kiri tunggal dari
  screenshot atau zoom. Plugin mencocokkan event klik dengan pasangan input
  CDP pada tab yang sama, lalu memeriksa efek setelah handler halaman berjalan.
  Saat tombol tertutup atau hasil belum terkonfirmasi, jalur inspeksi DOM dan
  screenshot tersedia di jendela yang sama. Pengujian Windows ditunda.
  Evaluasi merge ke main setelah fitur stabil dan regresi lulus.
- Pada `08dfc76` (0.15.0), klik dari screenshot saat zoom aktif berhasil di
  halaman uji, tetapi katalog tetap kosong. Di 0.15.1, Hermes CLI pada macOS
  27.2.1 dan Chrome 158.0.8127.38 membuktikan pembelajaran lewat screenshot,
  penolakan tombol yang tertutup banner, dan pemakaian ulang setelah ID
  tombol berubah. Uji mencakup zoom 1,1 hingga 1,4 serta regresi pembelajaran
  lewat DOM. Seluruh 466 tes unit lulus. Kedua versi lulus uji enam agen
  pada satu dan dua profil, dengan Stop dan cleanup yang menjaga jendela
  milik agen lain. Jumlah jendela kembali ke kondisi awal.
- Uji setelah pemasangan `0453456` (0.15.1) pada Hermes `ae2a81ccc0`,
  macOS 27.2.1 dan Chrome 158.0.8127.38 menemukan tombol pengganti kadang
  gagal disimpan setelah klik dari screenshot. Jejak CDP pada skenario
  yang sama menunjukkan event observasi tiba setelah balasan pelepasan
  mouse, ketika sesi sudah berhenti menunggunya. Di 0.15.2, relay menunggu
  event tersebut hingga 150 ms pada lampiran dan koordinat yang sama,
  lalu tetap memeriksa efek klik sebelum menyimpan kontrol. Regresi event
  terlambat gagal pada 0.15.1 dan lulus pada kandidat. Uji native DOM lulus
  pada kedua versi. Kandidat lulus uji lengkap screenshot, 467 tes unit,
  serta uji ulang enam agen pada satu dan dua profil dengan cleanup ke
  jumlah jendela awal.
- Pembanding `1e73be4` belum dapat membuka katalog. Pada kandidat, uji Hermes
  CLI di macOS 27.2.1 dan Chrome 158.0.8127.38 membuktikan empat sesi baru
  untuk belajar, pakai ulang, fallback DOM ketika ID tombol berubah, dan
  pakai ulang hasil pembaruan. Pada jalur halaman lain, target lama ditolak
  sebelum diklik. Kedua versi lulus uji enam agen pada satu dan dua profil,
  Stop, dan cleanup. Jumlah jendela kembali ke kondisi awal.

### Tujuan produk

Hermes memakai Google Chrome asli lewat CDP untuk membuka situs apa pun yang
dapat dijangkau Chrome. Gunakan `browser_exec` dan dukungan CDP bawaan Hermes.
Plugin menyediakan pilihan profil Chrome dan mengelola jendela milik setiap
tugas. Perilaku browsing dan chat Hermes mengikuti upstream.

Paket situs hanya menambahkan kontrol UI siap pakai untuk tindakan yang
sering diulang. Gemini dan Google Flow adalah dua paket awal. Kontrol klik,
ketik, dan unduh memakai halaman aktif di `browser_exec` yang sama. Jika suatu
tombol belum tersedia, tetap gunakan DOM atau screenshot bawaan di jendela itu.
Situs tanpa paket juga langsung memakai browsing bawaan.

Nilai browsing umum lewat situs tanpa paket. Nilai setiap kontrol situs dari
aksi yang benar-benar terjadi di UI Chrome. Deep Research adalah salah satu
contoh pengujian Gemini. Hasil layanan dan penyelesaian contoh tersebut dicatat
pada pengujian paket Gemini. Regresi browser yang terlihat selama pengujian itu
tetap diperiksa pada jalur browser yang terdampak.

### Kontrak browser dan ekstensi

- Seluruh perilaku chat mengikuti Hermes upstream. Ini termasuk pesan biasa
  yang masuk saat giliran aktif, prioritas pesan, slash command, steer,
  interrupt, jawaban model, dan tool selain browser. Plugin menyediakan status
  dan kontrol progres yang dipanggil eksplisit. Plugin tidak menyisipkan
  panggilan tool, mengganti jawaban, atau mengalihkan skrip browser dan
  perintah terminal.
- Pasang, aktifkan, nonaktifkan, dan hapus plugin melalui pengelola plugin resmi
  Hermes (`hermes plugins install`, `enable`, `disable`, dan `remove`).
  Setelah enable, pilih **Original Chrome · CDP** di
  `hermes tools → Browser Automation`. Sebelum disable atau remove, pulihkan
  pilihan browser dan pengaturan yang sebelumnya diubah. Jika
  `browser.cloud_provider` awalnya tidak disetel, gunakan
  `hermes config unset browser.cloud_provider`. Saat enable ulang, pilih
  Chrome asli lagi. Lihat [langkah resmi pada
  tutorial](docs/TUTORIAL.md#switch-back-disable-and-uninstall).
- Plugin sudah mendaftarkan Chrome asli sebagai provider browser Hermes.
  Pertahankan perilaku `browser_exec`, termasuk navigasi, pembacaan DOM,
  screenshot dan penggunaan jendela tugas. Tambahan untuk Gemini, Google Flow
  dan situs lain hanya berupa kontrol UI siap pakai melalui tool yang sama.
  `browser_exec` adalah satu-satunya alat browsing. Paket ekstensi menyediakan
  kontrol situs di alat ini lewat `site_control`. Skrip DOM dan screenshot
  memakai eksekutor native tanpa pembungkus khusus dari paket situs. Untuk
  mencatat kontrol yang belum dipetakan, panggil `record_missing_control`
  secara eksplisit pada sesi yang sama.
  Klik atau ketik langsung lewat CDP pada halaman aktif menghemat waktu dan
  token karena Hermes cukup memakai kontrol yang sudah dikenal. Panduan
  situs dapat menjelaskan cara menggunakan kontrol tersebut.
- Satu tugas memakai satu jendela Chrome asli dan sambungan CDP yang sama
  sejak aksi pertama sampai seluruh permintaan selesai. Submit, cek progres,
  pembacaan hasil, unduhan, dan pengiriman yang diminta berlangsung dalam
  pekerjaan itu. Status `running` adalah progres. Setelah hasil dan langkah
  yang diminta terverifikasi, Hermes memberi jawaban akhir dan plugin
  melepaskan jendela milik tugas. Stop dan kegagalan terminal memakai cleanup
  yang sesuai. Atas permintaan pengguna, panggilan eksplisit `keep_window`
  mempertahankan jendela tertentu sampai bisa dilanjutkan atau ditutup dalam
  percakapan yang sama. Tugas boleh memakai browser berkali-kali selama dibutuhkan.
  Plugin tidak menetapkan batas jumlah aksi atau durasi total tugas. Batas
  teknis per panggilan dan penghentian oleh Hermes tetap perlu diperhitungkan.
  Jika aturan perpindahan profil yang sudah disetujui terpicu,
  verifikasi hasil permintaan sumber sebelum melanjutkan di profil tujuan.
- Katalog tool dan panduan bawaan plugin cukup untuk sesi Hermes baru dengan
  perintah yang hanya menyatakan tugas. Gunakan provider Chrome asli melalui
  mekanisme resmi Hermes. Penemuan browser dan kontrol situs berjalan tanpa
  memori percakapan, prompt pribadi atau instruksi pengguna tentang nama tool.
- Pakai kontrol yang sudah dipetakan secara langsung. Jika kontrol belum
  dipetakan, lanjutkan dengan DOM terarah pada tool, sesi dan jendela yang sama.
  Pakai screenshot bila DOM tidak cukup. Situs tanpa paket memakai cara browsing
  biasa melalui tool yang sama. Untuk situs dengan paket, Hermes mencatat
  setiap kontrol yang terkonfirmasi belum dipetakan saat harus memakai DOM
  atau screenshot. Catat situs, halaman atau mode, kontrol dan cara inspeksinya
  sebelum jawaban akhir. Periksa mode, model dan panel aktif agar kontrol yang
  tersembunyi tidak keliru dicatat. Gunakan temuan untuk menambahkan kontrol
  siap pakai saat pengguna meminta patch.
- Profil, login, dan cookie tetap dikelola Chrome. Pertahankan profil terpilih,
  startup dan izin debugging yang sudah diatur, serta isolasi jendela antaragen
  dan jendela manual. Aksi melalui UI asli dengan CDP tanpa menyalin atau
  mengekspor cookie. Perubahan cukup pada ruang lingkup yang diminta. Pertahankan
  core Hermes dan 9Router dari upstream serta lifecycle resmi plugin dan paket
  situs yang sudah tersedia.
- Aktifkan saklar Remote debugging sekali, sesuai
  [tutorial](docs/TUTORIAL.md#enable-chrome-remote-debugging-once).
  Sesudah itu, plugin menjalankan alur startup, pemilihan profil dan izin koneksi
  yang sudah ada. Tes harus melalui alur plugin saat Chrome mati, hidup tanpa
  jendela, dan hidup dengan jendela. Chrome memakai satu ikon di Dock dan
  jendela agen aman saat beberapa agen berbagi satu profil.
- Gunakan [OpenCLI](https://github.com/jackwener/opencli) hanya sebagai referensi
  kontrol UI situs yang relevan, seperti tombol, label, selector, atau urutan
  klik. Arsitektur browser, routing sesi dan lifecycle mengikuti repo ini.

### Hasil audit acuan

- Pada plugin 0.11.1, ketujuh impor Hermes di kode runtime tercantum dalam
  [daftar API publik Hermes v0.23.2](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/hermes_cli/data/plugin_api.json).
  Provider Chrome memakai `ctx.register_browser_provider`. Dengan izin
  `tools.override`, kontrol situs memperluas `browser_exec` saat Hermes berjalan.
  [Registrasi kontrol](plugin.py) juga membaca dan mengatur langsung atribut
  entri tool di registry publik, termasuk skema dinamis dan batas waktu.
  Sebelum memakai versi Hermes baru, uji plugin yang sama pada instalasi uji
  versi tersebut. Dari sesi baru, pakai kontrol situs lalu baca DOM pada
  jendela yang sama. Jalankan dua agen pada satu profil Chrome dan pastikan
  akhir tugas satu agen hanya menutup jendelanya sendiri. Jika hasilnya sesuai
  kontrak, gunakan versi plugin yang sama. Patch kompatibilitas diperlukan
  bila pengujian menunjukkan perilaku yang rusak. Bila kontrol gagal sementara
  browsing umum berfungsi, periksa atribut registry dan pemanggilan handler
  bawaan pada integrasi kontrol situs.
- Hermes v0.23.2 sudah menyediakan `browser_exec` dan bisa memakai Chrome yang
  berjalan melalui endpoint CDP persisten (`browser.cdp_url`). Koneksi langsung
  memakai login yang sudah terbuka. Opsi terpisah `browser.use_real_profile`
  menyalin profil beserta cookie. Opsi `real_profile_pin` memilih sumber salinan itu.
  Plugin memakai profil asli melalui CDP dan mempertahankan larangan menyalin
  cookie. [Dokumentasi browser pada versi yang diperiksa](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/user-guide/features/browser.md)
- Pada satu endpoint Chrome bersama, Hermes mencoba membuat tab sendiri untuk
  setiap sesi bernama. Plugin mengelola pilihan profil dan kepemilikan jendela
  per agen, termasuk saat beberapa agen memilih profil yang sama. Gemini dan
  Flow menggunakan jendela tersebut melalui `browser_exec`. Pertahankan
  navigasi, DOM, dan screenshot bawaan saat memperbaiki kontrol situs.
  [Kode sesi bernama Hermes](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/tools/browser_use_cli.py#L56-L86) · [Kepemilikan sesi plugin](README.md#how-sessions-work)
- Baseline `84efb16` mendaftarkan `browser_app` di samping `browser_exec`.
  Handler situs memakai eksekutor native, tetapi jalur pemanggilan terpisah
  dapat memilih sesi berbeda untuk alias yang sama. Pada uji Telegram segar,
  Hermes juga memilih DOM umum untuk aksi Gemini yang sudah dipetakan.
  Keberhasilan fixture pencatatan kontrol belum membuktikan catatan dibuat
  pada jalur nyata tersebut.
- Commit awal `8f90d78` membedakan giliran berakhir dari tugas selesai melalui
  `finish_browser()`. Commit `3e1e5c1` menambahkan penyelesaian eksplisit pada
  desain Chrome khusus saat itu. Riwayat ini menjadi acuan batas penyelesaian
  tugas. Pada Chrome bersama, cleanup harus tetap mengikuti kepemilikan target.
- Gunakan referensi situs lama di [HANDOFF.md](HANDOFF.md#referensi-source-yang-sudah-tersimpan-di-github)
  untuk membaca perilaku menunggu hasil, verifikasi, pengumpulan artefak dan
  cleanup, serta detail UI yang relevan. Peliharalah satu jendela yang sama
  selama pekerjaan, termasuk pada jeda antara panggilan tool.
- Pada uji Telegram versi 0.11.0, Hermes mengakhiri giliran ketika tugas situs
  masih berjalan. Butir 3 mencatat patch 0.11.1, hasil uji terkendali, dan
  verifikasi yang masih terbuka pada percakapan Telegram nyata.

### Urutan perbaikan dan verifikasi

1. [x] Ulangi tes dari sesi Hermes baru dengan perintah yang hanya menyebut tugas.
   Mulai dengan situs umum. Verifikasi pemilihan Chrome asli, satu jendela
   milik tugas, hasil yang diminta, dan cleanup terarah. Pada host 0.10.21,
   Hermes membaca judul dan label tautan `example.com` lewat `browser_exec`.
   Inventori Chrome asli menunjukkan satu jendela tugas. Akhir giliran menutup
   jendela itu dan jendela pembanding tetap dapat dipakai.
   Uji CLI pada Hermes aktif menjalankan dua percakapan bersamaan dengan
   provider Original Chrome. Sesi pertama membaca judul dan tautan di
   `example.com`. Sesi kedua memakai kontrol `tools_menu` Gemini, lalu membaca
   dua pilihan menunya melalui DOM di sesi browser yang sama. Kedua percakapan
   selesai dan memakai ID sesi browser yang berbeda.
   - [x] Pada Hermes v0.23.2, `skills_list` menemukan skill plugin 0.12.1,
     tetapi daftar ringkas Telegram menyaringnya ketika `browser_exec`
     hadir lewat `browser-use` dan toolset `browser` tidak tersedia di
     sesi. Host 0.12.2 menyaratkan nama tool `browser_exec` secara langsung.
     Regresi memakai pembentuk daftar Hermes dan memeriksa kedua kondisi,
     saat tool itu tersedia dan saat tool itu tidak tersedia.
2. [x] Selesaikan perombakan dan dokumentasikan pemasangan melalui Git.
   - [x] Dokumentasikan pemilihan dan pemulihan browser secara manual.
     Audit Hermes v0.23.2 pada profil sementara menunjukkan bahwa enable,
     disable, dan remove mengelola plugin, sementara konfigurasi pemilihan
     browser disimpan terpisah. Saat gateway berhenti, remove juga
     mempertahankan nilai `browser.cloud_provider`. Perintah `config set`
     memulihkan pilihan browser sebelumnya dan `config unset` memulihkan
     seleksi otomatis ketika kunci semula belum disetel. Pengaturan browser
     lain pada profil uji tetap utuh. Ikuti
     [tutorial](docs/TUTORIAL.md#switch-back-disable-and-uninstall).
   - [x] Hapus registrasi dan deklarasi `browser_app`. Pemanggilan nama lama
     pada registry profil uji menghasilkan `Unknown tool`. Instalasi paket,
     pengelolaan status, panduan, dan operasi situs tetap tersedia.
   - [x] Uji Chrome asli. Klik menu alat Gemini melalui `browser_exec` dan
     pastikan identitas dokumen serta sesi sama sebelum dan sesudah klik.
     Inspeksi Google Flow juga berhasil pada sesi browser yang sama.
   - [x] Uji penemuan dengan dua percakapan Hermes baru melalui 9Router.
     Permintaan membuka menu alat dan pilihan model menghasilkan klik
     `tools_menu` dan `model_picker`. Masing-masing memakai `browser_exec`
     untuk membuka Gemini, membaca panduan, mengeklik, lalu membaca label menu.
     Parameter `site_control` menerima teks JSON agar parameter operasi yang
     ditentukan per situs sampai utuh lewat penyedia model.
   - [x] Uji isolasi di Chrome asli dengan fixture lokal. Enam jendela pada
     profil Chrome yang sama mempunyai kepemilikan terpisah. Uji meliputi
     penemuan paket, pemakaian ulang halaman, Stop, disable/enable/remove,
     pelepasan resource, serta pemulihan handler bawaan setelah unload.
     Sebanyak 425 tes otomatis lulus. Fixture perpindahan profil juga
     memverifikasi pemulihan permintaan asal tanpa submit ulang dan jumlah
     jendela Chrome kembali ke kondisi awal.
   - [x] Pasang commit `3be8e6f` dari GitHub dengan `hermes plugins install --ref`
     di profil Hermes kosong. Aktifkan plugin, beri izin `tools.override`, pilih
     provider ini, dan sertakan toolset Browser serta Terminal. Registry memuat
     `browser_exec` dengan `site_control` dan tidak memuat `browser_app`.
     Hermes menempatkan kedua paket situs di profil uji. Dalam percakapan baru
     melalui 9Router, Gemini membuka menu alat lewat kontrol `tools_menu`;
     pembacaan DOM pada sesi yang sama mengonfirmasi “Buat gambar” dan “Buat video”.
     Ada percobaan ekstra: model sempat menaruh JSON kontrol di `code`. Python
     mengembalikan output kosong. Klik baru terverifikasi setelah model mengirim
     permintaan lewat `site_control`. Sesi baru kedua melalui CLI dan konfigurasi
     provider 9Router menggunakan `open_chat`, `model_picker` dan pembacaan DOM
     untuk melaporkan pilihan model. Tanpa toolset Terminal, Hermes menyaring
     `browser_exec` dari katalog percakapan.
   - [x] Gunakan instalasi dari URL Git untuk distribusi publik. Pada audit
     Hermes v0.23.2, validator katalog melaporkan benturan nama tool bawaan
     `browser_exec`. Kontrol situs tetap memakai deklarasi resmi dan izin
     `tools.override`. Instalasi melalui katalog menunggu dukungan validator
     upstream untuk perluasan tool bawaan.
   - [x] Pada 21 November 2026, plugin lama dilepas lewat Hermes sebelum
     commit `36019f1` dipasang di profil Telegram. Gateway yang sudah dimulai
     ulang melaporkan plugin 0.11.0 aktif dan Telegram terhubung. Katalog tool
     untuk Telegram memuat `browser_exec` dengan `site_control`. Paket Gemini
     0.4.2 dan Flow 0.4.3 cocok dengan berkas bawaan commit itu. Uji Telegram
     kemudian mengonfirmasi `open_chat`, klik `tools_menu` dan inspeksi di sesi
     baru. Pada percakapan dari versi lama, pencarian `browser_app` berhenti
     sebelum membuka Gemini untuk permintaan gambar. Panduan migrasi pada
     deskripsi tool dan skill mengarahkan percakapan tersebut ke `browser_exec`.
3. [ ] Perbaiki regresi penyelesaian tugas. Uji progres yang berlangsung cukup
   lama. Tugas yang masih berjalan harus tetap dilanjutkan. Verifikasi hasil
   dan setiap unduhan atau pengiriman yang diminta sebelum jawaban akhir.
   Setelah itu ukur cleanup jendela milik tugas dan pastikan jendela lain utuh.
   - Paket mengembalikan `next_control` untuk diperiksa Hermes secara
     eksplisit. Jika pembacaan hasil perlu inspeksi, Hermes dapat mengamati
     DOM memakai `browser_exec` pada sesi milik tugas. Agen bisa menetapkan
     selector hasil pada `observe`. Job ber-ID diverifikasi oleh paketnya.
   - [x] Uji satu tugas berdurasi panjang dari sesi Hermes CLI baru pada
     host 0.13.1 dengan 9Router dan Chrome Windows. Pada situs uji terkendali,
     Hermes melakukan satu submit dan tiga pemeriksaan progres lewat DOM di
     `browser_exec`. Dari pembacaan `running` pertama hingga hasil siap,
     sesi browser bertahan 158 detik, melewati batas idle 120 detik.
     Empat sampel Windows mencatat jendela tugas yang sama dan jendela
     pembanding. Hermes membaca kode hasil sebelum jawaban akhir, dan kode
     itu cocok dengan hasil yang dibaca penguji langsung dari situs.
     Jendela pembanding bertahan setelah giliran selesai dan ditutup terpisah.
   - [x] Uji kontrol paket `next_control` pada sesi Hermes CLI baru dengan
     host 0.13.1 dan Chrome Windows. Hermes menemukan paket Progress Board
     lewat katalog, menjalankan `start` sekali, lalu mengikuti
     `next_control` dengan sepuluh panggilan `read_result` melalui
     `browser_exec`. Situs uji menerima satu submit. Selama 159 detik,
     sesi, dokumen, profil dan jendela tugas tetap sama. Hermes membaca hasil
     siap sebelum jawaban akhir dan mengembalikan kode yang cocok dengan
     hasil situs. Jendela pembanding bertahan setelah giliran berakhir dan
     ditutup terpisah. Sesi uji yang lulus memakai `cx/gpt-6.1-sol`
     melalui 9Router.
     Uji Telegram dengan Gemini 0.4.6 memakai sesi Hermes yang sudah ada.
     Satu topik dikirim di profil uji. Kontrol konfirmasi mengembalikan
     `obscured`; Hermes memakai DOM di jendela yang sama dan Gemini
     memulai riset. Pembaca tetap mengembalikan `running`. Saat Hermes
     menunggu 120 detik dalam satu skrip browser, pembersih idle menutup
     jendela sebelum laporan siap. Hermes membuka kembali percakapan yang
     sama tanpa mengirim ulang topik. Penutupan terulang saat menunggu.
     Pada pemeriksaan terakhir Gemini masih menampilkan “Meriset 12 situs”
     dan Hermes belum menyampaikan laporan. Kriteria satu jendela gagal.
   - Riwayat 0.11.5. Hook `pre_tool_call` saat itu mengalihkan skrip
     yang hanya tidur lalu mencetak progres ke
     `read_result` atau `observe` pada sesi tugas yang masih aktif.
     Pemeriksaan memakai jeda observasi yang sudah ada. Skrip klik,
     navigasi dan inspeksi biasa tetap mengikuti jalur native.
     Uji Chrome asli dengan batas idle 120 detik melampaui batas itu tanpa
     mengganti jendela atau dokumen. Satu submit menghasilkan satu hasil.
     Uji Stop dan cleanup menjaga jendela lain. Seluruh 438 tes otomatis lulus.
     Host 0.11.5 dipasang melalui Hermes dari commit `ebe81f1` di cabang
     perombakan setelah melepas 0.11.4. Gateway mengonfirmasi reload dengan
     perubahan katalog berlaku pada sesi baru. Paket Gemini 0.4.6 aktif.
     Uji ulang dari sesi Telegram baru mengirim topik sekali. Sesi browser
     bertahan lebih dari 120 detik. Panggilan yang berisi tidur 120 detik lalu
     membaca halaman dialihkan ke `read_result` dalam sekitar 12 detik.
     Panggilan yang hanya tidur berjalan penuh, dengan jendela tetap terbuka
     pada percobaan ini. Gemini belum menyediakan rencana dan Hermes memuat
     ulang halaman. Sesudah muat ulang, pembaca mengembalikan
     `research_submission_unconfirmed`. Hermes berhenti setelah kegagalan
     identik berulang dan jendela tugas tertutup. Penerimaan laporan lewat
     Telegram masih terbuka.
   - [x] Pulihkan pembacaan Deep Research setelah muat ulang pada sesi yang
     sama. Simpan identitas percakapan dan giliran kiriman yang sudah
     terverifikasi dalam data sesi paket. Cocokkan keduanya di DOM sebelum
     membaca progres, mengaktifkan konfirmasi, atau mengambil laporan.
     Muat ulang saat Gemini masih bekerja harus dapat dilanjutkan tanpa
     mengirim ulang topik atau mengambil hasil giliran lain. Jika identitas
     tidak dapat dipulihkan, pertahankan fallback DOM pada keadaan yang bisa
     diperiksa dan hentikan pengulangan pembaca dengan kegagalan identik.
     Cakup skrip yang hanya menunggu pada jalur pemeriksaan tugas aktif.
     Uji rangkaian topik, progres, muat ulang, konfirmasi, hasil dan cleanup
     dengan satu jendela pada Chrome asli sebelum mengulang uji Telegram.
     Seluruh 439 tes otomatis dan uji Chrome asli lulus. Setelah muat
     ulang, uji menolak chat lain dan giliran yang salah, lalu membaca
     kembali progres, melakukan satu konfirmasi, dan membuka laporan yang
     benar. Uji terpisah melewati batas idle dengan skrip tunggu yang
     bergantian membaca halaman dan hanya menunggu. Hermes memasang host
     0.11.6 dari commit `a6a2f99` setelah melepas versi sebelumnya.
     Paket Gemini 0.4.7 cocok dengan bundel commit tersebut dan gateway
     mengonfirmasi katalog baru berlaku pada sesi berikutnya.
     Uji Telegram mengirim topik sekali. Pembacaan hasil pertama pukul
     22.14 WIB mengembalikan `research_submission_unconfirmed`. DOM
     menampilkan topik yang dikirim, sementara penanda `submitted` belum
     mempunyai checkpoint. Jejak tool belum memuat perintah navigasi atau
     muat ulang sebelum kegagalan itu. Uji DOM sintetis mereproduksi
     kegagalan saat dokumen berganti sebelum checkpoint. Dengan checkpoint
     yang cocok, pembacaan pada dokumen pengganti mengembalikan `running`.
     Penyebab hilangnya konteks pada uji Telegram belum terkonfirmasi.
     Jendela juga tercatat ditutup oleh Hermes setelah 141 detik idle.
   - [x] Pulihkan kiriman Deep Research sebelum giliran pertama terverifikasi.
     Gunakan pola balasan Gemini dari commit `f679cf0` dan aturan di
     [HANDOFF.md](HANDOFF.md): simpan intent, hash topik, dan jangkar
     percakapan sebelum klik Kirim. Pada jendela dan profil asal, cocokkan
     giliran baru terhadap jangkar tersebut sebelum menyimpan identitasnya.
     Jika hasil pengiriman belum pasti, periksa sumber tanpa mengirim ulang.
     Uji pergantian dokumen tepat setelah klik Kirim, pergantian dari chat
     baru ke URL percakapan, dan penolakan giliran yang tidak cocok.
     Host 0.11.7 dan Gemini 0.4.8 lulus 441 tes otomatis. Uji Chrome asli
     pada halaman lokal membuktikan pemulihan sebelum pembacaan pertama
     baik di chat yang dimuat ulang maupun setelah chat baru mendapat URL.
     Uji juga menolak topik yang berbeda dan draft yang berubah sebelum klik.
     Uji Telegram pada 0.11.7/0.4.8 belum lulus. Kiriman pertama terlihat,
     lalu halaman kembali menampilkan draf kosong tanpa ID percakapan.
     Kontrol Kirim menahan pengulangan, tetapi Hermes mengirim draf berbeda
     lewat DOM. Gemini mulai membuat rencana untuk draf kedua dan pembaca
     menolaknya karena hash tidak cocok dengan checkpoint. Saat Hermes
     menunggu 180 detik lewat terminal, cleanup idle menutup jendela setelah
     125 detik. Hermes akhirnya mengakhiri giliran setelah pengguna meminta
     berhenti, tanpa laporan riset.
   - [x] Reproduksi kegagalan 0.11.7 dengan fixture Chrome lokal. Buktikan
     bahwa fallback DOM tetap dapat membaca halaman selama kiriman awal
     belum terverifikasi dan tidak bisa mengirim ulang dalam kondisi itu.
     Uji pemantauan di jendela yang sama melewati ambang idle serta Stop
     ketika pemantauan aktif. Jika kiriman tetap macet di Gemini Web setelah
     perilaku plugin lulus, cocokkan perubahan UI dengan waktu dan status
     jaringan yang relevan pada satu uji terkendali. Log percobaan ini
     belum menunjukkan penyebab backend Gemini.
     Pada 0.11.7, klik ulang lewat DOM membuat penghitung kiriman naik dari
     satu ke dua. Host 0.11.8 dan Gemini 0.4.9 menahan klik Kirim serta
     Enter pada composer selama pengiriman aktif. DOM, screenshot, tombol
     lain, dan pencatatan kontrol yang belum dipetakan tetap bisa dipakai.
     Panggilan terminal `sleep 180` mengikuti pembaca progres Gemini pada
     jendela semula selama lebih dari 120 detik. Event Stop resmi
     menghentikan pemeriksaan yang sedang berjeda dan melepas target Chrome.
     Sebanyak 442 tes otomatis lulus. Verifikasi Gemini Web hingga laporan
     terkirim ke Telegram tetap terbuka.
     Uji Telegram dengan 0.11.8/0.4.9 mengirim topik sekali, mencatat ID
     percakapan dan giliran, serta mengalihkan tidur terminal ke pembaca
     progres di sesi yang sama. Gemini belum menampilkan rencana saat
     pembaca kehilangan kecocokan kiriman. Pemantauan DOM tetap berjalan.
   - [x] Kembalikan prioritas pesan sepenuhnya ke Hermes. Pada uji Telegram,
     Hermes menyuntikkan pesan berhenti ke giliran aktif melalui `/steer`,
     lalu plugin tetap menyisipkan panggilan observasi. `continue_running`
     menimpa keluaran final model selama tugas masih tercatat aktif, tanpa
     mempertimbangkan arahan pengguna yang masuk setelah tugas mulai.
     Pada 0.11.9, hapus middleware pengganti jawaban dan pengalih terminal,
     serta pengalihan skrip browser saat menunggu. Uji registrasi memastikan
     plugin hanya memperluas browser dan tetap memakai hook Stop resmi.
     Uji skrip browser memastikan input eksplisit diteruskan ke jalur native.
   - Fallback DOM kembali langsung ke eksekutor native. Pengamat klik dan
     penahan kiriman Gemini di dalam skrip fallback dilepas. Kontrol situs
     yang dipanggil eksplisit serta `record_missing_control` tersedia pada
     `browser_exec` dan sesi yang sama. Sebanyak 439 tes otomatis lulus.
     Uji Chrome asli pada situs lokal memverifikasi klik langsung, fallback,
     screenshot, dan cleanup terarah dengan jendela agen lain tetap tersedia.
   - Host 0.11.10 memakai hook akhir giliran resmi Hermes untuk menutup
     jendela milik tugas. Selama giliran masih berjalan, kontrol situs dan
     fallback tetap memakai jendela yang sama. Checkpoint dan hasil tersimpan
     agar operasi yang mendukung pemulihan dapat dibuka kembali secara eksplisit.
     Uji Chrome asli memverifikasi penutupan jendela tugas saat situs masih
     `running`, pemeliharaan checkpoint, serta jendela agen lain dan manual.
   - Temuan Telegram 0.11.2 di percakapan yang sudah ada: setelah satu
     submit Deep Research, 32 panggilan `observe` tanpa selector membaca
     teks “Membuat rencana riset” pada sesi yang sama hingga pengguna
     mengganti tugas. Log belum membuktikan ada tombol konfirmasi saat itu.
     Untuk perbaikan Gemini, periksa panel riset aktif lewat CDP, bedakan
     progres, kontrol konfirmasi yang terlihat, dan laporan yang sudah siap.
     Uji setiap transisi pada dokumen yang sama dan pertahankan Stop.
   - Prioritas pertama pada ekstensi Gemini ialah tombol unduh video pada
     hasil yang diminta. Pengambilan URL elemen video di luar Chrome pernah
     menyimpan HTML dengan nama MP4. Klik tombol unduh asli menghasilkan
     MP4 yang valid. Kaitkan unduhan dengan klik pada jendela tugas,
     tunggu sampai selesai, periksa stream video dan berikan jalur berkas
     yang bisa dibaca gateway. Uji ulang memakai video yang sudah ada.
     Untuk permintaan kirim, verifikasi pengiriman melalui Telegram dan
     cleanup jendela tugas. Sesi ini hanya membuktikan gateway mencoba
     mengirim berkas yang valid.
   - [x] Pada 0.11.3, Hermes memakai tombol unduh pada jawaban video di
     Gemini Web asli. Plugin mencocokkan unduhan Chrome dengan percakapan
     serta waktu klik, lalu memeriksa ukuran, stream dan hasil dekode.
     Seluruh byte salinan hasil uji cocok dengan MP4 yang sudah ada.
     Pengguna mengonfirmasi lampiran muncul di Telegram. Pemutaran di HP
     masih belum terkonfirmasi.
   - [x] Paket Gemini 0.4.4 membedakan pembuatan rencana, tombol mulai
     riset, riset berjalan, tombol buka laporan dan teks hasil. Di halaman
     uji Chrome asli, satu klik memulai riset dan laporan terbaca di dokumen
     yang sama. Pada percakapan Gemini asli yang diperiksa, hasil akhirnya
     berupa penolakan. Uji lintas profil pada 0.11.4 tercatat di bawah.
   - Pada audit 0.11.3, teks pesan lanjutan yang dikirim Hermes cocok persis
     dengan pesan manual berikutnya di percakapan Gemini yang sama. UI
     menampilkan tahap pembuatan rencana lalu penolakan pada giliran Hermes.
     Pada giliran manual, UI menampilkan `deep-research-confirmation-widget`
     dan tombol “Mulai penelitian”. Penyebab perbedaan respons belum diketahui.
     Jalur `reply` sempat berhenti sebelum mengetik. Pengiriman yang tercatat
     memakai `type_prompt` dan `click(send)` dengan isi yang cocok dengan teks di UI.
     Untuk diagnosis berikutnya, cocokkan indikator mode pada komposer sebelum
     Kirim, pesan yang benar-benar terkirim, dan hasil pada giliran itu.
     Bedakan rencana siap dikonfirmasi, laporan selesai, dan penolakan.
   - Pada 0.11.4, ekstensi memeriksa indikator Deep Research pada komposer
     setelah memilih mode dan sebelum mengirim. Pilihan yang sudah aktif
     terkonfirmasi di Gemini Web asli, termasuk saat dipilih untuk kedua kali.
     Pada halaman uji di Chrome asli, hilangnya mode mencegah klik Kirim.
     Pembaca hasil menggunakan jawaban milik kiriman baru. Pada percakapan
     Gemini asli, dua pesan identik memiliki identitas giliran berbeda dan
     panel konfirmasi rencana berada pada giliran kedua.
   - [x] Uji pembanding lewat CDP di profil Chrome lain menghasilkan laporan
     Gemini asli. Satu kiriman topik menghasilkan rencana. Sesudah konfirmasi
     “Mulai penelitian”, percakapan memuat dua jawaban dan laporan tampil di
     panel dengan bagian sumber. Isi laporan diverifikasi lewat DOM. Pengujian
     penerimaan laporan dari Hermes di Telegram tetap terbuka pada butir 3.
   - [x] Perbaiki `read_result` Gemini ketika konfirmasi rencana membuka
     giliran lanjutan. Pembaca menunggu setelah konfirmasi dan mengambil isi
     laporan yang terkait dengan kartu aktif di giliran tersebut. Regresi
     Chrome asli mencakup satu klik konfirmasi, status progres, kartu
     serta laporan yang tidak terkait, dan laporan yang benar. Pembacaan
     ulang laporan yang sudah ada di Gemini Web juga lulus, termasuk membuka
     kembali panel dari kartunya dan menutup jendela uji. Verifikasi isi di
     Telegram dan cleanup pada alur nyata tetap tercantum pada butir 3.
   - Patch pembaca Gemini mengaitkan konfirmasi setelah salinan rencana
     berurutan hanya jika prompt dan widget rencananya cocok, kedua tombol
     mulai sudah nonaktif, dan giliran konfirmasi memiliki kartu riset.
     Uji ulang dua percakapan yang tersimpan lewat Chrome asli menemukan
     laporan yang sebelumnya tidak terbaca dan mengembalikan penolakan
     sebagai `research_no_plan`. Pemicu penolakan di sisi Gemini tetap terbuka.
     Gemini 0.4.10 dimuat gateway tanpa restart. Sesi Telegram baru berhasil
     mengirim ringkasan laporan lama melalui DOM pada `browser_exec`.
     Verifikasi terpisah pada sesi baru menemukan kartu laporan yang selesai,
     tetapi `open_research_report` mengembalikan `needs_inspection` dan
     `read_result` belum mengembalikan `report_ready` tanpa catatan giliran
     asal. Penerimaan jalur kontrol langsung dari sesi baru masih terbuka.
     Gemini 0.4.11 mengenali kartu selesai pada giliran konfirmasi terbaru
     di percakapan yang dibuka. Uji sesi Hermes baru dengan laporan lama
     melewati `open_research_report` hingga `report_ready` pada satu jendela
     Chrome asli. Hook akhir giliran menutup jendela uji. Uji Telegram
     sebelumnya mengonfirmasi pengiriman ringkasan lewat DOM.
   - [x] Uji situs lokal di Chrome asli melalui Hermes: satu paket tanpa
     pembaca hasil melewati enam pemeriksaan tertunda. Pemeriksaan ketujuh
     membaca hasil pada dokumen dan jendela yang sama. Uji isolasi dan
     cleanup lulus. Regresi terpisah memeriksa Stop ketika observasi sedang
     menunggu dan memastikan jendela agen lain tetap tersedia.
   - Telegram 0.11.0 berhasil memilih Deep Research dan menekan Send. Setelah
     satu `read_result` berstatus `running`, middleware menghasilkan lima
     panggilan `describe` berturut-turut. Hermes menghentikan giliran karena
     kelimanya membaca panduan yang sama. Patch 0.11.1 memanggil pembaca hasil
     paket pada sesi asal untuk operasi biasa yang mendukung `read_result`
     tanpa parameter wajib. Pengecekan itu mengikuti jeda observasi yang sudah
     ada. Operasi dengan job dan pemilihan profil tetap mengikuti kontrak
     kelanjutan masing-masing paket.
     Dalam uji Hermes dengan aturan platform Telegram dan Chrome asli, model
     uji mencoba mengakhiri giliran tujuh kali. Satu submit diikuti tujuh
     pembacaan halaman lokal, selama 91 detik dari pembacaan pertama sampai
     terakhir. Dokumen dan sesi tetap sama, hasil diterima dan jendela ditutup.
     Pada uji 9Router terpisah dengan cuplikan riwayat percakapan lama,
     Hermes membuka Gemini Web asli dan memilih `create_image` lewat
     `browser_exec`. Uji ini berakhir pada pemilihan mode gambar. Sebanyak
     427 tes otomatis lulus.
   - [x] Pada instalasi GitHub di atas, Hermes melalui 9Router menjalankan
     tugas di situs uji lokal lewat Chrome asli. Satu kali submit, tiga status
     tertunda, lalu kode hasil acak muncul di halaman dan diterima di jawaban
     akhir. Selama 61 detik, 156 sampel jendela dan identitas dokumen yang
     dibaca pada setiap operasi menunjukkan satu jendela yang sama. Setelah
     giliran selesai jumlah jendela kembali ke kondisi awal.
   - [x] Ulangi dengan model uji yang sengaja mengirim empat kandidat jawaban
     akhir saat pekerjaan masih berjalan. Hermes meneruskan keempatnya dalam
     giliran yang sama dan mengembalikan kode hasil sesudah situs siap. Pada
     keluaran streaming, teks progres masih dapat terlihat. Satu jendela
     pembanding tetap terbuka saat jendela tugas ditutup.
   - [x] Uji unduh dan kirim berkas melalui UI Chrome. Hermes lewat 9Router
     menunggu laporan siap, mengunduh berkas, mengunggahnya ke kotak penerima
     di situs uji lokal, lalu mengembalikan nomor tanda terima di chat.
     Penerima dan penguji mencocokkan seluruh 3.001 byte. Satu dokumen dan
     satu jendela dipakai dari submit sampai pengiriman, dengan dua jendela
     pembanding kembali utuh sesudah cleanup.
   - Pada percobaan berkas pertama, isi unduhan dan tanda terima benar, tetapi
     pemeriksaan jendela pembanding gagal. Percobaan terpisah mereproduksi
     penutupan jendela pembanding yang tidak melakukan panggilan browser selama
     120 detik. Log `tools.browser_session_lifecycle` mencatat pembersihan sesi
     tersebut karena inaktivitas. Jendela pembanding yang terus memeriksa
     dokumennya mempertahankan dokumen yang sama. Batas bawaan Hermes ini
     perlu diperhitungkan untuk pekerjaan dengan jeda panjang antarpanggilan.
4. [x] Perjelas panduan Flow dalam paket situs. Panel yang tertutup berarti
   kontrol belum terlihat. Gunakan `configure` untuk membaca pilihan setelah
   mode dan model terpilih. Di Klasik, gunakan UI untuk spesifikasi yang
   tersedia dan isi prompt dengan deskripsi konten. Di Agent, gunakan kontrol
   yang tersedia dan sampaikan spesifikasi tanpa kontrol sebagai instruksi,
   lalu verifikasi hasil. Flow 0.4.2 membaca pilihan Klasik dan radio model
   pada default gambar/video Agent di Chrome asli dalam satu jendela.
5. [ ] Verifikasi Hermes mencatat kontrol yang terkonfirmasi belum dipetakan
   saat melanjutkan tugas dengan DOM atau screenshot. Uji melalui tool yang
   sama pada sesi baru tanpa arahan tambahan. Fixture jalur lama menyimpan satu
   temuan lewat `record_missing_control`. Di Telegram pada 0.11.2, Hermes mengeklik tombol unduh video Gemini
   lewat DOM tanpa memanggil `record_missing_control`. Uji ulang dengan kontrol
   lain yang terkonfirmasi belum dipetakan dan periksa baris temuan yang tersimpan. Temuan
   yang terverifikasi menjadi bahan menambahkan tombol ketika diminta.
   Pada 0.11.3, klik DOM biasa pada tombol berlabel di Gemini Web asli
   mencatat kontrol yang belum dipetakan dalam `missing-controls.jsonl`.
   Untuk kontrol tanpa label yang ditemukan secara visual, Hermes dapat
   mencatat temuan dan menjalankan aksi lewat satu panggilan `browser_exec`.
   Pada sesi nyata, `record_missing_control` menyimpan tiga temuan Gemini
   yang memakai fallback DOM. Panggilan eksplisit berlaku pada CLI dan Telegram.

Untuk Google Flow, pertahankan pemisahan cara menggunakan mode Klasik dan Agent
sesuai butir 4 dan panduan paket. Pilihan profil serta mode perpindahan manual
atau otomatis yang sudah disetujui mengikuti [kontrak rolling](docs/ROLLING.md).
Periksa hasil dan identitas permintaan asal sebelum melanjutkan ke profil lain.

### Jendela Chrome lintas giliran

- `keep_window` dipanggil hanya ketika pengguna meminta jendela tetap terbuka
  atau hasil yang diminta jelas membutuhkan jendela tetap aktif. Verifikasi
  halaman atau tindakan yang diminta sebelum mengakhiri giliran. Status
  `running` sendiri tidak memicu fitur ini.
- `list_windows` menampilkan jendela yang disimpan untuk percakapan saat ini.
  Gunakan ID sesi yang sama untuk melanjutkan lewat browser native atau kontrol
  situs. `close_window` menutup jendela yang dirujuk pengguna. Akhir percakapan
  dan pelepasan plugin membersihkan jendela yang masih tersimpan.
- [x] Pada 0.12.0, uji Chrome asli memverifikasi ID jendela, target CDP, dan
  dokumen yang sama setelah akhir giliran, pembersihan cache idle Hermes, dan
  penyambungan ulang driver native. Percakapan lain tidak dapat melihat,
  memakai, atau menutup jendela tersebut. Penutupan berdasarkan ID, cleanup
  tugas biasa, dan isolasi enam jendela pada satu profil lulus. Sebanyak 440
  tes otomatis lulus.
- [x] Pada 0.12.1, Hermes CLI memanggil penahanan sekali memakai nama sesi
  aktif, lalu melanjutkan dan menutup jendela yang sama pada giliran
  berikutnya. Skill `original-chrome-default:site-controls` tersedia di
  katalog skill sesi baru. Suite 440 tes dan uji Chrome asli lulus.

### Bukti historis hingga 16 November 2026

**Perbaikan startup satu jendela per sesi tersedia pada host 0.10.3.** Pengguna meminta
jendela awal untuk izin CDP dan pemeriksaan profil dipakai langsung sebagai
jendela kerja. Relay sekarang menyerahkan halaman awal milik sesi satu kali pada
permintaan bootstrap driver. Pemeriksaan profil dan kesiapan halaman kosong
selesai sebelum penyerahan. Permintaan target berikutnya membuat target baru.
Duplikasi yang diperbaiki sudah ada sejak `d33aa03`. Sebanyak 342 tes otomatis,
startup cold/windowless/warm, regresi profil/extension/rolling, dan enam identitas
native pada profil sama/campuran lulus. Masing-masing sesi membuka satu jendela
awal. Pemeriksaan cleanup serta event macOS lulus.

- [x] Serahkan halaman awal milik sesi pada permintaan bootstrap pertama driver.
- [x] Penyerahan hanya sekali, pada halaman kosong yang identitasnya masih cocok.
- [x] Permintaan target tambahan mempunyai target baru milik sesi tersebut.
- [x] Uji satu jendela awal per sesi, enam agen pada profil sama/campuran,
  startup cold/windowless/warm, profil langsung, Dock, Stop dan cleanup.
- [x] Efek samping keyboard yang membuka Tentang Mac Ini diperbaiki pada relay.
  Helper Browser Harness 0.1.13 menyalin angka Windows ke `nativeVirtualKeyCode`.
  Pelacakan paralel merekam event Cmd+A `keyUp` sebelum dua event AboutThisMac.
  Probe pembanding memproses 1.212 event keyboard dengan field tersebut dihilangkan
  dan menghasilkan nol event AboutThisMac. Relay menormalisasi encoding yang
  mencerminkan angka Windows. Key/code, modifier, text dan perintah editor
  diteruskan. Encoding native eksplisit yang berbeda diteruskan. Uji browser dan
  enam identitas setelah patch memeriksa log macOS secara otomatis.
- [x] Regresi browser/profil/extension/rolling serta inspeksi Flow melalui Hermes.
  Klasik → Agent → klasik mengembalikan `ok` pada dokumen yang sama. Sebanyak
  657 sampel inventori mencatat maksimum satu jendela tambahan milik Hermes.
  Jendela peer mempertahankan input `KEEP`, dan inventori akhir nol.
- [x] Catatan hasil, versi, validasi distribusi bersih dan scan secret diperbarui.
  Publikasi mengikuti commit perubahan ini dan verifikasi SHA remote.

Pekerjaan sempat dijeda saat pengguna memakai Chrome. Runner profil dihentikan
dengan SIGINT dan cleanup kembali ke dua jendela pembanding yang sedang dipakai.
Uji cold-start sebelumnya gagal pada inventori akhir yang berisi halaman tambahan
saat kondisi desktop berubah. Setelah pengguna selesai dan Chrome mati, ketiga
kondisi startup diulang secara berurutan dan lulus. Dua probe diagnostik sebelum
jeda juga sempat gagal pada pembacaan AX `-25204`. Pengulangan setelah jeda lulus.
Pengukuran Hermes pertama sesudah jeda mencatat satu gangguan baca AX sementara.
Pengukur menunggu hasil inventori valid dalam deadline pengujian dan menyimpan
catatan gangguannya. Pengulangan akhir memiliki nol gangguan baca. Helper cleanup
native kini mengamati ulang error AX sementara dalam deadline tiga detik yang
sudah ada. Inventori valid diperlukan untuk lulus, dan error persisten menggagalkan
pengujian. Dua regresi tambahan memeriksa kedua keadaan tersebut.

**Rolling akun Flow nyata lulus pada paket 0.3.0 dan host 0.10.1.** Sumber yang
kreditnya habis dilanjutkan ke akun tujuan melalui profil Chrome asli. Jalur
klasik membawa definisi karakter/suara, membuat serta memverifikasi aset tujuan,
memulihkan job yang sama, lalu mengunduh MP4 720 × 1280 dengan video lima detik
dan audio AAC. Hermes chat CLI menjalankan rolling mode Agent dengan gambar
potret lokal dan menghasilkan MP4 dengan ukuran serta durasi yang sama.
Hash dan decode penuh kedua file lulus. Sampel suara tujuan tersedia untuk
penilaian aksen/timbre pengguna. Peristiwa reset kuota akun Flow nyata belum
diamati. Logika kunjung ulang profil memiliki bukti regresi dan fixture native.
Gemini serta penerimaan kanal nyata pada CTX-01/PRO-02 tetap terbuka.

**Bukti historis 0.10.2 mencakup enam identitas task/conversation native Hermes.** Fixture
lokal memakai satu source extension, enam sesi pada satu profil, lalu susunan
tiga sesi per profil pada dua profil asli. Setiap sesi mempunyai kelompok jendela
terpisah. Harness saat uji membuat dua jendela per sesi, sehingga totalnya dua
belas jendela agen. Input paralel, Stop, penyelesaian, pembuatan target tambahan,
pembacaan direktori profil aktual, preservasi peer/manual, dan cleanup kembali
ke baseline lulus pada dua pengulangan lengkap. Uji ini memanggil registry/tool
native secara langsung. Penilaian kesesuaian jumlah jendela awal dikoreksi pada
0.10.3 melalui assertion satu jendela per sesi dan enam tambahan jendela native
untuk enam pemilik.

Uji menemukan kegagalan pembuatan target setelah profil aktif terakhir berubah.
Pemaksaan ID konteks profil sudah ada sejak commit `d33aa03`. Patch host 0.10.2
memakai pembukaan profil eksplisit melalui singleton Chrome yang telah
terverifikasi ketika CDP menolak ID tersebut sebelum membuat target. Sembilan
regresi khusus ditambahkan. Pemeriksaan awal fixture juga disesuaikan dengan
jumlah jendela harness aktual, payload akhir turn yang memuat `turn_id`, dan
penantian isi direktori profil hingga Chrome selesai mengisinya.

**Klarifikasi cleanup diterima.** Pengguna mengklarifikasi bahwa layar kedua yang
terhubung ke laptop membeku sehingga gambar Chrome masih terlihat. Klarifikasi
ini sesuai dengan pemeriksaan terakhir yang menunjukkan nol jendela native.
Audit juga mencatat pemilih profil yang kemudian ditutup. Pengulangan browser
native empat agen serta fixture rolling
kembali ke baseline. Inspeksi Flow read-only melalui Hermes menjaga jendela peer,
lalu seluruh jendela uji ditutup. Assertion inventori native sebelum dan sesudah
cleanup tetap menjadi bagian pengujian. LIF-01 kembali lulus berdasarkan bukti
uji tersebut dan klarifikasi pengguna.

Dokumen ini menjadi acuan spesifikasi, status implementasi, pemasangan, verifikasi,
dan pekerjaan tersisa. Status yang sudah memiliki bukti menjadi titik awal sesi
berikutnya. Riwayat rinci sebelum PRD tersedia pada bagian sumber bukti.

| Area | Implementasi | Terpasang lokal | Verifikasi dan status |
| --- | --- | --- | --- |
| Browser Chrome asli | Host 0.10.3 | Ya, plugin aktif dan provider dipilih | 342 tes otomatis lulus. Startup cold/windowless/warm serta enam identitas pada profil sama/campuran memakai satu jendela awal per sesi. Stop, cleanup dan pemeriksaan event macOS lulus. |
| Inventori/default/profil per sesi | Tersedia pada 0.7.0 | Ya | Penerimaan native empat agen/multiprofil diulang dan lulus. |
| Panduan `chrome_profiles` | Tersedia pada 0.7.0 | Ya | Schema aturan profil dibaca melalui `tool_describe` pada chat CLI baru. |
| Pemuat dan lifecycle extension pengguna | List/describe/run/enable/disable/remove | Ya, gateway direload resmi | 33 regresi khusus paket dan uji native enam jendela, disable/remove, serta pekerjaan lintas turn lulus. Template Flow 0.3.0 dan Gemini `inspect` tersedia. |
| Profil tetap/acak/per platform/subagent | Implementasi tersedia pada 0.8.0 | Ya | Regresi aturan profil dan uji native pemilihan profil child per paket lulus. Kanal nyata mengikuti item terbuka. |
| Rolling generik dan handoff | Implementasi tersedia pada 0.8.0 | Ya, gateway direload resmi | 31 regresi rolling lulus. Fixture CDP UI membuktikan A -> B -> C, profil sumber pending bersama peer, source receipt setelah Stop/reload, serta preservasi browser umum/extension lain/manual. |
| Extension Gemini | Paket `site_apps/gemini` 0.2.1 dengan operasi `inspect` dan `reply` | Lingkungan uji | Gemini Web Indonesia memakai penanda panel respons lengkap. Satu uji teks melalui tool Hermes pada akun nyata memulihkan jawaban dengan ID permintaan yang sama setelah hasil awal belum terkonfirmasi. Chat asal bertambah tepat satu pesan dan satu jawaban. |
| Extension Google Flow | Paket `site_apps/flow` 0.3.4 | Lingkungan uji | Resume mengikat hasil ke proyek asal dan mempertahankan hasil yang sempat terlihat. Uji akun nyata pada 0.3.3 menghasilkan satu JPEG tanpa kredit dan memakai ulang receipt yang sama. |

Status konfigurasi lokal diperiksa pada 16 November 2026. Browser provider bernilai
`original-chrome-default`, dan plugin tercantum aktif pada versi 0.10.3.
Gateway sudah reload dengan source 0.10.3
melalui mekanisme resmi Hermes. Respons memuat hook plugin termasuk
`subagent_start`, serta tool `browser_app`/`chrome_profiles` untuk sesi baru.
Chat CLI setelah reload berhasil menginspeksi UI Flow klasik → Agent → klasik.
Pengukuran induk mencatat satu jendela kerja tambahan pada 657 sampel, jendela
peer berisi `KEEP`, serta inventori native akhir nol. Tiga inspeksi berbagi
`time_origin` yang sama. Semua permintaan berstatus `not_submitted`.
Chat CLI memuat source host/paket yang diperbarui, membaca schema/panduan
serta menjalankan karakter dan video Agent. Probe native/checkpoint dari chat CLI
sesudah reload 0.9.0 tetap menjadi bukti fondasi integrasi.
Source pembanding Gemini berada pada `957aed5`, Flow mandiri pada `79d810a`.

### Cara memperbarui checklist

- `[x]` berarti hasil yang ditulis pada baris tersebut sudah selesai dengan bukti.
- `[ ]` berarti pekerjaan masih terbuka. Prototipe dicatat sebagai prototipe.
- Tabel status memisahkan kode, pemasangan lokal, dan jenis verifikasi.
- Setelah suatu item selesai, ubah checkbox, tambahkan commit/bukti ringkas, dan
  perbarui tabel status serta langkah berikutnya pada perubahan yang sama.
- Jika regresi ditemukan, buka kembali item terdampak dan catat gejala, bukti,
  serta pekerjaan lanjutnya. Item lain mempertahankan bukti yang masih berlaku.
- Saat melanjutkan kerja, baca ringkasan, pekerjaan terbuka, dan diff sejak bukti
  terakhir. Audit tambahan ditujukan pada perubahan, bukti yang sudah usang, atau
  kegagalan yang benar-benar ditemukan. Verifikasi dipilih sesuai dampak perubahan.

## 2. Tujuan produk dan aturan dasar

Plugin browser mendaftarkan Chrome asli melalui CDP untuk `browser_exec` Hermes.
Ekstensi memasok kontrol UI siap pakai ke jalur browsing tersebut.
Paket awal menyertakan **Gemini** dan **Google Flow**. Extension situs lain
dapat memakai kontrak umum yang sama.

- Chrome memakai profil asli, login/cookie tetap dikelola Chrome.
- Setiap agen/sesi memiliki jendela dan target sendiri, termasuk saat berbagi
  profil dengan agen lain atau browsing manual.
- Satu sesi membuka satu jendela awal untuk izin CDP, pemeriksaan profil dan
  akses situs. Penyerahan halaman awal kepada driver terjadi sekali. Permintaan
  target tambahan menghasilkan target baru milik sesi yang sama.
- Startup mencakup Chrome mati, hidup tanpa jendela, dan hidup dengan jendela.
  Pemilihan profil berlangsung langsung dan memakai satu aplikasi Chrome di Dock.
- Pemilihan profil bersifat dinamis, dengan default, pilihan eksplisit, profil
  tetap, atau acak sesuai konfigurasi pengguna.
- Flow dan Gemini mempunyai rolling layanan masing-masing ketika kredit/kuota
  untuk operasi yang diminta sudah habis atau tidak mencukupi.
- Extension dan panduannya disimpan pada direktori pengguna yang terpisah dari
  instalasi plugin. Pengguna dapat menambah, memperbarui, mengaktifkan,
  menonaktifkan, dan menghapus paket tersebut secara mandiri.
- Integrasi Hermes memakai kontrak publik plugin. Hermes core dan dependensi
  terkelolanya mengikuti pemeliharaan serta pembaruan resmi Hermes.
- Besarnya pemakaian kredit dan pilihan approval mengikuti otorisasi pengguna.
  Pengaturan Flow mendukung persetujuan otomatis yang sudah diminta pengguna.

## 3. Fondasi yang sudah selesai

- [x] **BAS-01** Registrasi BrowserProvider native dan pilihan Original Chrome
  dalam Browser Automation. Bukti berada pada `plugin.py` dan README 0.5.2.
- [x] **BAS-02** Startup/izin CDP pada profil asli, termasuk cold/windowless/warm,
  profil langsung, dan satu ikon Chrome. Bukti native tercatat pada baseline 0.5.1.
- [x] **BAS-03** Inventori dinamis, pilihan/default per sesi, pergantian A/B/A,
  serta pemeriksaan direktori profil terhapus/diganti. Bukti pada `tests/test_profiles.py`.
- [x] **BAS-04** Jendela terpisah untuk agen berprofil sama/berbeda dan perlindungan
  target manual. Bukti pada `tests/live_native.py` dan `tests/live_profiles.py`.
- [x] **BAS-05** Stop, finalisasi, unload, penolakan sesi terlambat, dan cleanup
  yang dapat dicoba ulang. Bukti pada `tests/test_provider.py` dan penerimaan native.
- [x] **BAS-06** Panduan model-facing `chrome_profiles`, README, tutorial, lisensi
  MIT, instalasi bersih, serta publikasi repo. Bukti 0.5.2 dan baseline distribusi.
- [x] **DOC-01** Audit kebutuhan dan prototipe extension tercatat dalam PRD ini.
  Riwayat rencana sebelumnya tersedia pada commit `a44823a`.

`profile_directory` yang terpasang merupakan default yang dapat diganti. Pemilihan
per sesi sudah tersedia melalui `chrome_profiles` dengan `list`, `select`, dan
`set_default`. Aturan profil tetap/per platform/subagent/acak menjadi PRO-01–PRO-05.

## 4. Kontrak paket yang tersedia pada baseline `84efb16`

Bagian ini mencatat struktur paket dan cara pemanggilan versi tersebut.
[Kontrak aktif](#kontrak-browser-dan-ekstensi) mengatur perilaku tool browser
berikutnya.

### Struktur dan pemasangan

Direktori bawaan yang diusulkan adalah `~/.hermes/browser-apps/`, dengan pilihan
lokasi melalui pengaturan plugin. Source paket dapat digunakan bersama, sementara
keadaan pekerjaan mengikuti pemilik sesi dan profil Hermes yang melayani pekerjaan.

```text
browser-apps/
  flow/
    app.json
    app.py
    SKILL.md
  gemini/
    app.json
    app.py
    SKILL.md
```

`app.json` mendeklarasikan identitas, versi kontrak, operasi, parameter, dan
kebijakan profil. `app.py` menyediakan fungsi situs. `SKILL.md` menyediakan panduan
opsional yang dibaca sesuai kebutuhan. Kedua paket awal menyertakan panduan lengkap.
Source dan resource tambahan dapat berada di dalam folder paket.

Contoh metadata minimum untuk salah satu operasi paket awal berikut.

```json
{
  "api_version": 1,
  "id": "flow",
  "name": "Google Flow",
  "profile_policy": "rotate_on_limit",
  "operations": {
    "inspect": {
      "description": "Baca mode dan pilihan yang tersedia pada Flow.",
      "parameters": {"type": "object", "properties": {}}
    }
  }
}
```

Kontrak entry point adalah `run(context, operation, params)`. Context menyediakan
identitas pemilik, akses `browser_exec` yang terikat sesi, pilihan profil saat ini,
dan penyimpanan hasil/posisi pekerjaan. Plugin meneruskan task/session/turn serta
konteks platform dari jalur publik Hermes. Paket memakai namespace fungsi sendiri.

Pada instalasi baru, template Gemini dan Flow disalin ke direktori paket ketika
paket tersebut belum tersedia. Versi paket yang sudah ada dimiliki pengguna.
Pembaruan instalasi plugin memperbarui host dan template bawaan. Pembaruan paket
pengguna dilakukan melalui pengelolaan paket yang eksplisit. Pilihan pengguna
untuk menghapus atau menonaktifkan paket tercatat dan tetap berlaku setelah update
host. Distribusi awal dan pemulihan instalasi mengikuti status pemasangan tersebut.

### Pintu pemanggilan umum

Tool umum bernama `browser_app`. Argumen utamanya adalah `action`,
`app`, `operation`, `params`, `session`, dan `job_id` jika melanjutkan pekerjaan.

| Action | Perilaku |
| --- | --- |
| `list` | Baca katalog paket terbaru, status aktif, dan ketersediaannya. |
| `describe` | Baca operasi, schema parameter, dan panduan paket yang diminta. |
| `run` | Jalankan operasi paket melalui context pemilik dan browser sesi tersebut. |
| `enable` | Aktifkan paket yang dipilih. |
| `disable` | Tutup penerimaan operasi baru, simpan posisi pekerjaan, dan cleanup resource milik paket pada lingkupnya. |
| `remove` | Lakukan lifecycle penonaktifan lalu hapus folder paket yang dituju. Hasil produksi dan catatan pekerjaan memiliki penyimpanan mandiri. |

Versi 0.7.0 menyediakan keenam aksi tersebut. Disable menyimpan flag dan menutup
sesi paket yang dimiliki proses Hermes yang melayani aksi. Setiap panggilan
browser terikat memeriksa flag. Proses Hermes lain membacanya pada panggilan
berikutnya dan mengelola perintah in-flight melalui lifecycle prosesnya sendiri.
`cleanup_pending` menyatakan callback aktif atau cleanup yang belum terkonfirmasi.
Remove menunggu keduanya selesai. Direktori paket berupa symlink dilepas melalui
entry-nya. Artefak dan checkpoint berada di plugin data, terpisah dari source paket.
Metadata memvalidasi bentuk schema parameter, lalu operasi memvalidasi nilainya.
Profil layanan dipilih melalui `chrome_profiles` dengan argumen `app`.

Kode host memuat metadata dan fungsi berdasarkan paket yang dipilih. Situs baru
serta operasi baru ditemukan dari direktori tersebut melalui schema umum ini.
Nama Flow/Gemini menjadi data paket dan preset awal.

### Pemuatan, pembaruan, dan hasil

- Source terbaru dipakai pada pemanggilan berikutnya, termasuk edit berukuran sama
  pada waktu berdekatan. Metadata dan modul diperiksa sebagai versi yang sesuai.
- Pemanggilan aktif memegang versi modul yang telah dimuat. Keadaan eksekusi milik
  agen/sesi/paket. Data login dan penyimpanan situs mengikuti profil Chrome asli.
- Kegagalan satu paket dikembalikan dengan identitas operasi dan sumber error.
  Katalog serta paket lain tetap mempunyai lifecycle masing-masing.
- Hasil umum memakai `status` dan `data`, ditambah error, identitas permintaan/job,
  profil/akun sumber, dan lokasi artefak yang relevan.
- Status mencakup `ok`, `running`, `quota_exhausted`, `needs_inspection`, dan `failed`.
  Penolakan kuota menyertakan bukti layanan serta posisi permintaan yang terdampak.
- Helper membaca DOM terkini secara terarah. Pengaturan/status/hasil ringkas dikirim
  kepada model. Pembacaan luas dan screenshot membantu pemeriksaan bila UI berubah.
- Sesi operasi mencakup pengaturan, unggahan, submit, menunggu hasil, dan unduhan.
  Observasi status memakai dokumen serta identitas permintaan yang sedang diikuti.

### Checklist fondasi extension

- [ ] **EXT-01** Direktori paket pengguna dan template awal yang menghormati paket
  yang sudah tersedia. Uji instalasi baru, update host, dan direktori pilihan.
  Bagian direktori default/pilihan dan pemuatan eksternal lulus pada 0.6.0.
  Template Flow tersedia pada 0.9.0, dengan regresi instalasi baru, edit pengguna,
  symlink serta tombstone disable/remove. Template Gemini kini memuat `inspect`.
- [x] **EXT-02** Penemuan/validasi `app.json`, operasi dan versi kontrak. Paket
  baru serta metadata/entry point yang keliru tercakup pada `tests/test_browser_apps.py`.
- [x] **EXT-03** Pemuatan `app.py`, namespace/context per pemilik, dan pembaruan
  antar pemanggilan. Source/relative import ukuran sama, edit cepat, fungsi lama
  yang sedang dimuat, dan dua pemanggil paralel lulus pada regresi 0.6.0.
- [x] **EXT-04** `browser_app` untuk katalog, bantuan dan eksekusi. Penambahan
  paket/operasi pada dua agen dan pembaruan source tanpa registrasi ulang lulus
  pada `tests/live_apps.py`. Enam sesi berbagi profil memakai enam jendela terpisah.
- [x] **EXT-05** Enable/disable/remove dengan lifecycle resource dan posisi pekerjaan
  terverifikasi pada 0.7.0. Native peer/manual dipertahankan, checkpoint/receipt
  tetap ada, re-enable memakai nama native baru. Regresi juga mencakup callback
  aktif, retry cleanup, paket rusak/link dan penghapusan source yang lambat.
- [x] **EXT-06** Bantuan paket dan panduan umum model-facing tersedia pada 0.7.0.
  Panduan berubah/opsional lulus regresi. Chat CLI baru berhasil membaca schema
  kedua tool, panduan paket temporer dan menjalankan probe native.

Uji 0.6.0 memakai paket fixture di direktori eksternal temporer melalui registry,
hook native Hermes dan `ctx.dispatch_tool`. Native `browser_exec` dapat memeriksa
sesi aplikasi milik pemanggil yang sama pada turn tersebut. Pemanggilan ulang
mempertahankan marker dan `performance.timeOrigin` halaman. Source dan panduan
paket nyata tersedia dalam tutorial. Penerimaan Gemini/Flow mengikuti GEM/FLO.

## 5. Aturan profil dan pemisahan konteks

Aturan berlaku pada lingkup sesi/agen, subagent, platform, atau default. Urutan
resolusi yang dipilih untuk implementasi adalah aturan sesi/agen, aturan subagent,
aturan platform, default parent, lalu default global. Aturan child yang eksplisit
mengalahkan default parent. Penguncian berlaku pada lingkup aturan yang dipilih
sampai pengaturan lingkup tersebut diubah.

Mode profil mendukung `fixed`, `default`, dan `random`. Mode acak memilih sekali
pada awal sesi, kemudian memakai hasil pilihan tersebut selama pekerjaan sesi.
Aturan tersimpan dipakai kembali pada turn berikutnya. Pilihan sementara mengikuti
umur sesi. Perubahan default dipakai sesi baru. Profil terhapus/diganti diperiksa
melalui inventori dan identitas direktori yang sudah tersedia.

Pada baseline `84efb16`, setiap agen mempunyai ruang sesi untuk browser umum
dan setiap extension. Contoh alias adalah `browser`, `flow`, dan `gemini`.
Namespace privat mengikat alias pada pemilik. Agen utama pada A, child pada B,
Flow pada C, dan Gemini pada D dapat berjalan bersamaan. Beberapa agen juga
dapat memakai satu profil dengan jendela masing-masing. Profil tetap untuk
browser umum berlaku pada sesi browser umum. Flow/Gemini mempunyai profil awal
dan urutan kandidat layanannya sendiri. Dalam [kontrak aktif](#kontrak-browser-dan-ekstensi),
kontrol situs bekerja pada jendela yang sudah dimiliki tugas `browser_exec`.

Konteks platform berasal dari sesi Hermes, dan hubungan parent/child berasal dari
hook publik. ID diteruskan sebagai identitas opaque. Profil Hermes menentukan
konfigurasi agen yang melayani pekerjaan. Profil Chrome menentukan direktori browser.

- [ ] **CTX-01** Penerusan identitas pada `ctx.dispatch_tool()`/`browser_exec`,
  persiapan namespace plugin, dan hook tepat sekali. Uji CLI, kanal, child dan sesi bernama.
  Bagian dispatch, task/session/turn asli, namespace aplikasi serta inspeksi native
  pemilik yang sama lulus pada regresi 0.6.0. Eksekusi paket temporer dari chat CLI
  melalui gateway juga lulus, termasuk identitas lengkap dan nama sesi native
  yang cocok. `tests/live_apps.py` menguji identitas
  parent/child dan route Telegram sintetis. Penerimaan pesan kanal nyata serta
  delegasi child melalui percakapan Hermes masih terbuka.
- [x] **PRO-01** Aturan sesi/agen dan profil tetap pada 0.7.0. Pengubahan dan
  persistensi aturan lulus regresi. Native sesi berbagi profil tetap memiliki
  jendela sendiri. Aturan sesi mengikat percakapan/alias lintas turn, sedangkan
  aturan agent mengikat task ID Hermes yang dapat berubah pada turn berikutnya.
- [ ] **PRO-02** Aturan WhatsApp/Telegram serta pewarisan parent/child. Uji
  parent A, child B, dua kanal bersamaan, serta routed Hermes profile berbeda.
  Implementasi hook publik, prioritas role/channel/parent, dua konfigurasi Hermes
  dan route sintetis lulus pada 0.7.0. Penerimaan pesan kanal dan delegasi nyata
  melalui gateway dengan routed homes masih terbuka.
- [x] **PRO-03** Mode default/acak dan prioritas resolusi lulus pada 0.7.0.
  Pilihan acak stabil pada sesi aktif, inventori dibaca segar, konfigurasi lama
  serta readback default tetap tercakup.
- [x] **PRO-04** Pemisahan pilihan/default dan rolling satu extension saat browser
  umum, extension lain serta job sumber aktif lulus pada fixture native 0.8.0.
  Jendela sumber mempertahankan marker/timeOrigin dan receipt yang sama.
- [x] **PRO-05** Inventori dinamis dan identitas direktori tetap dipakai pada 0.7.0.
  Penambahan/penghapusan/rename, penggantian direktori dan pemilihan ulang paket
  tanpa mengganggu pilihan peer lulus regresi. Perpindahan native multiprofil lulus.

Pilihan `running` dan `needs_inspection` menyimpan sesi, profil asal serta direktori
artefak lintas turn dalam proses yang sama. `context.checkpoint()` menulis posisi
JSON secara atomik, dan hasil paket disimpan sebagai `result.json`. Kebijakan baru
disimpan sebagai deferred ketika hasil masih diikuti pada profil asal. Akhir sesi,
Stop, disable dan unload melepaskan resource. Pemulihan otomatis setelah proses
berakhir, identitas akun serta handoff lintas profil memakai kontrak rolling 0.8.0.
Implementasi callback UI produksi pada Gemini/Flow mengikuti GEM/FLO.

## 6. Rolling kuota dan kelanjutan pekerjaan

Flow mendeklarasikan `rotate_on_limit`. Pengendali umum plugin menjalankan
keputusan rolling berdasarkan bukti yang dikembalikan paket. Gemini memakai
pengendali yang sama untuk `reply` teks dengan checkpoint portabel yang diberikan
pemanggil. `inspect` melaporkan petunjuk akun dan kuota yang terlihat.

Flow menyediakan pilihan manual dan otomatis. Mode manual menjadi default dan
menunggu profil tujuan yang ditentukan secara eksplisit melalui `target_profile`
bersama ID job. Mode otomatis mengikuti daftar `rolling_profiles.flow` setelah
layanan mengonfirmasi limit dan dapat diaktifkan dengan `handoff_mode.flow`.
Pekerjaan berstatus belum pasti tetap diperiksa pada profil asal dalam kedua
mode. Gemini menyediakan pilihan yang sama untuk penolakan model yang terbukti
sebelum Send dengan `handoff_mode.gemini` dan `rolling_profiles.gemini`.

Untuk paket tanpa deklarasi mode handoff, kandidat default mencakup seluruh
profil yang dapat mengakses layanan dalam urutan alami direktori. Profil awal
dan urutan pilihan pengguna dapat dikonfigurasi.

1. Pakai akun aktif selama masih dapat melakukan operasi yang diminta.
2. Saat layanan menyatakan kuota/kredit habis atau tidak mencukupi, catat akun aktif,
   layanan, operasi/model terdampak, posisi permintaan dan reset yang tersedia.
3. Segarkan inventori dan pilih kandidat berikutnya. Identitas akun diverifikasi
   pada layanan. Metadata akun Chrome menjadi petunjuk penemuan awal.
4. Akun yang sama pada beberapa profil berbagi status kuota untuk operasi terdampak.
   Kepemilikan jendela tetap mengikuti setiap agen/sesi.
5. Setelah seluruh kandidat habis, simpan posisi pekerjaan dan laporkan status kuota
   serta reset yang tersedia. Saat tersedia lagi atau pekerjaan dilanjutkan,
   pemeriksaan kembali dimulai dari awal putaran.

Status kuota mengikuti layanan/akun/operasi. Saldo bersama antarlayanan diakui
berdasarkan informasi yang benar-benar ditampilkan sumber layanan. Kebijakan biaya
mengikuti otorisasi pengguna dan kemampuan aktual layanan.

Permintaan yang sudah diterima mempertahankan akun, proyek/chat, dan identitas
hasil asal selama observasi/unduhan. Timeout atau hasil ambigu menjalani
rekonsiliasi permintaan asal. Hasil parsial disimpan untuk menentukan pekerjaan
tersisa. Rolling memilih tujuan pekerjaan berikutnya atau permintaan yang telah
ditolak kuota. Sesi bernama tambahan dapat memakai akun berikutnya saat hasil asal
masih ditunggu.

Pengendali membuat handoff dari konteks, instruksi, pengaturan, dan berkas lokal
pekerjaan. Akun tujuan membuka/membuat proyek/chat sendiri, mengunggah bahan, dan
mengikat referensi tujuan. ID dan riwayat native dimiliki akun sumber. File hasil,
catatan sumber permintaan, dan posisi pekerjaan disimpan terpisah dari source paket.

- [x] **ROT-01** Kuota dipetakan dari scope, bukti layanan serta penolakan request.
  Timeout/selector dan bukti tidak lengkap menjalani rekonsiliasi sumber. Regresi
  0.8.0 mencakup penolakan tersimulasi, ID hasil salah dan hasil parsial.
- [x] **ROT-02** Kandidat segar, urutan pilihan dan deduplikasi akun/scope lulus
  pada 0.8.0. A -> B -> C memakai CDP UI native. Tambah/hapus profil di tengah
  putaran dan akun yang sama di dua profil tercakup pada fixture otomatis.
- [x] **ROT-03** Seluruh kandidat habis, checkpoint dan reset -> A dengan bukti
  availability baru lulus. Cursor mempertahankan akun kerja lintas turn sampai
  kuota habis. Kebijakan profil baru mengambil prioritas atas cursor tersimpan.
- [x] **ROT-04** Packet handoff membawa input, checkpoint, source receipt, berkas,
  hasil selesai dan sisa pekerjaan. Callback mengikat parameter/ID tujuan.
  Regresi memeriksa file hilang, hasil parsial serta handoff yang terinterupsi.
- [x] **ROT-05** Intent ditulis sebelum submit dan receipt disimpan lewat accepted.
  Penguncian filesystem, Stop, ID/account/profile salah dan pemulihan lulus.
  Proses fixture benar-benar keluar setelah accepted, lalu recovery mengambil
  receipt yang sama tanpa submit kedua. Native UI menguji Stop/reload saat peer aktif.

Kontrak lengkap terdapat di [docs/ROLLING.md](docs/ROLLING.md). Paket opt-in
menyediakan `identify`, `run`, `handoff` dan `resume`. Penanda bukti berasal dari
UI layanan yang diperiksa callback. Jurnal, quota per akun/scope dan cursor
berada di plugin data. Aksi `describe` melalui `browser_exec.site_control` menampilkan job pemilik percakapan,
dan `run` menerima ID `job` untuk meneruskan rekonsiliasi. Callback produksi serta
bukti kuota/media Google yang sebenarnya masih menjadi penerimaan GEM/FLO.

## 7. Paket awal dan penerimaan fungsional

### Gemini

Perilaku Gemini custom menjadi acuan operasi. Pemilihan model/penalaran/tool,
pengisian prompt, dan unggahan memakai interaksi UI yang sesuai. DOM dan respons
aplikasi yang dipicu UI dapat dipakai untuk pembacaan streaming/identitas hasil.
Jalur tambahan dicatat per operasi. Preset model mengikuti pilihan pengguna dan
opsi yang tersedia pada akun.

- [ ] **GEM-01** Chat baru/lanjutan, model/penalaran, dan penyelesaian respons.
  Uji chat panjang serta pencocokan hasil dengan turn asal.
- [ ] **GEM-02** Unggahan dan streaming sesuai kontrak yang diimplementasikan.
  Uji file asli, kesiapan lampiran, delta dan hasil final, serta pembatalan.
- [ ] **GEM-03** Generate/edit gambar dan pengambilan file asli milik turn yang
  diminta. Uji gambar masukan dan hasil nyata.
- [ ] **GEM-04** Generate video serta pengambilan file asli milik turn tersebut.
  Uji file, metadata media, dan kepemilikan sesi hingga unduhan selesai.
- [ ] **GEM-05** Laporkan bukti limit UI dan waktu reset yang ditampilkan. Simpan
  status pekerjaan, lalu lanjutkan lintas akun menggunakan mode manual atau
  otomatis. Jalur `reply` dengan checkpoint dan blokir Send diuji lewat fixture
  lokal. Gemini 0.3.1 mempertahankan job saat profil tujuan terbukti berhenti
  sebelum Send. Regresi mencakup perubahan profil manual, kandidat otomatis,
  pemulihan setelah proses terputus, dan hasil belum pasti setelah Send.
  Bukti limit serta rekonsiliasi nyata pada UI tetap bagian penerimaan terbuka.

Source mandiri juga memiliki musik, temporary chat, dan tahapan Research. Cakupan
migrasinya dicatat per operasi ketika diimplementasikan. Daftar operasi paket
menyatakan kemampuan yang sudah tersedia. Catatan Research sumber masih menyebut
penerimaan laporan final sebagai pekerjaan verifikasi.

### Google Flow

Kedua mode ditangani melalui UI akun yang dipilih. Pilihan model, rasio, durasi,
kualitas, jumlah hasil dan referensi mengikuti kontrol yang tersedia. Nilai yang
hanya diminta melalui prompt dicatat sebagai permintaan. Hasil dipantau sampai
identitas media dan file asli dapat dikaitkan dengan permintaan asal.

- [x] **FLO-01** Mode klasik, pemilihan pengaturan, generate gambar/video, progres,
  dan unduhan. Uji readback pengaturan serta file nyata yang dapat didekode.
  Pada 0.9.0 Nano Banana 2.1 menghasilkan JPEG vertikal. Omni 1.2 Flash menghasilkan
  MP4 720 × 1280, video 3 detik, audio AAC. Durasi 5 detik, resolusi 360p,
  rasio 16:9 dan x3 juga lulus readback pengaturan tanpa submit.
- [x] **FLO-02** Mode Agent, kontrol yang tersedia, approval native sesuai pilihan
  pengguna, submit, progres, dan unduhan hasil sebenarnya.
  Pada 0.9.0 gambar dan video asli didekode. Chat Hermes CLI menghasilkan tepat
  satu video Agent, 720 × 1280, video 3 detik dan audio AAC. Approval radio 2
  dibaca kembali. Default model/rasio/count disertakan dalam instruksi Agent.
  Angka durasi/resolusi pada Agent mengikuti permintaan prompt dan hasil ukur.
- [x] **FLO-03** Unggahan, Ingredients/Frames, karakter dan suara sesuai kemampuan
  mode/model. Uji keterikatan referensi dan hasil/preview yang relevan.
  Pada 0.9.0 upload JPEG, ingredient gambar, serta video klasik memakai dua frame
  awal/akhir lulus dengan file MP4 asli terdekode. Pada 0.10.0, potret lokal dipakai
  untuk karakter native, nama/deskripsi/suara dibaca kembali setelah data siap.
  Suara kustom dari basis Achird menghasilkan WAV 3,4 detik yang terdekode dan
  memiliki ID audio tersimpan. Video klasik dan video Agent melalui Hermes CLI
  memakai karakter serta ID suara tersebut, masing-masing 720 × 1280, video
  5 detik dan audio AAC. Perbandingan potret binding dengan karakter tersimpan
  cocok. Pemulihan job karakter mempertahankan ID yang sama. Aksen, timbre dan
  naturalness diserahkan kepada pengguna melalui sampel asli.
  Regresi mencakup aktivasi menu Upload, benturan nama unggahan antar sesi,
  data suara editor yang terlambat dimuat, editor Agent yang diganti saat binding,
  binding ulang yang mempertahankan chip serta preview/save tanpa replay.
  URL preview stok sempat terbaca pada editor ketika data suara masih dimuat.
  Readback akhir menunggu sumber audio kustom yang benar.
- [ ] **FLO-04** Rolling serta kelanjutan proyek pada akun tujuan.
  - [x] Kuota sumber nyata habis, lalu Default → profil tujuan pada mode klasik
    serta Agent. Bukti berasal dari panel akun dan harga native model yang dipilih.
  - [x] File lokal serta pengaturan dibawa ke proyek tujuan yang identitasnya
    disimpan sebelum pengeditan judul. Pemulihan mempertahankan proyek tersebut.
  - [x] Karakter dan suara tujuan dibuat dari definisi sumber yang tersedia,
    dibaca ulang setelah tersimpan, dan diverifikasi pada ingredient video.
    Remix native yang diuji belum menghasilkan preset suara kustom yang valid.
  - [x] Preview/save suara dan pembuatan karakter memiliki receipt persiapan
    tersendiri di bawah job induk. ID aset persiapan terpisah dari receipt video.
  - [x] Video klasik tujuan serta video Agent melalui Hermes diunduh, cocok
    hash/ukuran filenya dan lulus decode penuh. Keduanya 720 × 1280 dengan video
    lima detik dan audio AAC. Job klasik pulih setelah persiapan terhenti.
  - [x] Output sumber yang sudah selesai tetap dipertahankan saat sisa jumlah
    output diteruskan. Cakupan ini diuji dengan regresi terarah. Fixture native
    menguji A → B → C, source pending, Stop/reload, dan preservasi peer/manual.
  - [ ] Reset/isi ulang kuota akun Flow nyata, lalu kunjung ulang profil awal.
    Flow 0.4.1 memulihkan proyek sumber dan sisa output setelah memeriksa ulang
    saldo dan harga native. Skenario manual, otomatis, dan akun yang berubah
    diuji dengan fixture lokal. Reset kuota asli dari provider belum diamati.
  Uji video unggahan dengan permintaan perubahan suara ditolak oleh Flow dan
  menampilkan pemberitahuan refund. Kegagalan provider tanpa identitas hasil
  tetap memerlukan inspeksi pada job sumber. Penilaian aksen/timbre suara tujuan
  dilakukan pengguna dari WAV aslinya.

## 8. Verifikasi integrasi dan distribusi

- [x] **LIF-01** Cleanup native lulus pada pengulangan browser, rolling, serta
  inspeksi Flow melalui Hermes. Inventori akhir kembali ke baseline dan seluruh
  jendela uji ditutup. Pengguna mengklarifikasi pengamatan awal sebagai gambar
  Chrome pada layar kedua yang membeku. Inventori native menjadi assertion akhir
  uji browser/rolling. Umur sesi extension teruji pada 0.7.0 untuk akhir turn, operasi
  `running`, Stop, finalisasi, disable dan unload. Uji native menjaga dokumen,
  profil dan direktori artefak saat turn diganti, lalu melepas resource pemilik
  yang tepat. Checkpoint/receipt berada di luar paket dan bertahan setelah cleanup.
- [x] **LIF-02** Host 0.10.3 lulus dengan satu jendela awal per sesi. Enam
  identitas task/conversation native pada profil sama serta profil campuran
  memakai source paket bersama melalui `tests/live_parallel.py`. Dua putaran
  input paralel, target tambahan pada profil yang benar, Stop/akhir turn,
  preservasi dokumen/input/artefak peer dan fixture manual, serta cleanup ke
  baseline lulus. Log macOS memuat nol event AboutThisMac dari Chrome.
- [ ] **LIF-03** Browser umum, Flow, Gemini dan jendela manual berjalan bersama.
  Uji perpindahan profil serta penghentian satu operasi saat peer masih aktif.
- [x] **LIF-04** Regresi native host 0.10.3 lulus saat Chrome mati total, hidup
  tanpa jendela, dan hidup dengan jendela manual pembanding. Setiap sesi memakai
  satu jendela awal pada profil yang diverifikasi. Input, Stop/reload, preservasi
  peer/manual dan cleanup lulus. Identitas proses Chrome sama pada windowless/warm.
  Observasi Dock selama penerimaan mencatat satu ikon Chrome pada sampel valid.
- [ ] **REL-01** Kedua paket awal tersedia pada instalasi bersih dan dapat dipanggil
  Hermes. Catat versi host/paket, source, dan permukaan CLI/kanal yang diuji.
  Tambahan pada 0.10.17 memastikan penyalinan awal paket mengikuti direktori
  profil Hermes aktif, termasuk `HERMES_HOME` kustom.
- [ ] **REL-02** Update host mempertahankan paket pengguna, lalu tambah/update/
  disable/remove extension tambahan melalui kontrak yang sama.
- [x] **REL-03** README, tutorial, template dan panduan paket menjelaskan
  pemilihan browser manual, kontrol situs, profil, rolling dan hasil. README
  dan tutorial menjelaskan cara mempertahankan serta melanjutkan jendela
  dan bahwa distribusi host tersedia dari URL Git.
- [ ] **REL-04** Pemeriksaan asal-usul/lisensi source dan dependency, paket bersih,
  secret scan, Git bersih, commit/push, serta SHA remote yang cocok.

Fixture lokal digunakan untuk regresi browser dan kondisi sulit seperti kuota,
error, serta pembatalan. Penerimaan operasi media mencakup pengujian nyata sesuai
permintaan dan otorisasi pengguna yang berlaku. Setiap hasil mempunyai identitas
permintaan dan artefak yang dapat diperiksa.

## 9. Hal yang perlu penyesuaian atau verifikasi

| Temuan | Jenis/status | Tindak lanjut dan pengaruh pada urutan kerja |
| --- | --- | --- |
| Laporan sisa jendela setelah uji | Diklarifikasi pengguna sebagai tampilan layar kedua yang membeku | Pemeriksaan terakhir nol jendela native. Pengulangan browser/rolling dan inspeksi Hermes lulus. Assertion inventori native menjadi bagian pengujian cleanup. |
| CDP menolak konteks profil asli setelah profil aktif terakhir berubah | Diperbaiki pada host 0.10.2 | Direproduksi pada dua profil dengan kode yang sudah ada sejak `d33aa03`. Pembukaan profil eksplisit memakai singleton terverifikasi. Sembilan regresi dan uji native enam identitas lulus. |
| Satu sesi membuka dua jendela awal | Diperbaiki pada host 0.10.3 | Halaman startup milik sesi diserahkan satu kali pada bootstrap driver. Native cold/windowless/warm, enam pemilik dan Flow melalui Hermes lulus dengan satu jendela kerja per sesi. |
| Chrome memicu Tentang Mac Ini saat input paralel | Diperbaiki pada host 0.10.3 | Relay menormalisasi native keycode yang mencerminkan angka Windows. Perbandingan 1.212 event keyboard, regresi native dan inspeksi Hermes mengonfirmasi input benar dan nol event AboutThisMac setelah patch. |
| Gangguan baca inventori AX sementara saat pengujian | Pengukuran diperbaiki | Pembacaan diulang dalam deadline yang sudah ada. Tes mewajibkan inventori valid dan menggagalkan error persisten. Pengulangan penerimaan akhir lulus. |
| Dua identitas supervisor native menyisakan reconnect setelah endpoint ditutup | Menunggu upstream sesuai keputusan pengguna | Mengikuti update resmi Hermes. Fondasi extension dapat dikerjakan. |
| Router Gemini memakai SDK baseline, pilot UI memiliki kontrak sendiri | Perlu implementasi GEM-02/GEM-05 | Sambungkan bukti kuota UI, file, streaming, dan kelanjutan chat pada pemilik sesi yang sama. |
| Catatan pembatalan Gemini paralel belum menjelaskan hilangnya satu target pra-uji | Perlu verifikasi LIF-03 | Reproduksi terfokus dan atribusi sebelum menetapkan patch. Paralel normal sudah tercatat berhasil. |
| Launcher bundel Gemini/Flow masih memakai `open -n` | Perlu penyesuaian integrasi | Extension memakai fondasi Chrome plugin mutakhir dan context yang disediakan host. |
| Source Gemini mencantumkan AGPLv3, host/Flow memakai MIT | Perlu pemeriksaan REL-04 | Pilih komponen dan tata distribusi yang sesuai sebelum membundel source untuk publikasi. |
| Warning konfigurasi pytest-asyncio dan cleanup direktori temporer | Catatan kualitas pengujian | Seluruh regresi yang dilaporkan lulus. Tindak lanjut diarahkan pada dampak yang ditemukan. |
| Cleanup akhir turn/disable pada 0.7.0 memakai nama dasar setelah profil berpindah | Diperbaiki pada 0.8.0 | Nama browser terkini dipakai. Regresi akhir turn, disable rolling dan peer native lulus. |
| Fixture UI membaca akun sebelum halaman siap | Fixture diperbaiki pada uji 0.8.0 | Penanda ready ditunggu sebelum account readback. Percobaan awal berhenti sebelum submit, lalu uji native lulus. |
| Kode probe chat awal salah mengutip string | Fixture diperbaiki pada uji 0.8.0 | Sintaks probe divalidasi sebelum pengulangan. Chat baru menjalankan native probe dan mengembalikan job cached yang sama. |

Baseline native Dock mempunyai 16.939 pembacaan valid, masing-masing satu ikon.
Observer juga mencatat 84 error pembacaan AX dan dua pembacaan Dock tidak lengkap.
Bukti itu tetap dilaporkan beserta batas observasinya. Proses yang berakhir sebelum
cleanup selesai dapat meninggalkan target. Login serta storage situs mengikuti
perilaku bersama profil Chrome asli.

Pengulangan enam identitas, regresi native, dan inspeksi Hermes pada 0.10.2
disertai 4.667 pembacaan Dock valid. Seluruhnya menunjukkan satu ikon Google
Chrome, dengan nol error pembacaan. Pengujian startup cold/windowless/warm
lengkap diulang pada 0.10.3 sesuai LIF-04.

Penerimaan 0.10.3 setelah jeda mencatat 13.171 sampel Dock valid, seluruhnya satu
ikon Google Chrome, dengan nol error baca. Inventori Chrome akhir nol. Pemeriksaan
log sejak awal penerimaan mencatat nol event AboutThisMac dari Chrome.

## 10. Urutan implementasi

Urutan di bawah mencatat fase implementasi awal. Pekerjaan terkini mengikuti
[checklist aktif](#urutan-perbaikan-dan-verifikasi). Status jeda dan panduan
pemulihan awal tercatat pada [HANDOFF.md](HANDOFF.md).

1. **Fondasi extension** — EXT-01 sampai EXT-04 dan CTX-01. Buktikan paket fixture
   eksternal, katalog, bantuan, pembaruan, serta konteks browser pemiliknya.
2. **Lifecycle dan profil** — EXT-05/EXT-06, PRO-01 sampai PRO-05, dan LIF-01.
   Buktikan pengaturan serta sesi per extension sebelum menghubungkan rolling.
3. **Rolling generik** — ROT-01 sampai ROT-05 dengan paket fixture, termasuk
   kuota habis, pemulihan, handoff dan permintaan yang masih aktif.
4. **Dua paket awal** — GEM-01 sampai GEM-05 dan FLO-01 sampai FLO-04. Gunakan
   perilaku source yang sudah diperiksa dan kontrak host yang sudah diuji.
5. **Penerimaan dan rilis** — LIF-02 sampai LIF-04 serta REL-01 sampai REL-04.
   Perbarui setiap status berdasarkan hasil yang benar-benar selesai.

## 11. Sumber bukti dan riwayat

| Bukti | Cakupan |
| --- | --- |
| `tests/test_*.py`, 170 lulus | Regresi plugin 0.5.2. Pemasangan/provider aktif diperiksa kembali saat penyusunan PRD. |
| `tests/test_*.py`, 192 lulus pada 0.6.0 | Termasuk 22 regresi pemuat paket, identitas, relative import dan pembaruan source. |
| `tests/test_*.py`, 216 lulus pada 0.7.0 | 33 tes paket dan 13 tes aturan profil, termasuk lifecycle paralel, checkpoint, pending lintas turn, prioritas aturan serta konfigurasi terpisah. |
| Host 0.10.3, 342 tes otomatis lulus | Dua belas regresi untuk penyerahan halaman awal, input keyboard dan pemeriksaan event macOS. Dua regresi tambahan memeriksa pemulihan baca inventori AX serta kegagalan persisten. |
| Native cold/windowless/warm pada 0.10.3 | Tiga pengulangan suite browser umum memakai satu jendela awal per sesi, menjaga peer, menguji input/Stop/reload dan kembali ke baseline. Empat belas file Browser Harness cocok dengan RECORD. |
| Profil, extension, rolling dan enam identitas pada 0.10.3 | Keempat suite native lulus. Enam pemilik pada profil sama serta campuran mempunyai enam jendela awal. Target tambahan mempunyai profil yang benar, dan Stop/akhir turn menjaga peer/manual. Pengulangan akhir setelah penyesuaian pengukur AX lulus. |
| Flow 0.3.0 melalui Hermes pada host 0.10.3 | Tiga inspeksi klasik → Agent → klasik menghasilkan `ok`, satu `time_origin`, satu jendela kerja, 657 sampel tanpa error baca, preservasi peer dan cleanup akhir nol. |
| Dock dan event macOS pada penerimaan 0.10.3 | Seluruh 13.171 sampel Dock menunjukkan satu ikon Chrome. Log macOS sejak awal penerimaan memuat nol event AboutThisMac dari Chrome. |
| Distribusi bersih 0.10.3 | Validasi Hermes menyatakan security scan safe, tanpa core override. Gitleaks dan pemindaian identitas pribadi pada ekspor source lulus. |
| Host 0.10.2, 328 tes otomatis lulus | Sembilan regresi tambahan mencakup penolakan konteks profil lama, singleton/profil terverifikasi, kepemilikan target, outcome tak pasti, batas jendela, dan preservasi error CDP lain. |
| `live_parallel.py`, dua pengulangan lengkap pada 0.10.2 | Enam identitas native berbagi source paket, satu profil lalu dua profil dengan susunan 3+3, dua putaran input, target tambahan dengan readback profil aktual, Stop/akhir turn dan preservasi peer/manual. Dua belas jendela agen per fase, cleanup kembali ke baseline. |
| Empat suite native dan inspeksi Flow melalui Hermes pada 0.10.2 | Browser umum, profil, extension dan rolling lulus. Empat belas file Browser Harness cocok dengan RECORD. Inspeksi klasik memakai tool `browser_app`, status `ok`. Jendela peer dipertahankan dan inventori akhir nol. Sebanyak 4.667 sampel Dock menunjukkan satu ikon, nol error baca. |
| Ekspor distribusi bersih 0.10.2 | Validasi plugin Hermes menyatakan security scan safe dan tanpa core override. Gitleaks serta pemeriksaan identitas pribadi pada source ekspor lulus. |
| Penguatan cleanup native, 319 tes otomatis lulus | Empat regresi memastikan sisa jendela native menyebabkan gagal, baseline dipertahankan, transisi penutupan diamati, dan error inventori gagal eksplisit. Uji browser serta rolling memeriksa kesamaan inventori native akhir dengan baseline. |
| `tests/test_*.py`, 315 lulus pada 0.10.1 | Termasuk handoff multi-output, harga native, preservasi hasil sumber, receipt persiapan per job/profil, pemulihan project/unggahan, hidrasi ingredient, serta pilihan suara karakter. |
| Flow 0.3.0 pada akun nyata dan Hermes chat CLI | Sumber nol kredit berlanjut ke akun tujuan. Video klasik dengan karakter/suara tujuan serta video Agent dengan potret lokal selesai, cocok SHA-256 dan lulus decode penuh. Peer sentinel mempertahankan time origin dan isi selama rolling Hermes. |
| `live_native.py` dan `live_rolling.py` pada 0.10.1 | Input focus, empat jendela agen terpisah, Stop/reload, hasil fixture A → B → C, preservasi manual/peer dan cleanup pemilik lulus. Browser Harness sesuai RECORD. |
| `tests/test_*.py`, 286 lulus pada 0.10.0 | Regresi bundel serta Flow, termasuk karakter/suara, identitas dan pemulihan job, menu Upload, namespace nama file antar agen, readback suara asinkron dan penggantian editor Agent. |
| Paket Flow 0.2.0 melalui CDP native | Bukti 0.9.0 untuk gambar/video, JPEG, Ingredients dan dua frame dipertahankan. Pembuatan karakter serta WAV suara kustom dan video klasik dengan kedua referensi lulus pada 0.10.0. Model uji Nano Banana 2.1 dan Omni 1.2 Flash. |
| Hermes chat CLI dengan Flow 0.2.0 | Karakter tersimpan selesai melalui pemulihan ID yang sama. Video Agent dengan karakter/suara dikirim sekali dan menghasilkan MP4 720 × 1280, video 5 detik dan audio AAC. Hash dan decode penuh independen lulus. Sampel audio tersedia untuk penilaian pengguna. |
| `live_native.py`, `live_profiles.py`, `live_apps.py`, `live_rolling.py` pada pengerjaan 0.10.0 | Keempat regresi native lulus, menjaga peer/manual dan resource masing-masing. Browser Harness pada kedua environment uji cocok dengan RECORD. |
| `tests/test_*.py`, 248 lulus pada 0.8.0 | 31 tes rolling dan regresi cleanup sesi yang namanya berubah. Proses fixture keluar setelah accepted untuk menguji jurnal/lease sebenarnya. |
| `tests/live_rolling.py`, 0.8.0 | CDP UI lokal menghitung submit, membuktikan A -> B -> C, receipt sumber, browser/extension peer, disable setelah rolling, Stop/reload dan target manual. |
| Regresi native umum, profil dan paket pada 0.8.0 | `live_native.py`, `live_profiles.py`, `live_apps.py` diulang. |
| Chat CLI 0.8.0 setelah reload resmi | Schema job, panduan paket, probe native serta pengambilan ulang job dengan `cached: true` diverifikasi dari hasil tool. Artefak/paket fixture dibersihkan. |
| `tests/live_apps.py`, 0.7.0 | Enam jendela satu profil, pemilihan profil child per paket, status pending lintas turn, disable/enable/remove, preservasi artefak/peer/manual dan unload pending. |
| `tests/live_native.py` dan `tests/live_profiles.py`, diulang pada 0.7.0 | Browser umum, empat agen, input/focus, Stop, reload, default/switch profil dan cleanup lulus. |
| Chat CLI setelah reload resmi 0.7.0 | Tool describe memuat aksi lifecycle serta aturan profil, panduan paket terbaca, probe native dan checkpoint berhasil dengan identitas lengkap. Paket/artefak uji dibersihkan. |
| `tests/live_apps.py`, 0.6.0 | Paket eksternal, dua situs, tiga identitas sintetis dan enam jendela, dokumen tetap, pembaruan source, inspeksi native dan Stop yang mempertahankan peer/manual. |
| `tests/live_native.py` dan `tests/live_profiles.py`, diulang pada 0.6.0 | Regresi browser umum dan multiprofil lulus. 14 source Browser Harness cocok dengan hash RECORD. |
| Validasi salinan distribusi bersih 0.6.0 | Registrasi tool/hook sesuai manifest, security scan safe, tanpa core override. |
| Chat CLI melalui gateway setelah reload resmi | `tool_call` menemukan `browser_app`, katalog berhasil dan melaporkan nol paket produksi terpasang. |
| Operasi paket temporer dari chat CLI | Hasil tool `browser_app` memuat identitas task/session/turn, output native yang benar dan nama sesi yang sama. Paket uji dihapus setelah penerimaan. |
| `tests/live_native.py` dan `tests/live_profiles.py` | Baseline penerimaan native empat agen/multiprofil, Stop, target manual, input, screenshot, reload dan cleanup. |
| Regresi Gemini custom, 588 lulus dan 40 live dilewati | Hasil penuh source yang diaudit. Uji ini memiliki guard offline. |
| Regresi Flow mandiri, 118 lulus | Kontrak controller dan lifecycle Chrome bundel source pembanding. |
| Prototipe helper dua workspace | Paket baru dan perubahan fungsi ditemukan pada panggilan berikutnya. Fungsi penanda dan direktori temporer dipakai untuk uji. |
| Riwayat 0.5.1/0.5.2 | Startup, Dock, profil dinamis, panduan model-facing dan instalasi bersih. |

Rincian naratif dan hasil penerimaan sebelum PRD dipertahankan pada riwayat Git.
[Plan dan riwayat penerimaan sebelum PRD](https://github.com/dhansxd/hermes-original-chrome-cdp/blob/a44823a83ec01a89ff13163eb462516eebd4a601/PLAN.md)

Kontrak publik dan pola ekstensi yang menjadi referensi tercantum berikut.

- [Panduan plugin Hermes](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- [Konteks dan lifecycle subagent](https://hermes-agent.nousresearch.com/docs/developer-guide/observer-hooks)
- [Helper dan domain skills Browser Harness](https://github.com/browser-use/browser-harness/blob/main/AGENTS.md)
- [Referensi komunitas Gemini CLI](https://github.com/Zahed316/google-gemini-cli)
