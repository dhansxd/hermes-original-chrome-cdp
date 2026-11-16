# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# Retained native CDP idle-timeout repair

## Outcome and scope

Implemented and verified in fresh processes against the installed plugin source. **Not activated or verified in the running native-chat runtime.** No Hermes core/config/other profile was edited, no gateway/runtime reload or restart was performed, and personal Chrome/the private test site/login/storage were not touched. Only disposable empty-root Chrome instances were launched and closed. Existing resilience changes were preserved.

Pre-edit snapshot: `snapshot-timeout-20261019-025037/`. The task-only diff is `evidence-timeout-scoped.diff` (compare this, not the aggregate git diff containing prior accepted work).

## Reproduced cause

Installed `websockets==15.0.1` sync connections have a background receive thread, **but** its bounded frame queue pauses socket reads at the high-water mark (default 16). The retained plugin observer only called recv/pump during tools. On event-heavy pages, an inter-tool idle interval therefore filled that queue, stopped reading pong frames, and eventually closed the connection with:

`observer_lost: sent 1011 (internal error) keepalive ping timeout; no close frame received; no reconnect or action replay`

This is reproduced both by a real loopback WebSocket (80 event frames, accelerated heartbeat, 0.8s idle) and by real disposable Chrome using the normal heartbeat (local fetch every 30ms, **45 seconds without a tool call**). All three retained baseline Chrome runs failed at that exact boundary; repaired runs passed. This is not an increase to timeout values, disabled keepalive, disabled queue bounds, or an action retry.

The historical `Page.navigate` and `Runtime.runIfWaitingForDebugger` timeouts and the private test site blank rendering are **not individually reproduced or conclusively attributed**. New named sessions succeeded after loss in the baseline as well as the repaired fixture, so the stale-competing-owner hypothesis must not be reported as established. An external new page's actual script beacon executed even on the baseline; URL/title alone was not used as rendering proof. Personal the private test site acceptance remains with the parent after activation.

## Minimal production changes

- `observer.py`: one daemon idle drain per retained observer, on its existing consent-checked WebSocket. A reentrant lock serializes idle pumping, regular requests, and the complete vault borrow. Existing event/dialog/popup handling and bounded event buffers are reused. A detected held-session detach fails closed and releases that connection's auto-attach ownership while idle; the next action cannot be sent first. Background observation errors close rather than reconnect/replay. Close signals the drain to stop and joins boundedly; existing worker-timeout close can still interrupt the socket without waiting for the request lock.
- `plugin.py`: normal explicit browser finish uses the serialized observer request rather than reading the same socket directly in competition with the idle pump. All pre-existing browser-close authority/deferral rules are unchanged.

No production modifications to `worker.py`, `binding.py`, `consent.py`, `vault_adapter.py`, vendor helpers, manifest, or account/consent guards in this task. Existing worker subprocess and pipe boundaries remain.

## RED → GREEN and real verification

Interpreter:
`$HERMES_PYTHON`

Run from this plugin with `PYTHONPATH=$HOME/.hermes/hermes-agent`.

- Baseline: `-m unittest discover -s tests -q` → **112 tests, OK** (`evidence-timeout-baseline-suite.txt`).
- RED `test_idle_observer.py`: exact 1011 keepalive failure, converted to an assertion failure (`evidence-timeout-red-idle.txt`). Initial green: `evidence-timeout-green-idle.txt`.
- RED finish serialization: assertion `browser_close_error: AssertionError` from deliberately rejected direct socket access (`evidence-timeout-red-finish.txt`).
- RED idle detach release: `lost held session retained browser-wide autoattach while idle` (`evidence-timeout-red-detach.txt`).
- Final: `-m unittest discover -s tests -v` → **115 tests in 3.774s, OK** (`evidence-timeout-final-suite.txt`).
- `tests/registration.py` → **exit 0**, real isolated namespaced registration (`evidence-timeout-registration.txt`).
- `git diff --check` → **exit 0**, no output.

Real-Chrome regression:
`tests/live_idle_timeout.py green-script` → **exit 0**. `TIMEOUT-IDLE-GREEN-SCRIPT.json`: 45.20s idle read succeeded; document title and action counter verified; injected socket loss refused the old session; two fresh named sessions each navigated and read their fixture; independent exact-target counter stayed **1**; scoped cleanup succeeded; external comparator survived; exact-root process residue **[]**.

Baseline for the same script:
`TIMEOUT_SOURCE_ROOT=$PWD/snapshot-timeout-20261019-025037 ... tests/live_idle_timeout.py red-script` → **exit 1**, exact keepalive failure; `TIMEOUT-IDLE-RED-SCRIPT.json`. Earlier red/green receipts retained independently as `TIMEOUT-IDLE-{RED,GREEN}*.json` and `evidence-timeout-*-live.txt`.

Existing disposable-Chrome fixtures rerun after the production changes:

| Script | Result and retained evidence |
|---|---|
| `live_observer_integration.py` | exit 0; cross-call alert/confirm/prompt, target refusal, loss refusal, cleanup; `evidence-timeout-final-live_observer_integration.txt` |
| `live_popup_integration.py` | exit 0; URL/load/document-write popup cases, original execution counter and opener; `evidence-timeout-final-live_popup_integration.txt` |
| `live_pending_dialog.py` | exit 0; beforeunload explicit cancel/accept without action replay; `evidence-timeout-final-live_pending_dialog.txt` |
| `live_helpers.py` | exit 0; helper parity, input/AX/screenshot/events/recording; `evidence-timeout-final-live_helpers.txt` |
| `live_repair.py` | exit 0; bounded-worker timeouts/ownership/control cleanup; `evidence-timeout-final-live_repair.txt` |
| `live_browser_finish.py` | exit 0; two-session deferral/final exit/reopen synthetic persistence; `evidence-timeout-final-live_browser_finish.txt` |
| `live_observer_vault.py` | **three consecutive exit 0** after fixture serialization adjustment; `evidence-timeout-final-vault-{1,2,3}.txt` |

Each final fixture reported empty disposable process residue. Vault verification used only a synthetic in-memory password/backend: selected exact target filled, same-origin comparator empty, no extra peer/worker for secrets, callback preserved, next worker could observe/dismiss an alert. Real credentials/OTP/payment remain untested.

## Test changes and encountered issues

New: `tests/test_idle_observer.py`, `tests/live_idle_timeout.py`.

Updated:
- `tests/test_vault_adapter.py`: construct the real observer with patched Wire instead of bypassing initialization with `__new__`; old fixture omitted the new lock/stop members and initially caused ten test failures, not ten production vault failures.
- `tests/test_browser_finish.py`: expect serialized request instead of raw wire call.
- `tests/live_observer_vault.py`: fixture-only comparator/verification calls now acquire the same observer lock. The earlier fixture read the live raw socket concurrently with the new idle drain and failed once; original failure receipt is retained (`evidence-timeout-final-live_observer_vault.txt`). Three subsequent runs passed. Production vault already borrows under the lock.

Existing root result JSON files were refreshed by their existing live scripts. All new receipts use `evidence-timeout-*`, `TIMEOUT-IDLE-*`, this report, and the scoped diff. Snapshot preserves relevant pre-edit source/tests; prior resilience logs remain unchanged.

## Activation recommendation (parent/owner only)

The changed observer and provider classes are loaded in the **parent runtime**, not only in new bounded workers. Editing disk or choosing a new named browser session does **not** replace already-imported classes or release that runtime's old observer sockets. **An owner-controlled restart of the Hermes runtime hosting this plugin is required for assured activation** (or an explicitly supported owner-controlled unload/reload that demonstrably disposes all old observer references). Do not restart Chrome. No restart/reload was performed here.

Before any activation, preserve the real the private test site tab/login and do not blindly run `finish_browser()` on an uncertain old session: it may be refused, and existing finish policy can close the browser when eligible. Parent should choose the safe runtime-only activation boundary, leaving Chrome and its profile running. Runtime disconnect releases old debugger ownership without clearing cookies/storage.

After activation, parent must use native `browser_exec` on the intended chat surface: harmless navigate/read, a genuine event-producing 45s inter-call idle, second read of the same target, and a second named session. Inspect real the private test site read-only without login replay if authorized. Source/registry fixtures are not proof the current chat loaded the repair. Do not mark the entire blank-page/navigation incident resolved until this acceptance is complete.

## Reusable diagnostic lesson

A synchronous WebSocket's background receive thread does not guarantee keepalive liveness when its bounded application queue applies backpressure. Reproduce with event traffic during a real inter-call idle longer than ping interval + timeout, not only sleeps within a command loop. Serialize every reader, including vault and explicit finish, and preserve no-replay semantics after loss. This lesson is recorded here rather than editing global skills, because this delegation restricts writes to the plugin and local evidence.
