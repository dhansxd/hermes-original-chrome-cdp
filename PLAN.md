# PRD — Original Chrome for Hermes dan extension situs

Revisi PRD 1, 15 November 2026.

## 1. Status dan langkah berikutnya

**Kebutuhan produk sudah cukup untuk memulai implementasi fondasi extension.**
Langkah berikutnya adalah EXT-01 sampai EXT-04 dan pengujian penerusan konteks
pada CTX-01. Riset tambahan diarahkan ke kontrak teknis atau kegagalan yang ditemukan
ketika mengerjakan checklist terkait.

Dokumen ini menjadi acuan spesifikasi, status implementasi, pemasangan, verifikasi,
dan pekerjaan tersisa. Status yang sudah memiliki bukti menjadi titik awal sesi
berikutnya. Riwayat rinci sebelum PRD tersedia pada bagian sumber bukti.

| Area | Implementasi | Terpasang lokal | Verifikasi dan status |
| --- | --- | --- | --- |
| Browser Chrome asli | Selesai pada 0.5.2 | Ya, plugin aktif dan provider dipilih | 170 tes offline lulus. Penerimaan native startup, profil, jendela dan cleanup tercatat pada baseline. |
| Inventori/default/profil per sesi | Selesai pada 0.5.2 | Ya | Offline dan penerimaan native empat agen/multiprofil tercatat. |
| Panduan `chrome_profiles` | Selesai pada 0.5.2 | Ya | Schema native `tool_describe` sudah diverifikasi. |
| Pemuat extension pengguna | Prototipe fungsi penanda | Belum | Pemuatan/pembaruan pada dua workspace terpisah lulus secara offline. Kontrak produk masih perlu implementasi. |
| Profil tetap/acak/per platform/subagent | Spesifikasi tersedia | Belum | PRO-01 sampai PRO-05 masih terbuka. |
| Rolling generik dan handoff | Spesifikasi tersedia | Belum | ROT-01 sampai ROT-05 masih terbuka. |
| Extension Gemini | Source dan pilot UI mandiri tersedia | Belum sebagai extension plugin | Regresi source 588 lulus, 40 tes live dilewati. Migrasi UI/routing dan penerimaan extension masih terbuka. |
| Extension Google Flow | Controller mandiri tersedia | Belum sebagai extension plugin | 118 tes source offline lulus. Penerimaan media pada repo mandiri tercatat. Integrasi extension masih terbuka. |

Status konfigurasi lokal diperiksa pada 15 November 2026. Browser provider bernilai
`original-chrome-default`, dan plugin tercantum aktif. Kode runtime plugin mengacu
pada `f072557`, versi 0.5.2. Commit setelahnya sebelum PRD berisi perubahan dokumen.
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

Satu plugin browser Hermes menyediakan Chrome asli melalui CDP untuk browsing
umum dan extension yang dapat ditambah pengguna bersama agennya. Paket awal
menyertakan **Gemini** dan **Google Flow**. Extension situs lain dapat memakai
kontrak umum yang sama.

- Chrome memakai profil asli, login/cookie tetap dikelola Chrome.
- Setiap agen/sesi memiliki jendela dan target sendiri, termasuk saat berbagi
  profil dengan agen lain atau browsing manual.
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

## 4. Kontrak extension yang akan diimplementasikan

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

Tool yang direncanakan bernama `browser_app`. Argumen utamanya adalah `action`,
`app`, `operation`, `params`, `session`, dan `job_id` jika melanjutkan pekerjaan.

| Action | Perilaku |
| --- | --- |
| `list` | Baca katalog paket terbaru, status aktif, dan ketersediaannya. |
| `describe` | Baca operasi, schema parameter, dan panduan paket yang diminta. |
| `run` | Jalankan operasi paket melalui context pemilik dan browser sesi tersebut. |
| `enable` | Aktifkan paket yang dipilih. |
| `disable` | Tutup penerimaan operasi baru, simpan posisi pekerjaan, dan cleanup resource milik paket pada lingkupnya. |
| `remove` | Lakukan lifecycle penonaktifan lalu hapus folder paket yang dituju. Hasil produksi dan catatan pekerjaan memiliki penyimpanan mandiri. |

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
- [ ] **EXT-02** Penemuan/validasi `app.json`, operasi dan versi kontrak. Uji paket
  baru serta paket dengan metadata/entry point yang tidak sesuai.
- [ ] **EXT-03** Pemuatan `app.py`, namespace/context per pemilik, dan pembaruan
  antar pemanggilan. Uji source ukuran sama, edit cepat, dan operasi lama masih aktif.
- [ ] **EXT-04** `browser_app` untuk katalog, bantuan dan eksekusi. Uji penambahan
  paket/operasi pada dua agen tanpa mendaftarkan schema per situs.
- [ ] **EXT-05** Enable/disable/remove dengan lifecycle resource dan posisi pekerjaan
  yang terverifikasi. Uji satu paket dinonaktifkan saat paket/agen lain berjalan.
- [ ] **EXT-06** Bantuan paket dan panduan umum model-facing yang dapat ditemukan.
  Uji perubahan panduan, panduan opsional, serta pemakaian pada sesi Hermes baru.

Prototipe yang sudah lulus memakai fungsi penanda di direktori temporer dan dua
workspace Browser Harness. Hasil itu membuktikan mekanisme helper, sementara
EXT-01–EXT-06 mencakup penerimaan kontrak produk yang sebenarnya.

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

Setiap agen mempunyai ruang sesi untuk browser umum dan setiap extension. Contoh
alias adalah `browser`, `flow`, dan `gemini`. Namespace privat mengikat alias pada
pemilik. Agen utama pada A, child pada B, Flow pada C, dan Gemini pada D dapat
berjalan bersamaan. Beberapa agen juga dapat memakai satu profil dengan jendela
masing-masing. Profil tetap untuk browser umum berlaku pada sesi browser umum.
Flow/Gemini mempunyai profil awal dan urutan kandidat layanannya sendiri.

Konteks platform berasal dari sesi Hermes, dan hubungan parent/child berasal dari
hook publik. ID diteruskan sebagai identitas opaque. Profil Hermes menentukan
konfigurasi agen yang melayani pekerjaan. Profil Chrome menentukan direktori browser.

- [ ] **CTX-01** Penerusan identitas pada `ctx.dispatch_tool()`/`browser_exec`,
  persiapan namespace plugin, dan hook tepat sekali. Uji CLI, kanal, child dan sesi bernama.
- [ ] **PRO-01** Aturan sesi/agen dan profil tetap. Uji pengubahan aturan dan
  pemakaian profil yang sama oleh beberapa agen.
- [ ] **PRO-02** Aturan WhatsApp/Telegram serta pewarisan parent/child. Uji
  parent A, child B, dua kanal bersamaan, serta routed Hermes profile berbeda.
- [ ] **PRO-03** Mode default/acak dan prioritas resolusi. Uji pilihan acak stabil
  sepanjang sesi dan konfigurasi lama yang hanya memiliki `profile_directory`.
- [ ] **PRO-04** Ruang profil browser umum dan tiap extension yang independen.
  Uji rolling satu extension sementara browser umum dan extension lain digunakan.
- [ ] **PRO-05** Penambahan/penghapusan/rename/pergantian direktori saat routing.
  Uji pemilihan ulang dan resource yang sudah dimiliki sesi lain.

## 6. Rolling kuota dan kelanjutan pekerjaan

Flow dan Gemini mendeklarasikan `rotate_on_limit` pada paket awal. Pengendali umum
plugin menjalankan keputusan rolling berdasarkan bukti yang dikembalikan paket.
Kandidat default mencakup seluruh profil yang dapat mengakses layanan, dalam urutan
alami direktori. Profil awal atau urutan pilihan pengguna dapat dikonfigurasi.

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

- [ ] **ROT-01** Klasifikasi kuota dan status permintaan yang terverifikasi.
  Uji penolakan nyata tersimulasi, timeout, error CDP/selector, dan hasil parsial.
- [ ] **ROT-02** Urutan seluruh kandidat, deduplikasi akun, dan inventori mutakhir.
  Uji A -> B -> C, profil berubah, dan beberapa profil dengan akun yang sama.
- [ ] **ROT-03** Semua kuota habis lalu pulih. Uji semua kandidat terkunjungi,
  posisi tersimpan, dan reset -> A dengan bukti ketersediaan baru.
- [ ] **ROT-04** Handoff konteks dan bahan, termasuk referensi milik akun tujuan.
  Uji kelanjutan pekerjaan setelah berganti akun.
- [ ] **ROT-05** Kepemilikan job aktif, Stop, error, dan pemulihan setelah proses
  berakhir. Uji pengambilan hasil asal setelah operasi lain berpindah profil.

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
- [ ] **GEM-05** Rolling UI dan handoff memakai pengendali umum. Uji penolakan
  kuota yang dipetakan ke hasil helper serta kelanjutan lintas akun.

Source mandiri juga memiliki musik, temporary chat, dan tahapan Research. Cakupan
migrasinya dicatat per operasi ketika diimplementasikan. Daftar operasi paket
menyatakan kemampuan yang sudah tersedia. Catatan Research sumber masih menyebut
penerimaan laporan final sebagai pekerjaan verifikasi.

### Google Flow

Kedua mode ditangani melalui UI akun yang dipilih. Pilihan model, rasio, durasi,
kualitas, jumlah hasil dan referensi mengikuti kontrol yang tersedia. Nilai yang
hanya diminta melalui prompt dicatat sebagai permintaan. Hasil dipantau sampai
identitas media dan file asli dapat dikaitkan dengan permintaan asal.

- [ ] **FLO-01** Mode klasik, pemilihan pengaturan, generate gambar/video, progres,
  dan unduhan. Uji readback pengaturan serta file nyata yang dapat didekode.
- [ ] **FLO-02** Mode Agent, kontrol yang tersedia, approval native sesuai pilihan
  pengguna, submit, progres, dan unduhan hasil sebenarnya.
- [ ] **FLO-03** Unggahan, Ingredients/Frames, karakter dan suara sesuai kemampuan
  mode/model. Uji keterikatan referensi dan hasil/preview yang relevan.
- [ ] **FLO-04** Rolling serta kelanjutan proyek pada akun tujuan. Uji konteks,
  media lokal, referensi tujuan, dan hasil yang sudah diterima pada akun asal.

## 8. Verifikasi integrasi dan distribusi

- [ ] **LIF-01** Sesi extension mengikuti umur operasi dan kebutuhan hasil. Uji
  akhir turn, operasi `running`, Stop, finalisasi, disable dan unload.
- [ ] **LIF-02** Enam agen pada profil sama serta profil campuran. Uji source
  paket bersama, jendela berbeda, operasi paralel, dan cleanup pemilik yang tepat.
- [ ] **LIF-03** Browser umum, Flow, Gemini dan jendela manual berjalan bersama.
  Uji perpindahan profil serta penghentian satu operasi saat peer masih aktif.
- [ ] **LIF-04** Regresi startup cold/windowless/warm, profil langsung dan satu
  ikon Dock pada versi yang akan dipublikasikan.
- [ ] **REL-01** Kedua paket awal tersedia pada instalasi bersih dan dapat dipanggil
  Hermes. Catat versi host/paket, source, dan permukaan CLI/kanal yang diuji.
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
| Dua identitas supervisor native menyisakan reconnect setelah endpoint ditutup | Menunggu upstream sesuai keputusan pengguna | Mengikuti update resmi Hermes. Fondasi extension dapat dikerjakan. |
| Router Gemini memakai SDK baseline, pilot UI memiliki kontrak sendiri | Perlu implementasi GEM-02/GEM-05 | Sambungkan bukti kuota UI, file, streaming, dan kelanjutan chat pada pemilik sesi yang sama. |
| Catatan pembatalan Gemini paralel belum menjelaskan hilangnya satu target pra-uji | Perlu verifikasi LIF-03 | Reproduksi terfokus dan atribusi sebelum menetapkan patch. Paralel normal sudah tercatat berhasil. |
| Launcher bundel Gemini/Flow masih memakai `open -n` | Perlu penyesuaian integrasi | Extension memakai fondasi Chrome plugin mutakhir dan context yang disediakan host. |
| Source Gemini mencantumkan AGPLv3, host/Flow memakai MIT | Perlu pemeriksaan REL-04 | Pilih komponen dan tata distribusi yang sesuai sebelum membundel source untuk publikasi. |
| Warning konfigurasi pytest-asyncio dan cleanup direktori temporer | Catatan kualitas pengujian | Seluruh regresi yang dilaporkan lulus. Tindak lanjut diarahkan pada dampak yang ditemukan. |

Baseline native Dock mempunyai 16.939 pembacaan valid, masing-masing satu ikon.
Observer juga mencatat 84 error pembacaan AX dan dua pembacaan Dock tidak lengkap.
Bukti itu tetap dilaporkan beserta batas observasinya. Proses yang berakhir sebelum
cleanup selesai dapat meninggalkan target. Login serta storage situs mengikuti
perilaku bersama profil Chrome asli.

## 10. Urutan implementasi

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
