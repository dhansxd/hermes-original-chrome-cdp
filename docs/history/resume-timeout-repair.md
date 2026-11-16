# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# First-call resume timeout: production-route repair

## Outcome

**Reproduced the exact reported first-call error on the actual personal Default profile using the installed provider in a fresh standalone process, then the same production route passed after a minimal observer-only repair.** This is not merely empty-profile success. The already-running chat runtime has NOT been reloaded/restarted or accepted after this edit; that boundary remains for the parent/owner.

Original native report (parent supplied, unchanged): session `timeout-repair-native`, first `new_tab('https://example.com');wait_for_load();print(page_info());print(js(...))`, no stdout, `observer_lost: CDP_response_timeout: Runtime.runIfWaitingForDebugger; no reconnect or action replay` after owner restart.

No Hermes core/config/profile changes, personal Chrome restart/close, cookie/storage manipulation, login replay, historical target adoption, or timeout increases. The prior idle keepalive repair and all earlier uncommitted work remain. The only production file changed by this repair is `observer.py`.

## Exact cause and evidence

`RESUME-PRODUCTION-baseline.json` records the fresh installed-source run with normal account validation, GUI-selected owned seed, consent transport, actual Profile Path verification, bounded Python worker and retained observer. It fails with the **identical** error and empty stdout. Instrumentation records method names, opaque target identifiers, target types, URL schemes and `waitingForDebugger`, never personal URLs/titles/documents or command arguments.

On first verified request, `Target.setAutoAttach` synchronously emits existing-page attachments. `_attached` previously sent `Runtime.runIfWaitingForDebugger` to every unrelated page even when Chrome explicitly said `waitingForDebugger=false`. A nonresponsive unrelated renderer therefore blocked global setup before user code. Reentrant callbacks nested several resume requests; the innermost failing target in this trace is `REDACTED_TARGET_ID`, type `page`, URL kind `https`, **waitingForDebugger=false**, not provider-owned. Exceptions in outer commands are propagation of that failure, not proof all those targets independently timed out.

Baseline trace has one `Target.setAutoAttach` and **zero `Target.createTarget`** calls: the requested `new_tab` user code had not run. This is distinct from a timeout while navigating an already-created requested destination and distinct from the earlier idle keepalive queue starvation. A fresh process loading hashed current source reproduced it, so stale runtime code is not required to explain this failure. We did not inspect the parent runtime's live Python object graph; process timing alone cannot prove its loaded class version.

A frozen/discarded renderer remains a possible reason the unnecessary command did not answer, **not an established lifecycle diagnosis**. No personal page was evaluated or frozen/discarded to investigate. The minimal test injects an unresponsive nonwaiting renderer at the socket boundary; the stronger live baseline is the actual profile failure itself.

## Minimal change

In the non-owned attachment branch only:

```python
if params.get('waitingForDebugger'):
    self.wire('Runtime.runIfWaitingForDebugger',{},sid)
self.wire('Target.detachFromTarget',{'sessionId':sid})
```

Thus an existing nonwaiting unrelated target is detached without requiring its renderer to answer. A genuinely paused unrelated new target is still resumed before detach. Owned opener-linked children still get Page/Network armed before resume. Ownership, exact vault, no-replay, transport-loss handling, worker bounds and teardown remain unchanged.

## RED / GREEN / regression receipts

- `evidence-resume-red.txt`: new real observer + real Wire reentrant setup test fails with the exact observer_lost / Runtime.runIfWaitingForDebugger error before the edit. Simulated nonresponsive socket is explicitly a unit fixture, not live renderer evidence. Waiting=true counterpart passes as baseline characterization.
- `evidence-resume-green-suite.txt`: **117 tests, 3.765s, OK**. Prior baseline was 115; two new tests cover nonwaiting unresponsive setup and waiting unrelated resume-before-detach. Existing nonwaiting expectation was corrected in `tests/test_observer.py`.
- `RESUME-PRODUCTION-green.json`: same installed production route on actual personal Default succeeds. First call prints `Example Domain`, URL `https://example.com/`, `ready=complete`; second call reads the same owned page successfully. Exactly one `Target.createTarget` occurs. No failed commands. The exact previously failing unrelated target is present again with waiting=false; it is not sent Runtime resume. An owned setup target still receives its existing resume command, so this is not a blanket suppression.
- `RESUME-CLEANUP-READBACK.json`: independent consent-checked **Target.getTargets-only** readback verifies both successful diagnostic owned pages absent, all baseline page IDs still present, and failed diagnostic seed preserved. Cleanup used `close_session`, not `finish_browser`; no personal `Browser.close` was sent.
- `evidence-resume-live_popup_integration.txt`: exit 0; real disposable GUI plain, URL-load and document-write popup comparisons; early dialogs answered explicitly; opener retained; action counter one; comparator preserved; empty fixture process residue.
- `evidence-resume-live_pending_dialog.txt`: exit 0; explicit beforeunload cancel and accept, two explicit navigations/two sends, cleanup, empty disposable residue.
- `evidence-resume-live_observer_vault.txt`: exit 0; synthetic password exact-target native fill, same-origin comparator empty, no second peer/worker for vault, callback retained, next worker sees/dismisses alert, cleanup preserves comparator, empty disposable residue. Real credentials untouched.
- `git diff --check`: exit 0.

## Blank first window is a separate behavior

Parent source inspection confirms `worker.initialize` navigates the owned GUI seed through `chrome://version` to verify the actual Profile Path, then to `about:blank`. `new_tab` subsequently creates another owned window, initially blank, and navigates that destination. The unused initial seed may therefore remain blank intentionally even on a successful request. A permanently blank first setup window alone is **not** evidence the requested page failed or this timeout recurred. In the reproduced baseline setup failed before the destination's Target.createTarget, so only the seed existed for this diagnostic. No cleanup redesign was made in response to this observation.

## Files and preservation

Base directory: `$HOME/.hermes/plugins/original-chrome-default/`.

- Modified production: `observer.py` (one conditional plus comment).
- Modified test: `tests/test_observer.py` (nonwaiting expectation).
- Added tests/probes: `tests/test_resume_setup.py`, `tests/live_resume_production.py`, `tests/verify_resume_cleanup.py`.
- Scoped diff: `evidence-resume-scoped.diff`; compare against `snapshot-resume-20261018-2235/`, NOT aggregate git diff containing older accepted changes.
- Pre-edit snapshot includes observer/worker/plugin/existing observer test and prior popup/beforeunload result JSON before reruns. `worker.py` and `plugin.py` byte equality against this snapshot verified. Earlier `snapshot-timeout-20261019-025037`, TIMEOUT report and idle receipts untouched.
- Existing popup and beforeunload JSON result files were refreshed by their existing scripts; prior versions preserved in new snapshot.
- Failed diagnostic seed remains intentionally preserved because the failed session was marked uncertain; its exact ID/provenance is retained in baseline receipt. Do not broadly close blank or ambiguous tabs. Green diagnostic targets were positively owned and cleaned/read back.

## Activation and remaining acceptance

Authoritative current docs consulted: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins . They describe startup/restart activation for in-process plugins; no documented safe live reload for this provider was established. The parent holds the observer class in memory: starting another named session does not reload this edited class. No runtime reload/unload/restart was invoked here.

There is now direct real-profile red/green evidence addressing the exact remaining native boundary, so an owner-controlled **Hermes-runtime-only** activation is justified, followed by parent's native browser_exec first navigate/read and second same-session read. Keep personal Chrome running; no Chrome restart is needed. Do not retry the uncertain old native action/session. Native chat acceptance after activation remains explicitly unverified. Real the private test site rendering and live authentication were not inspected and are not claimed fixed or verified; all baseline page targets remained present.

Reproduction interpreter: `$HERMES_PYTHON`, `PYTHONPATH=$HOME/.hermes/hermes-agent`. Probes refuse overwriting their labeled receipt. No recommendation to repeatedly run real-profile baseline is made.

## Reusable lesson (plugin-local, scope preserved)

When browser-wide auto-attach reports an existing unrelated target with waitingForDebugger=false, detach it without sending a renderer resume command. Browser-wide setup must not depend on an unrelated nonwaiting renderer answering. Capture the exact nested command target and waiting flag before attributing a setup timeout; propagate no-replay loss, preserve original evidence, and distinguish real-profile provider acceptance from active native-chat acceptance. This lesson is recorded locally rather than modifying profile skills outside the plugin-only scope.
