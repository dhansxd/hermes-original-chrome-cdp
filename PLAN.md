# Original Chrome provider

## Agreed scope, 2026-11-09

Replace the browser backend, keeping Hermes's native browser_exec and browser helpers.
Register Original Chrome in the official Browser Automation picker. Use the original
Chrome profile via CDP, without copying cookies, credentials or profile directories.
Support stopped Chrome, running Chrome without windows, and already-open Chrome.
Parallel agents own their windows/tabs; cleanup preserves other agents and manual work.
Production must retain one original Chrome application process and one Dock icon.
Do not edit Hermes core or implement a new browsing language, vault or site-specific rules.

## Implementation

1. Retain tested macOS GUI launch and CDP consent.
2. Replace custom tools/interpreter with a standard BrowserProvider.
3. Expose per-session CDP: filter target discovery, create owned windows, forward page commands.
4. Namespace native named sessions by agent identity through the supported pre-tool hook.
5. Remove obsolete custom execution, recovery, vault and Flow-specific components/tests.

## Acceptance

- Official plugin loading, provider picker and native browser_exec dispatch.
- Existing login through the original profile, without copying profile/cookies.
- Same-alias independent sessions, overlapping page work, isolated cleanup.
- Native DOM, keyboard, click, screenshot, iframe/shadow DOM, popups.
- Three startup states, separating real-profile from disposable-fixture evidence.
- Failure does not switch to packaged Chromium or close the shared browser.
- Review/test/secret scan; commit/push and verify remote SHA.
- Official install/reload and verification of native tools.

The native fill_input helper has a focus bug. The 0.4.2 correction belongs to the
plugin: its existing pre_tool_call hook loads a per-call focus check before calling
the unchanged native helper. No site-packages edits or agent workspace files are
required. Validate with an unmodified native package and again after official update.

## Candidate verification

- 89 unit tests pass, including failed-start cleanup and disconnected-process evidence.
- Native Hermes browser_exec: DOM/input/click, screenshot, shadow DOM, cross-origin
  iframe, popup, login, same-alias parallel work and exact agent cleanup pass.
- A 3-second page operation overlaps a peer response in 396 ms.
- Original profile: windowless parallel startup preserves the same Chrome PID;
  one Chrome application process remains after cleanup.
- Empty-profile approval mode: stopped, windowless, existing-window and background
  startup pass. The original personal browser was not quit for these fixtures.
- One HTTP 403 from Chrome during earlier acceptance remains unexplained. Later
  passes do not prove it fixed. Failed cleanup is now reported accurately and an
  existing approved peer can close the exact failed-start seed.

## Stabilization follow-up

- Reproduce the Chrome rejection with consent diagnostics; do not retry unknown outcomes.
- Reproduce native fill_input focus failure and use a supported native correction.
- Test four parallel native calls with distinct real tool_call_id values.
- Restore Gemini compatibility with the current provider: its old adapter imports
  private 0.3.4 modules removed in 0.4.0. Keep generation/parsing behavior unchanged.
- Verify original-profile startup, shared use and one Dock icon; close Chrome only
  when there are no user/peer tabs or other active browser connections.
- Commit/push, official update/reload, and verify active Hermes tools after changes.

## Stabilization evidence, 0.4.1

- 90 provider unit tests pass. HTTP rejection diagnostics record only the status
  and a fixed category. The historical 403 was not reproduced; its cause remains
  unconfirmed. No retry or broader Chrome permission flag was added.
- Native Hermes browser_exec passes with four independent same-alias agents.
  Three peer reads finish while one agent awaits a 3-second page operation;
  cleanup of one agent preserves the others. DOM, input/click, screenshot,
  iframe/shadow DOM, popup ownership and existing login pass.
- The actual patched native fill_input passes visible, hidden, disabled and
  read-only input cases without overwriting a previously focused field.
- Original personal Chrome passes fully stopped, running with no windows,
  explicit other-profile startup, and return to the default profile. The cold
  test first verified zero other pages and zero other CDP connections.
- Browser agents, the actual Flow API and Gemini adapter coexist on the same
  original profile with an independently controlled simulated manual tab.
  Closing one browser agent preserves Flow's document, Gemini and the manual
  fixture. Owned cleanup succeeds. No content generation was performed.
- A real CDP resource operation taking 32 seconds succeeds through the relay,
  including Gemini's existing late-response handling. Cleanup is confirmed.
- Gemini's complete offline suite passes: 587 passed, 40 opt-in tests skipped.
  Its companion compatibility commit is preserved as a patch under fixes/,
  because the local Gemini checkout has no Git remote.

## Plugin-owned input correction, 0.4.2

Remove the manual dependency patch. The existing official pre-tool hook loads the
plugin's focus check for each native call; successful input uses the original helper.
Leading Python docstrings/future imports remain valid, and repeated hooks do not stack
checks. Other providers are unaffected and no agent workspace file is written.

97 unit tests and native four-agent acceptance pass for the candidate. Deployment
acceptance must additionally verify the stock package against its RECORD hashes,
run native input/parallel/cleanup checks after the official updater creates its new
environment, and confirm the active gateway has loaded 0.4.2. Retire only the two
known manual helper edits from 0.4.1. Keep the historical HTTP 403 limitation open.

## CDP consent correction, 0.4.3

Scope is CDP consent and failed-start cleanup. Two regression cases reproduced the
global mouse-state dependency before correction. Consent now waits for stable Chrome
geometry and validates the exact dialog/socket before AXPress, independently of global
mouse-button state. Existing handshake deadlines remain bounded.

A unique startup-tab title allows failed-start cleanup through its retained native tab
close button when no CDP ownership has been discovered. Process identity, document URL,
tab ancestry and final absence are checked. The close is scoped to the startup tab,
including when another tab shares its window. Unknown closure remains unconfirmed.

Candidate evidence includes 107 provider unit tests, native four-agent browser_exec
acceptance with input/click/screenshot/iframe/popup/login and independent cleanup,
587 Gemini tests with 40 opt-in skips, and 906 Flow tests. A real Chrome connection
completed in approximately 2.3 seconds with the legacy mouse-state reader simulated
as continuously held; the corrected path did not consult that reader. Physical
held-mouse interaction is not established by this simulation. Failed-start native
tab cleanup was exercised while an independently created tab remained open.

Publication, official update/reload and installed coexistence checks follow candidate
verification. Gemini reuses this plugin's CDP session module. Flow retains its own
consent module and requires its own HTTP verification.

## Deployment and real-agent acceptance, 2026-11-09

The official update installed 0.4.2 into a fresh Python environment. All 14 native
browser-harness source hashes match the package RECORD after live tests, and both
earlier manual helper edits were restored. The active gateway loads 0.4.2.

Two actual Hermes model conversations completed through the active gateway, using
only native browser_exec: one read the signed-in Flow projects dashboard; the
other read the signed-in Gemini editor and held its page until the first agent's
cleanup completed. All five tool calls succeeded. Independent CDP observations
confirmed distinct windows in the same original profile, the surviving peer
document, and unchanged pre-existing pages and an operator-created manual fixture.
Both agent sessions and the observer/manual fixtures cleaned up successfully.
One Chrome application process and one Dock icon remain. No content was generated.
The manual fixture does not claim a human typing test. The earlier HTTP 403 did not
recur in this run; its original cause remains unconfirmed.
