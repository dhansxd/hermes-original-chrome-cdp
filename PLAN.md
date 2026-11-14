# Project scope and verification

## Scope

Provide Original Chrome through Hermes's native BrowserProvider interface and
Browser Automation picker. Use the current macOS user's existing Chrome profiles
through CDP, including their saved website sign-ins.

Each session owns its windows, tabs, and opener-linked popups. Support Chrome
stopped, running without windows, and already in use. Agents and manual browsing
share the original Chrome application while retaining independent tab ownership.

Implementation work belongs in this plugin repository. Keep Hermes core and its
installed native browser helpers under Hermes's own management.

## Current implementation

- Native provider registration, configuration picker, and browser_exec dispatch.
- Explicit existing-profile startup and verified Chrome process/profile identity.
- Exact Accessibility consent and a loopback per-session CDP relay.
- Namespaced native sessions and owned-target routing.
- Plugin-owned input focus verification.
- Finalization, unload admission control, and retryable in-process cleanup.

## Verification baseline

The 0.4.4 baseline passes 114 unit tests and native four-agent Chrome acceptance.
Coverage includes input/click, screenshots, iframe/shadow DOM, popups, existing
sign-in observations, overlapping operations, and peer-preserving cleanup.
Lifecycle transition tests use an isolated Hermes home. Simulated dependency
publication and gateway notifications in those tests are distinct from actual
plugin installation and reload checks.

The tested Hermes source revision is b200f5bc60e31588ba2cb60e288029c4a54ba5fa,
with browser-harness 0.1.13. Recheck compatibility when upgrading Hermes.

## Distribution preparation

Version 0.4.5 adds distribution documentation, licensing, and macOS dependency
markers. A fresh-install test reproduced a universal resolver conflict with
Hermes's Android psutil dependency. Qualifying this macOS plugin's requirements
keeps those constraints local to its supported platform. A manifest regression
test raises the unit-suite total to 115. Runtime implementation files retain the
tested 0.4.4 behavior.

Fresh-home native installation and enablement pass with the qualified requirements.
The newly built dependency environment passes all 115 unit tests and the native
four-agent local-fixture acceptance, including exact cleanup and stock harness
RECORD validation. All test-owned provider sessions close successfully.

- Document installation, permissions, configuration, operation, and lifecycle.
- Include the MIT license and a step-by-step tutorial.
- Keep examples and fixtures independent of personal accounts and local paths.
- Scan the release tree and reachable Git history for secrets and private identity.
- Validate a clean checkout through the native Hermes loader and regression tests.
- Verify the published Git revision against the reviewed revision.

## Known lifecycle behavior

Version 0.4.6 preserves the foreground window when native provider helpers request
CDP activation. Target routing and actions continue through owned attachments.
Cleanup marks each finishing agent while releasing the provider lock around native
I/O. Queued window creation rechecks closure under the shared consent guard, and
closed endpoints reject new clients. New targets retain `newWindow=True` and the
selected original profile.

All 121 unit tests pass. Native four-agent acceptance verifies disjoint Chrome
window IDs in one profile, input/click, screenshots, popups, and exact cleanup.
Real testing covers running Chrome without windows and with an independent manual
fixture window. The foreground fixture stays selected during a native new-window,
typing, screenshot, and bring-to-front sequence. Cold startup received code review.
These live runs began with the user's original Chrome already running.

Version 0.4.7 records the task-local route for each admitted native browser name.
A dedicated Stop callback matches Hermes's `session_key` payload and closes only
its snapshot of owned names. Creation of finalized native names is rejected.
Hermes's existing turn identity separates replacement names from delayed calls.
The README describes the English and Indonesian debugging-dialog matching.

All 126 unit tests pass. The native four-agent test now sends the actual Stop
payload, verifies exact cleanup and peer/manual preservation, rejects late native
creation, and confirms a replacement turn can browse with an independent name.

Hermes manages plugin activation and browser selection separately. Select Local
in its browser picker before disabling or removing this provider. Apply the
supported plugin reload when the active Hermes surface requires it.

Cleanup recovery records live in process memory. A process that ends before
cleanup succeeds can leave an owned tab behind. Shared-profile website storage
follows Chrome's normal profile-wide behavior.
