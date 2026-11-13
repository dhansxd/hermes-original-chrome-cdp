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

- Document installation, permissions, configuration, operation, and lifecycle.
- Include the MIT license and a step-by-step tutorial.
- Keep examples and fixtures independent of personal accounts and local paths.
- Scan the release tree and reachable Git history for secrets and private identity.
- Validate a clean checkout through the native Hermes loader and regression tests.
- Verify the published Git revision against the reviewed revision.

## Known lifecycle behavior

Hermes manages plugin activation and browser selection separately. Select Local
in its browser picker before disabling or removing this provider. Apply the
supported plugin reload when the active Hermes surface requires it.

Cleanup recovery records live in process memory. A process that ends before
cleanup succeeds can leave an owned tab behind. Shared-profile website storage
follows Chrome's normal profile-wide behavior.
