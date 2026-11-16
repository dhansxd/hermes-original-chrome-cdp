# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# Shared event-buffer overflow repair

## Status

Implemented in the installed plugin source; **not activated or verified in the running parent native-chat runtime**. Exact native-symptom reproduction and repaired acceptance passed through real disposable Chrome, `ChromeProvider.execute`, retained shared observer, and actual bounded Python workers. No Hermes/personal Chrome restart or live reload performed.

Prior native facts supplied by parent remain separate: first navigation succeeded after the resume repair; the held WebSocket survived about 59 seconds with 1733 successful synthetic fetches. The subsequent metadata failure was not keepalive loss. This repair addresses that new overflow defect, not the private test site rendering or authentication.

## Root cause and repair

`Wire.events` evicts at 4000 and sets a sticky global `event_overflow`. Observer copied that flag into every worker. `BoundBrowser.send` rejected **all** session/pending-dialog/drain metadata when it was set. Thus successful JS could be followed by a page_info error; a subsequent named session inherited the same poison. Worker-local overflow could also be overwritten by the next parent response.

Changed production files only: `binding.py`, `worker.py`, `observer.py`.

- Current session metadata and pending-dialog snapshots no longer depend on historical retention. Existing uncertain-dialog refusal remains.
- Track gaps by the **evicted event's held CDP session ID**, not by incoming event or requesting named session. Retain the global overflow diagnostic; never clear it to pretend history recovered.
- `drain_events` and therefore `wait_for_network_idle` explicitly reject the damaged attachment's incomplete history. Repeated drains/new Python workers do not reset it. A distinct newly armed attachment is a fresh observation epoch, not reconstruction of old history. No automatic detach/reconnect is added.
- Route owned session events to their caller; another named session cannot consume their history. Global ownership events retain the existing callback route; public drains remain active-session-only.
- Worker aggregation remains capped at 4000. Local eviction is sticky and immediately acknowledged into the parent, including eviction on the final command response. The acknowledgement is metadata-only: no browser command, event drain, action retry, or secret transport.
- Parent buffer remains capped at 4000. Gap/detach bookkeeping is restricted to held sessions and retired on confirmed close/replacement, not keyed by arbitrary traffic forever. This is the existing event-count bound, not a new byte-size limit.
- Owned detach is retained outside the evictable event list; requests/idle checking/vault validation still fail closed if the detach event itself was evicted. Confirmed-close delayed detach remains harmless; failed close retains ownership.
- Exact vault borrowing keeps the reader lock, held session, callback restore, no event drain, no new peer/worker, secret-silent transport, native hash guard and no-replay policy.

## Evidence

All relative paths below are under `$HOME/.hermes/plugins/original-chrome-default/`.

- `EVENT-OVERFLOW-RED.json`: exact real-browser red. 55.15s inter-call idle; buffer 4000, overflow true, observer alive. Same-session JS printed title/ready/1733 successes/zero failed fetches/count 1, then page_info failed with `event_buffer_overflow: observation incomplete`, uncertain false. Fresh named session failed with the same error and empty stdout. Comparator preserved, disposable process residue empty.
- `EVENT-OVERFLOW-FINAL.json`: final source green, 55.15s idle, buffer still 4000, overflow still true, same observer object across named sessions. Same-session JS + wait_for_load + page_info succeed; fresh named session new_tab + wait_for_load + page_info + network-idle succeed. Old-session drain explicitly fails, subsequent metadata succeeds, real alert observed and explicitly answered. Owned cleanup succeeds, comparator preserved, residue empty. `EVENT-OVERFLOW-GREEN.json` records an earlier matching successful run.
- `evidence-overflow-final-suite.txt`: **126 tests, OK**, baseline 117 plus nine overflow tests. RED receipts: `evidence-overflow-red-unit.txt` (exact helper error), `evidence-overflow-red-detach.txt` (evicted detach missed), `evidence-overflow-red-worker.txt` (final worker eviction lost), `evidence-overflow-red-vault-detach.txt` (detach evicted during vault validation). Other new tests characterize attribution, caller isolation, dialog snapshots, bounded state/fresh epoch, exact borrowing.
- `evidence-overflow-live-vault-burst-fixed.txt`: real Network traffic overflows before synthetic native password fill; exact held target filled, same-origin comparator empty, no second peer/worker, no secret in result, callback preserved, next worker sees/answers alert; cleanup and residue checks pass. No real credentials used. Initial optional vault-burst fixture had a malformed data URL and failed before vault; corrected fixture-only URL, retained failed receipt as `evidence-overflow-live-vault-burst.txt`.
- `evidence-overflow-live-vault.txt`: ordinary synthetic vault regression passes.
- `evidence-overflow-live-dialog.txt`: real beforeunload cancel/accept pass; two explicit navigations equal two actual sends, cleanup succeeds, residue empty.
- `evidence-overflow-live-popup.txt`: real popup/plain/load/write and prompt paths pass; opener retained, original action counter one, comparator preserved, residue empty.
- `evidence-overflow-registration.txt`: isolated actual plugin-manager load/schema/unload/restore checks pass. This does not reload the live parent.
- `git diff --check`: exit 0.

## Files and preservation

Pre-edit source/test/report/result snapshot: `snapshot-overflow-20261019-054605/`. Prior uncommitted changes preserved. `plugin.py`, `vault_adapter.py`, `consent.py`, and `plugin.yaml` verified byte-identical to that snapshot. No core/config/other-profile/skill changes. Personal tabs, cookies, storage and Chrome lifecycle untouched.

Scoped existing-file diff: `evidence-overflow-scoped.diff`. New tests: `tests/test_event_overflow.py`, `tests/live_event_overflow.py`. Existing fixture changes: `tests/test_observer.py` (explicit mock bookkeeping), `tests/test_idle_observer.py` (explicit owned session for now-scoped event delivery), `tests/live_observer_vault.py` (opt-in real overflow precondition). Existing popup/beforeunload result JSON refreshed by their scripts; originals preserved in snapshot. Reports/receipts use `EVENT-OVERFLOW-*` and `evidence-overflow-*`.

Final production SHA256:
- binding.py: `542b71b6a9140cd7ddad1882ba74d60010d19ae065cea441eb628cfab6ae82e6`
- worker.py: `97a1bceba71ee8bc3b7229dc574f0eedb877c029e8107b5d55e3d72a1b0240d0`
- observer.py: `b15f87c22764aa3af9726d5eb0d9e6fc4223b9ce5e0ada7200b2f4a181d4560c`

## Reproduction commands

Working directory is the plugin directory above. Interpreter:
`PY=$HERMES_PYTHON`

```sh
PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" tests/live_event_overflow.py UNIQUE_LABEL
OVERFLOW_VAULT=1 PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" tests/live_observer_vault.py
PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" tests/live_pending_dialog.py
PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" tests/live_popup_integration.py
PYTHONPATH="$HOME/.hermes/hermes-agent" "$PY" tests/registration.py
```

The overflow script refuses to overwrite its labeled receipt and uses a wholly disposable browser root. Do not run old baseline against personal Chrome.

## Activation and remaining acceptance

Official docs consulted: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins (startup/restart plugin loading). No documented safe in-place observer reload established. Source repair is ready for **owner-controlled Hermes-runtime-only activation**; keep personal Chrome running. A fresh named session in the old runtime does not reload its observer class. Do not hot-mix new workers with an old in-memory observer for acceptance.

After activation, parent must verify through actual native browser_exec: new harmless owned page + wait_for_load/page_info; install the bounded synthetic fetch probe; return from tool and wait beyond 52s; same-session read + wait_for_load/page_info; then a fresh named session navigation + wait_for_load/page_info. Verify expected explicit old-session history refusal separately without replaying preceding actions. The final disposable fixture proves this source path, **not** live native-chat acceptance. Never replay the previous failed compound script just because its error was observation-related: its preceding JS/navigation may already have executed. Preserve old uncertain/lost sessions and personal targets; no broad cleanup.

Limits: event history predating attachment or already lost cannot be reconstructed; damaged attachment history APIs intentionally remain unavailable. Fresh epochs promise only their stated observation window. Buffer remains event-count-bounded, and this is not a general throughput guarantee for unbounded traffic. the private test site/video task remains stopped and unverified. Real login state, personal-profile consent interaction and final native activation are not claimed tested here.
