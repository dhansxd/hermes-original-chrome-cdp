# Arsip laporan diagnosis historis

Laporan ini berasal dari fase arsitektur lama plugin pada Oktober 2026.
Baseline aktif, spesifikasi dan status lanjut tersedia di
[HANDOFF.md](../../HANDOFF.md) dan [PLAN.md](../../PLAN.md).
Nama file source serta perintah di laporan mengikuti desain pada waktu itu.
Path pribadi, lokasi interpreter khusus mesin, URL proyek pribadi dan ID
target pribadi telah disunting. Isi laporan lainnya dipertahankan.
File evidence dan snapshot yang dirujuk merupakan bukti lokal historis.

---

# Browser plugin resilience repair — installed source evidence

## Outcome

Implemented personally in this plugin only. No Hermes core, production config, other-profile files, runtime/gateway lifecycle, publication or installation command changed. Existing uncommitted unified-vault repair files were preserved. Manifest version remains 0.1.8 (local refactor, not a published release).

- Registration isolates native vault module/registration failures. It always installs a vault guard, so missing compatibility never leaves selected-provider page writes on native browser-wide target selection. Unknown future actions also refuse. List/unlock use the registered native handler, or their native non-page entry points if unified registration alone is missing. If native code itself cannot import, those native capabilities are explicitly unavailable.
- Worker no longer imports/clones live `browser_harness.helpers` internals. It executes the reviewed plugin-owned snapshot in a fresh namespace, preserving helper algorithms, names and injected scoped transport. Existing tab/observer/finish boundaries are unchanged. Custom workspace helpers still load per execution. Screenshot/debug paths and explicit recording controls use that execution workspace and transport. Automatic recording was not wired into the previous worker and was not added.
- No vault hash weakened: `vault_adapter.py` was not modified by this refactor. The reviewed native source SHA256 still equals `ea1ac6458b5cf542a203c51168ae6fb4c6e9c7b1eae3854cc28852d57b0fc651`. Its internal algorithm namespace cloning remains a guarded maintenance boundary, not update-proof code.

## Public API decision

Read official https://hermes-agent.nousresearch.com/docs/developer-guide/browser-supervisor and installed `tools/browser_supervisor.py` (capture delegation), `tools/browser_supervisor_capture.py` (full implementation), and `tools/browser_vault_tool.py` transport/dispatch paths. Host revision inspected: `22063fc099ec9ad8357d7f8f6e6248a0400680d3`.

`SUPERVISOR_REGISTRY.capture(task_id)` pins an already-running supervisor's socket and default attached page; it never starts or imports the plugin's held observer. Native vault still calls `_ensure_supervisor`, `_eval_js`, and `_focus_bound_origin` (same-origin form focus), with no public transport argument. Capture therefore does not remove the native-algorithm coupling or make that native focus exact-target. Migrating to a second supervisor would change sole-peer consent, selected target and dialog ownership. No such substitution or private registry injection was made. The existing adapter remains necessary within this bounded refactor; a public native-vault exact-target transport seam would allow removing it later.

## Real execution

Interpreter used (the README's older environment no longer exists):
`$HERMES_PYTHON`

Run from this plugin with `PYTHONPATH=$HOME/.hermes/hermes-agent`:

- Baseline `-m unittest discover -s tests -v`: **Ran 107 tests in 2.099s — OK** (`evidence-resilience-baseline.txt`).
- RED real namespaced loader: missing native registration rolled back plugin: `AssertionError: False is not true : native vault tool registration missing: browser_vault`.
- RED helpers: simulated upstream module removal caused `AssertionError: simulated harness update removed internal module`.
- RED list/unlock preservation: missing unified registration returned `vault_compatibility_unavailable` instead of native synthetic passthrough.
- Review caught a preflight namespace regression when `BH_DOMAIN_SKILLS=1`: added RED (`AGENT_WORKSPACE` undefined), then initialize it explicitly to None and skip domain lookup only during internal profile preflight. User execution still gets its real workspace. Helper live test reran with `BH_DOMAIN_SKILLS=1`, exit 0.
- Final full suite: **Ran 112 tests in 2.155s — OK** (`evidence-resilience-green-suite.txt`). Additional import/adapter fault cases were first-run-green characterizations of the implemented boundary.
- `tests/registration.py`: **exit 0**; real namespaced PluginManager load/unload, provider namespace, exact native schemas, native list/unlock passthrough, missing-bound-target page refusal, picker and unload restoration. Receipt: `RESILIENCE-REGISTRATION-RESULT.json`.
- `git diff --check`: **exit 0**, no output.

Seven real disposable-Chrome scripts exited **0** and independently reported empty fixture process residue:

| Script | Exercised result | Evidence |
|---|---|---|
| `tests/live_helpers.py` | Navigation/JS decoding, DOM input/key/click/scroll, upload selection, AX, PNG screenshot, events/network idle, local HTTP, scoped tab controls, start/stop JPEG recording, custom helper reload, finish | `RESILIENCE-HELPERS-RESULT.json`, `evidence-resilience-live-helpers.txt` |
| `tests/live_observer_vault.py` | Native synthetic password fill only on selected held target; same-origin comparator empty; no second peer/worker secret path; next-worker alert; exact cleanup | `evidence-resilience-live_observer_vault.txt` |
| `tests/live_observer_integration.py` | Cross-call alert/confirm/prompt with one execution; wrong-target refusal; new-tab arming; external close; observer-loss refusal; retain/cancel/finalize/unload | `OBSERVER-INTEGRATION-RESULT.json`, matching evidence log |
| `tests/live_popup_integration.py` | Five popup cases including initial URL prompt and immediate document.write prompt, opener preserved, parent counter 1, comparator preserved | `POPUP-INTEGRATION-RESULT.json`, matching evidence log |
| `tests/live_pending_dialog.py` | beforeunload cancel and accept, two explicit navigations and two actual sends, normal finish exit | `PENDING-DIALOG-RESULT.json`, matching evidence log |
| `tests/live_browser_finish.py` | Other-session deferral, final exit, same-root GUI reopen with synthetic cookie/storage preserved | `BROWSER-FINISH-RESULT.json`, matching evidence log |
| `tests/live_repair.py` | First/later worker timeout without replay, new-tab/popup cleanup, preflight pending-seed cleanup, control preservation, real delayed network idle | `REPAIR-GUI-RESULT.json`, matching evidence log |

These scripts exercised the updated installed files in fresh Python processes with local disposable roots, not the running native chat handler. No real credential backend, external site action, masked Telegram prompt, real OTP/payment, personal cold launch or new personal consent prompt was exercised. Existing account/GUI/consent fixture regressions remain in the passing unit suite. Same-profile storage is shared; arbitrary Python is not sandboxed. Existing unsupported cross-origin iframe target adoption is unchanged.

## Exact files changed in this task

All paths below are relative to `$HOME/.hermes/plugins/original-chrome-default/`:

Modified existing files:
- `plugin.py`
- `worker.py`
- `tests/registration.py`
- `tests/test_worker.py`
- `README.md`

New source/tests/provenance:
- `vault_schema.json` (last-known native schema only for missing-registration safe guard)
- `vendor/helpers.py`
- `vendor/LICENSE.browser-harness`
- `vendor/PROVENANCE.md`
- `tests/test_resilience.py`
- `tests/live_helpers.py`

New evidence:
- `RESILIENCE-RESULT.md`
- `RESILIENCE-REGISTRATION-RESULT.json`
- `RESILIENCE-HELPERS-RESULT.json`
- `BROWSER-FINISH-RESULT.json`
- `OBSERVER-INTEGRATION-RESULT.json`
- `PENDING-DIALOG-RESULT.json`
- `POPUP-INTEGRATION-RESULT.json`
- `REPAIR-GUI-RESULT.json`
- `evidence-resilience-baseline.txt`
- `evidence-resilience-red-registration.txt`
- `evidence-resilience-red-passthrough.txt`
- `evidence-resilience-red-helpers.txt`
- `evidence-resilience-red-workspace.txt`
- `evidence-resilience-green-registration.txt`
- `evidence-resilience-green-suite.txt`
- `evidence-resilience-live-helpers.txt`
- `evidence-resilience-live_observer_vault.txt`
- `evidence-resilience-live_observer_integration.txt`
- `evidence-resilience-live_popup_integration.txt`
- `evidence-resilience-live_pending_dialog.txt`
- `evidence-resilience-live_browser_finish.txt`
- `evidence-resilience-live_repair.txt`

Python generated/updated plugin-local `__pycache__` and `tests/__pycache__` entries during execution. Pre-existing working-tree edits in `plugin.yaml`, `vault_adapter.py`, `tests/test_vault_adapter.py`, `tests/live_observer_vault.py`, and `VAULT-API-REPAIR.md` are not this refactor's changes.

## Activation handoff

No runtime or gateway restart performed. Existing worker launches read updated disk source, but an already-loaded plugin registration closure may remain old. Fresh-process namespaced registration is verified; current-chat activation is not claimed. Parent owns native `browser_exec` open/read/repeated read/finish acceptance and the project plan. If the active process needs reload/restart, leave it owner-controlled. The older unified-vault native recovery was reported verified before this task; stale historical README sections do not negate that prior result.

## Parent native-chat verification

Native `browser_exec` session `resilience-acceptance` successfully opened https://example.com, returned Example Domain, then read the same page in a second call. `page_info.__code__.co_filename` confirmed the actual helper source was this plugin's `vendor/helpers.py`. Both calls used `original-chrome-default` with `fallback_used:false`. Explicit finish returned `success:true`, `remaining_owned_targets:[]`, `unresolved_creation:false`, `browser_closed:true`.

Parent independently inspected the diff, registration/helper receipts and final unit log. Core `git status --short --untracked-files=no` returned empty. Native helper activation is verified; the current process's registration closure is not introspected, so the new vault-load isolation still needs owner-controlled restart for assured activation. No restart performed.

## Maintenance procedure

Keep helper updates explicit: compare the installed upstream algorithms against this snapshot, preserve local ownership/transport overrides, retain upstream license/provenance, then rerun helper smoke plus affected dialog/vault/lifecycle fixtures. Do not remove the vault source pin until the private algorithm dependency is removed or reviewed against a tested replacement. Always exercise directory loading through PluginManager's namespaced path, not only top-level script imports. Keep fault injection and synthetic vault fixtures isolated from real credentials.
