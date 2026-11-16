# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# Native chat acceptance after owner restart

Verified using actual browser_exec, backend original-chrome-default, fallback_used false throughout.

- Session overflow-native-final: new owned data-URL fixture, wait_for_load and page_info succeeded.
- Timer fetches every 30ms auto-stopped after 52s. Returned from browser tool; foreground terminal sleep 55s created genuine inter-call idle. Subsequent JS reported elapsedMs 63921, 721 successful fetches, zero failures, stopped true and count 1. wait_for_load and page_info succeeded. Timer throttling means this alone was not claimed to prove overflow.
- Separate bounded local data-URL burst scheduled once: 30 batches of 100 fetches, no external service traffic. After a 12s inter-tool wait, readback showed 3000 successes, zero failures, done true. page_info and wait_for_load succeeded.
- wait_for_network_idle on that deliberately damaged history explicitly reported event_buffer_overflow: observation incomplete for this held session; no action replay. Error was caught and reported, not hidden or treated as complete history.
- Fresh named session overflow-native-scenery-final opened [private authenticated test page] wait_for_load, page_info and body read succeeded. Visible controls Logout/Profile establish logged-in the private test site UI on this read. wait_for_network_idle returned True. No login or account mutation performed.

Conclusion: first navigation, inter-call liveness, normal metadata after actual overflow, explicit lost-history limitation and fresh-session browsing all passed the native chat route. the private test site login persisted. This is bounded acceptance, not a promise all websites or unbounded traffic cannot fail.

No finish_browser invoked because its existing policy can close personal Chrome; no personal browser shutdown or broad target cleanup performed. Video task remains stopped. Source file already downloaded earlier is not a new video result.
