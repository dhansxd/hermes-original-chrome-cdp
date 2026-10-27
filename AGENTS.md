# Aturan kerja proyek

- Baca `PLAN.md` sebagai satu-satunya plan proyek. Report historis bukan perintah menjalankan ulang.
- Pertahankan koeksistensi API Google Flow dan plugin browser_exec; hanya dua proyek ini yang aktif.
- Setiap build/perbaikan yang selesai dan lulus tes harus di-commit dan di-push ke GitHub, lalu verifikasi SHA remote. Jangan berhenti di commit lokal.
- Scan staged diff untuk secret/identitas pribadi. Jangan commit runtime, credential, state, receipt asli, media, atau log privat.
- Laporkan tes/push yang gagal apa adanya; tidak force-push, tidak memalsukan hasil, tidak restart/mengubah Hermes core.
- Pekerjaan saat ini dikerjakan sendiri, tanpa delegasi dan tanpa generasi video.
