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

The native fill_input helper also has the focus bug found in the old vendored
helper. The separate 0.1.13 dependency patch is tracked under fixes/; backend
replacement alone does not fix it, and a dependency rebuild can overwrite it.

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
