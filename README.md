# Original Chrome for Hermes

A browser provider for Hermes's native `browser_exec`. Select **Original Chrome · CDP**
in `hermes tools → Browser Automation`.

Hermes uses the installed Google Chrome and an existing profile, including its current
website logins. The plugin does not copy cookies or profiles, launch packaged Chromium,
replace browser tools, implement a scripting language, or provide a separate vault.

## Requirements

- macOS with a logged-in desktop and Google Chrome.
- Remote debugging enabled in `chrome://inspect/#remote-debugging`.
- Accessibility granted to the process running Hermes, for Chrome's debugging consent.
- A Hermes build supporting browser providers and `pre_tool_call` argument modification.
- Native Browser Automation and Terminal toolsets enabled (Hermes requires Terminal for
  its native Python browser tool).

## Install and select

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-default-plugin
hermes plugins enable original-chrome-default
hermes tools
```

Choose **Original Chrome · CDP** in Browser Automation. The provider is registered through
`register_browser_provider` and `get_setup_schema`, like other browser providers.

For this local provider, use:

```yaml
browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  use_real_profile: false
```

Hermes currently classifies provider plugins as cloud backends. Disable its private-URL
sidecar so it cannot send localhost work to a separate Chromium. If localhost access is
needed, use Hermes's normal private-URL permission setting. Clear an existing
`browser.cdp_url`, `BROWSER_CDP_URL`, or `BU_CDP_*` override before using this provider.

The plugin setting `profile_directory` defaults to `Default`; it may name another existing
Chrome profile directory, such as `Profile 2`. It takes effect for newly created sessions.
The profile is selected explicitly and verified using Chrome's profile-path page.

### Migration from 0.3.x

Enable the native browser toolsets again: remove `browser` and `browser-use` from
`agent.disabled_toolsets`, and enable Browser Automation on the intended surfaces.
Remove the old `original_chrome` toolset selection. Existing conversations must refresh
their tool definitions after the supported plugin reload.

Use `browser_exec` and native `browser_vault`, not `browser_original_chrome_exec` or
`browser_original_chrome_vault`. The old account-binding setting is no longer required;
there is no hardcoded account identity. Core Hermes and its installed Python packages
are not patched. The input focus check is owned and loaded by this plugin.

## Session ownership

Chrome can be stopped, running without windows, or already in use. Each browser session
opens its own window in the selected original profile. New targets also open in owned
windows; opener-linked popups belong to that session. Native named sessions are namespaced
by Hermes task identity, including when different agents use the same name.
All production sessions use the same original Chrome application process and Dock icon.
Chrome's own debugging-consent dialog can briefly activate Chrome during connection;
normal page work does not require activating a window.

A small local CDP endpoint presents only the session's targets to the native driver.
DOM, Runtime, Input, screenshots and frame commands are forwarded. Cross-session target
access, quitting the whole browser, and browser-wide operations that would change peers
are refused. This is cooperative session ownership, not a sandbox for native Python,
arbitrary website code, or other tools on the machine.

Cookies and site storage remain shared normally within a Chrome profile. Signing out
of a website has the same profile-wide effect as signing out manually.

Hermes's normal browser lifecycle closes the provider session; the provider closes only
its owned tabs and its CDP connection. It never quits shared Chrome. Startup errors stay
on the selected CDP route instead of falling back to a different browser.
If startup fails after opening its seed tab, cleanup is only confirmed after that exact
tab is gone. An existing approved connection can remove it; an unavailable connection
is reported as incomplete cleanup, without reopening Chrome or retrying permission.

## Verification

Unit tests retain the existing consent/connection tests and cover native registration,
agent namespaces, startup identity, target ownership, parallel CDP responses and cleanup.
Run them with the Hermes Python environment:

```sh
hermes --run-module unittest discover -s tests -p 'test_*.py'
```

Live acceptance is separate: actual native registry dispatch, real Chrome with an existing
login, parallel agents, ordinary input/click, screenshot, nested DOM, popup ownership, and
peer-preserving cleanup. Cold/windowless startup can be tested with an empty temporary
Chrome profile without closing the user's original browser.

During the 0.4.0 acceptance run, one original-profile handshake returned HTTP 403.
It did not recur in the subsequent native, original-profile windowless/parallel, or
empty-profile approval-mode startup tests. Its cause is not confirmed; these passing
tests do not establish that Chrome can never reject a connection.

Version 0.4.1 records the HTTP status and a fixed rejection category on failed handshakes;
it never logs an arbitrary response body or retries the handshake automatically. Forwarded
page commands use the caller's deadline rather than an extra 30-second transport deadline.

The native browser-harness 0.1.13 `fill_input` helper has a focus-check defect: a hidden or
disabled target can leave typing in a previously focused field. Version 0.4.2 uses the
plugin's existing `pre_tool_call` hook to load `input_guard.py` into each native
`browser_exec` call. It verifies editability and actual focus, then calls the original
native helper for typing. The runner, tools and vault remain native. The check does not
edit Hermes packages or the agent's workspace helpers, and applies only when this
provider is selected. Reinstalling dependencies needs no manual input patch.

Run `tests/live_native.py --check-native-focus --require-unmodified-harness` with Hermes's
Python to verify both the input behavior and the installed package's recorded file hashes.
This replaces the temporary site-packages correction used in 0.4.1. Ordinary plugin/API
compatibility still needs verification when upgrading Hermes.
