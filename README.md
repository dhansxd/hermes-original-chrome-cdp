# Original Chrome Default plugin

Native Hermes `browser_exec` and exact-target `browser_vault` adapter for original headed Chrome on macOS. Current requirements, status and remaining work live only in [PLAN.md](PLAN.md).

## Runtime contract

- Install/enable with Hermes' official plugin manager and the operator's `tools.override` grant. Select `browser.backend=browser-use` and `browser.cloud_provider=original-chrome-default`.
- Set `plugins.entries.original-chrome-default.settings.expected_account` through `hermes config set` to the explicitly approved account; no identity is shipped in source or inferred from a last-used profile. Missing settings refuse before launch. Verify the original Default profile/account binding before work. Attach a current endpoint or cold-launch through the verified macOS GUI destination. Never clone login/cookies or reset profile storage/Keychain.
- One parent-held CDP observer per named session keeps dialog/event continuity; user Python runs in bounded workers. A worker timeout closes only that session transport, never its peers. `vendor/helpers.py` is the reviewed plugin-owned helper snapshot, with license/provenance in `vendor/`.
- Different task/named-session pairs execute independently; one session stays serialized. Root launch/setup and consent/target-close still use their scoped coordination. Cancel fences already-queued actions, and vault borrowing holds only the selected session/transport, not the provider-wide state lock.
- Named sessions own their confirmed targets, including proven opener-linked additions. Lost/unknown ownership does not select the first page or repeat an uncertain action.
- Vault list/unlock remain native; page actions borrow the exact selected held session/document, with version-bound native compatibility. Secrets do not pass through worker pipes or output.

## Shared Chrome with Google Flow API

The only companion project is [google-flow-api](https://github.com/dhansxd/google-flow-api). Owned-root/related observation excludes API targets. `finish_browser()`, cancellation, finalization and unload release this client's targets/transport, never quit shared original Chrome. Explicit finish may report `browser_close_deferred:shared_browser`.

Only consent handshake/cancellation and owned target-close share a root-scoped lock. Settled-peer receipts require a current endpoint/process/socket and independent descriptor pin. Unknown/pending peers remain ambiguous; page reads/actions are not globally serialized.

An uncertain named session still rejects page actions. For explicit recovery, send only `finish_browser()` or `print(finish_browser())` in that same session, optionally with comments. The expression is parsed, never executed as user code, and routes to cleanup for that named session only. A failed close preserves quarantine and reports failure; it does not replay the original action or close another named session.

**Known gap:** an opener-linked popup that opens a JavaScript dialog before Page attachment may time out without the callback. Do not claim this is fixed by related-only observation. Post-attachment dialog/vault and plain-popup evidence is separate. No universal OS-permission, hard-crash, long-run or paid-generation claim.

## Build and acceptance

```sh
hermes --run-module unittest discover -s tests -p 'test_*.py'
# Run tests/registration.py with the same Hermes Python interpreter; it imports hermes_bootstrap.
```

Registration is tested in an isolated real namespaced PluginManager. Browser and HTTP coexistence tests are run separately with a harmless local marker and read-only account operations; no generation is needed. Source-tested, registered-host and chat-native results must be reported distinctly because an already-running gateway can retain older closures. Never restart the owning Hermes runtime to complete activation.

Successful completed builds must be committed and pushed to this GitHub repo, with secret scanning and exact remote SHA verification; see `AGENTS.md`. Keep private reports, runtime, screenshots, live IDs and credentials out of Git.
