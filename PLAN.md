# PRD — Original Chrome for Hermes dan extension situs

Revisi PRD 26, 21 November 2026.

## 1. Status dan langkah berikutnya

Di cabang perombakan, Hermes memanggil tombol lewat parameter `site_control`
dan helper DOM lewat `code` pada tool `browser_exec` yang sama. Katalog sesi baru tidak lagi menawarkan `browser_app`.
Untuk distribusi publik masih ada satu masalah pada validator katalog Hermes,
dijelaskan di butir 2. [AGENTS.md](AGENTS.md) dan kontrak di bawah menjadi
acuan. [HANDOFF.md](HANDOFF.md) mencatat perilaku versi sebelumnya.

### Kontrak browser dan ekstensi

- Pasang, aktifkan, nonaktifkan, dan hapus plugin melalui pengelola plugin resmi
  Hermes (`hermes plugins install`, `enable`, `disable`, dan `remove`).
  Saat plugin diaktifkan, `browser_exec` otomatis memakai Chrome asli melalui
  CDP. Saat plugin dinonaktifkan atau langsung dihapus dalam keadaan aktif,
  Hermes otomatis kembali ke pilihan browser sebelum aktivasi. Jika sebelumnya
  memakai pengaturan bawaan, pulihkan pengaturan bawaan itu. Jika pengguna
  memilih provider tertentu, pulihkan pilihannya. Mengaktifkan kembali plugin
  harus langsung memilih Chrome asli lagi. Pengguna cukup menjalankan tindakan
  plugin yang sesuai tanpa memilih ulang browser di `hermes tools`.
- Plugin sudah mendaftarkan Chrome asli sebagai provider browser Hermes.
  Pertahankan perilaku `browser_exec`, termasuk navigasi, pembacaan DOM,
  screenshot dan penggunaan jendela tugas. Tambahan untuk Gemini, Google Flow
  dan situs lain hanya berupa kontrol UI siap pakai melalui tool yang sama.
  Hapus tool `browser_app` beserta deklarasi, registrasi, dan jalur
  pemanggilannya. Pertahankan paket ekstensi beserta kontrol situsnya.
  Klik atau ketik langsung lewat CDP pada halaman aktif menghemat waktu dan
  token karena Hermes cukup memakai kontrol yang sudah dikenal. Panduan
  situs dapat menjelaskan cara menggunakan kontrol tersebut.
- Satu tugas memakai satu jendela Chrome asli dan sambungan CDP yang sama
  sejak aksi pertama sampai seluruh permintaan selesai. Submit, cek progres,
  pembacaan hasil, unduhan, dan pengiriman yang diminta berlangsung dalam
  pekerjaan itu. Status `running` adalah progres. Setelah hasil dan langkah
  yang diminta terverifikasi, Hermes memberi jawaban akhir dan plugin
  melepaskan jendela milik tugas. Stop dan kegagalan terminal memakai cleanup
  yang sesuai. Tugas boleh memakai browser berkali-kali selama dibutuhkan.
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
2. [ ] Selesaikan perombakan dan validasi distribusi publik.
   - [ ] Terapkan dan verifikasi perpindahan browser otomatis sesuai kontrak.
     Versi 0.11.1 masih memerlukan pemilihan browser secara manual sesuai
     [tutorial](docs/TUTORIAL.md#switch-back-disable-and-uninstall).
     - Periksa dulu jalur resmi enable, disable, dan remove, termasuk remove
       saat gateway berhenti. Tentukan kapan pilihan sebelumnya dapat disimpan
       dan dipulihkan. Pada Hermes v0.23.2, `ctx.set_config` hanya menulis
       pengaturan milik plugin dan CLI remove menghapus berkas plugin. Jika satu
       jalur tidak mendukung pemulihan, catat batasannya untuk dibahas sebelum
       memilih implementasi. [API pengaturan](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/hermes_cli/plugins_context.py#L75-L89) · [Alur remove](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/hermes_cli/plugins_cmd_remove.py#L121-L141)
     - Gunakan profil Hermes uji. Mulai dari konfigurasi bawaan, lalu ulangi
       dengan provider pilihan pengguna dan dengan endpoint CDP yang sudah
       dikonfigurasi.
       Jalankan `browser_exec` setelah enable, disable, enable ulang, dan remove
       langsung saat aktif. Cocokkan browser yang dipakai dan konfigurasi yang
       dipulihkan dengan keadaan awal, termasuk pilihan yang semula kosong.
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
   - [ ] Lulus `hermes plugins validate` untuk katalog publik. Hermes mendukung
     perluasan handler melalui izin `tools.override` pada profil pengguna.
     Validator katalog tetap melaporkan benturan nama `browser_exec` ketika
     registrasi tersebut tercantum di manifest.
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
   - [x] Pada 0.11.2, `continue_running` meneruskan permintaan ke pembaca
     hasil paket bila tersedia. Jika paket tidak punya pembaca tanpa argumen
     wajib, atau pembacaan hasil perlu inspeksi, `browser_exec` mengamati
     DOM pada sesi milik tugas. Agen dapat menentukan selector hasil akhir
     yang spesifik sekali dan memakainya pada pemeriksaan berikutnya. Job
     yang memiliki ID tetap membutuhkan konfirmasi hasil melalui paketnya.
   - [ ] Periksa satu tugas nyata dari sesi Telegram baru di versi yang diuji.
     Cocokkan panggilan setelah status `running` dengan perubahan status di
     situs, hasil yang diterima pengguna, dan penutupan jendela tugas. Jika
     terhenti, catat operasi terakhir beserta hasilnya agar patch berikutnya
     memperbaiki penyebab yang teramati.
   - [x] Uji situs lokal di Chrome asli melalui Hermes: satu paket tanpa
     pembaca hasil melewati enam pemeriksaan tertunda. Pemeriksaan ketujuh
     membaca hasil pada dokumen dan jendela yang sama. Uji isolasi dan
     cleanup lulus. Regresi terpisah memeriksa Stop ketika observasi sedang
     menunggu dan memastikan jendela agen lain tetap tersedia. Pengiriman
     melalui bot Telegram pada rilis ini masih memerlukan uji tersendiri.
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
     pembanding kembali utuh sesudah cleanup. Pengiriman lampiran ke Telegram
     pada instalasi utama masih belum diuji dengan cabang ini.
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
   temuan lewat `record_missing_control`. Uji Telegram berikutnya belum
   menghasilkan catatan untuk kontrol yang memang belum dipetakan. Temuan
   yang terverifikasi menjadi bahan menambahkan tombol ketika diminta.

Untuk Google Flow, pertahankan pemisahan cara menggunakan mode Klasik dan Agent
sesuai butir 4 dan panduan paket. Pilihan profil serta mode perpindahan manual
atau otomatis yang sudah disetujui mengikuti [kontrak rolling](docs/ROLLING.md).
Periksa hasil dan identitas permintaan asal sebelum melanjutkan ke profil lain.

### Fitur setelah perbaikan lulus

- [ ] Biarkan jendela tertentu tersedia untuk pengguna ketika diminta secara
  eksplisit atau ketika tujuan tugas jelas mengharuskan pengguna melanjutkan
  di jendela itu. Pekerjaan Hermes selesai setelah halaman atau tindakan yang
  diminta benar-benar siap digunakan. Menyiapkan video untuk ditonton hanyalah
  salah satu contoh. Status `running` sendiri tidak memicu fitur ini.
- [ ] Gunakan identitas jendela yang tepat untuk menutupnya ketika pengguna
  meminta pada giliran berikutnya. Uji bahwa jendela yang dipakai pengguna
  tetap tersedia, penutupan berikutnya hanya mengenai jendela yang dirujuk,
  dan tugas biasa tetap menjalankan cleanup setelah selesai.

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
- [ ] **REL-03** README, tutorial, template dan panduan menjelaskan ekstensi,
  profil, rolling, hasil, serta batas kemampuan yang masih terbuka.
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
