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

The installed native fill_input helper also has the focus bug found in the old
vendored helper. Backend replacement must not be reported as fixing that dependency.

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
