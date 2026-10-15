# Original Chrome Default adapter — partial implementation

Source only; **not installed or production-ready**. No Hermes/core/harness modifications, production config/grants, profile copy, cookies, personal Chrome launch, broker or background runtime.

## Implemented and exercised

- BrowserProvider identity/setup schema produces a real picker row. Public `register_tool(..., override=True)` replaces `browser_exec`, preserving its native schema. Requires operator `tools.override` consent when installed later.
- Selected provider path executes through a bounded child process with the installed `browser_harness.helpers` functions cloned into a private globals namespace. Does not mutate the imported harness module. No harness daemon is started and no first-personal-tab startup/recovery occurs.
- Cold-launch inside the normal execute path uses `/usr/bin/open -n -a Google Chrome.app`, Default, and the original data root. Requires Aqua, console UID and Security Session graphic-access bit. No direct Chrome binary launch or mock Keychain. Disposable roots alone use debugging-port flags. Stale port-file candidates must survive a real WebSocket handshake before any page action.
- Only one GUI-created unique file-page seed is selected with --profile-directory=Default; no candidate-context search remains. Personal executions require Default metadata to match developer@example.invalid before launch/execution. Only that seed is checked on chrome://version for exact Profile Path, then used for work; missing/mismatched seed refuses. Tested live on an empty Default root, not personal browsing.
- Per-task/named-session target/context/window identity is checked before helper operations. Missing/moved target reports error; never adopts a manual tab. `new_tab` creates a new owned window each time (deliberate bounded subset, not same-window tabs).
- Explicit created targets and new page targets with positive owned `openerId` provenance are tracked. Existing/manual targets are not adopted by window/title/URL. Popup code has unit coverage, not live acceptance.
- `print(finish_browser())` explicitly closes tracked owned targets, returns residuals, supports `retain=[target_id]`. Provider `close_session(task_id)` also releases only recorded targets. Neither quits shared Chrome.
- Timeout quarantines the session and does not replay. If first execution dies before returning ownership state, residual targets cannot be safely recovered; close refuses to adopt them.
- Failure reports `fallback_used:false` and `action_replayed:false`; automatic alternate-backend fallback is intentionally not implemented. Fallback was permitted, not silently invoked.

## Required gaps / blockers

1. **Native vault exact target:** implemented via `vault_adapter.py` with private namespace copies of version-pinned native functions and an exact owned target/document transport; native module globals/core/private supervisor registries stay unchanged. Public tool overrides now route fill/save-login/enter-code through this adapter when selected; list/unlock remain native. 15 synthetic tests and real empty-profile DOM tests show agent-only fill, same-origin manual form preserved, navigation during prompt refused and no secret output. This is version-specific implementation reuse, not a supported public vault transport API. Actual Telegram masked prompts, real backend unlock/login and payments are not accepted yet. Native save may store an original-origin item before a navigation-related fill refusal. See VAULT-RESULT.md and VAULT-LIVE-RESULT.json.
2. **Consent automatic click:** source + 13 fixture tests now cover exact English/Indonesian main/PWA heading/button approval during pending attach. Actual main-Chrome Indonesian consent click and completed handshake are now verified; live 9Router PWA-host consent plus bound agent read/read and exact cleanup are verified (PWA-CONSENT-RESULT.json). Saved profile count is no longer a rejection condition; exact endpoint/host/new-sheet and actual socket correlation still apply. Chrome’s root/-/Web Applications shim layout is recognized without treating it as work-target profile proof. Earlier personal no-sheet timeouts were followed by a reproduced transient AX-read latch and ineffective ctypes press. The exact legacy PID-scoped AppleScript fixed the action path: personal main-Chrome consent+handshake and adapter open/read/read/cleanup now pass. See CONNECTION-SLICE-RESULT.json and PERSONAL-CONSENT-RESULT.json. See CONSENT-RESULT.md.
3. **Lifecycle:** automatic mapped cancel/interruption and session-finalization cleanup now use public hooks (8 tests). Ordinary completed turns preserve browser work because the host supplies no authoritative task-finished signal. Explicit `finish_browser()` remains; automatic normal-task completion and immediate post-teardown failure notification are not guaranteed. No timer/persistence system added. See LIFECYCLE-RESULT.md.
4. Picker provider rows set `browser.cloud_provider` but do not set driver. `browser.backend: browser-use` must already be selected (current production has it, unchanged). Legacy `browser_*` provider `create_session` deliberately refuses to expose a browser-wide endpoint. A menu row is not full legacy-stack support.
5. Native chat/PluginManager install, actual consent, personal Keychain/login safety, original multi-profile mapping and live popup/mixed-window cases are unverified. No universal sandbox: arbitrary Python remains trusted user code, and same-profile windows share login/storage.
6. Deliberately unsupported helper metadata: native dialog/event bookkeeping is not backed by the harness daemon. Pending-dialog and event drain explicitly refuse as unsupported; frame/pop-up discovery is bounded to owned page provenance. Do not infer full harness feature parity.

## Actual verification

Interpreter:
`/Users/example/.hermes/installs/054eb5508814b359/environments/6b64fb5d3e2d40499038afc42859ebf5/venv/bin/python`

From this directory:

```sh
PYTHONPATH=$HOME/.hermes/hermes-agent <python> -m unittest discover -s tests -v
<python> tests/registration.py
<python> tests/live_gui.py
```

- Test-first slice logs: `evidence-red-binding.txt`, `evidence-red-worker.txt`, `evidence-red-adapter.txt`, `evidence-red-popup.txt` are API-absence REDs (not behavioral bug reproductions). `evidence-red-finish.txt` is assertion RED. `evidence-red-timeout.txt` reproduces first-call replay/quarantine defect before repair.
- `evidence-green-final.txt`: final unit suite output.
- `REGISTRATION-RESULT.json`: real isolated PluginContext/picker registration, native schema equality, vault write refusal, no Chrome.
- `LIVE-RESULT.json` and `evidence-live-final.txt`: actual automatic GUI launch from execute, real reused helper open/read, repeated registry read, separate manual-fixture window, missing target refusal, exact owned cleanup, explicit finish cleanup, and no process argv residue for fixture root. Not native chat.
- First live run failed because macOS `/var` and `/private/var` scope paths differed, so dispatch selected the original handler; no website action was run by it (provider missing preflight refused), fixture browser closed and residue was empty. Fixed fixture scope by using a resolved scratch path. First worker test also exposed an incomplete fake interface (`create` missing); fixture corrected. Neither failure is counted as a pass.

Parent owns PLAN.md updates. Installation/publication and personal Chrome acceptance remain separate authorized work.
