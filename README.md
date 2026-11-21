# Original Chrome for Hermes

The [active product contract](PLAN.md#kontrak-browser-dan-ekstensi) calls for one
Hermes browser tool with site controls built into the same browsing task.
The `browser_app` and `browser_exec` examples below describe the current implementation.
Read [AGENTS.md](AGENTS.md) and the active plan before changing the integration.

Use your installed, signed-in Google Chrome as the browser backend for Hermes Agent.
Choose **Original Chrome · CDP** in Hermes's Browser Automation picker, then use the
native `browser_exec` tool and browser helpers.

The [project handoff](HANDOFF.md) records the verified baseline and recovery
steps for a fresh Mac installation. The active plan records current open work.

The plugin connects through Chrome DevTools Protocol (CDP). Each agent session gets
its own Chrome window and owned tabs in the selected existing profile. Saved website
sign-ins come from that Chrome profile. Separate agents can work alongside manual
browsing in the same Chrome application.

Use `chrome_profiles` to list current profiles, choose a profile for an agent's
named browser session, or change the default for new sessions. Several agents can
choose the same profile or different profiles, each with their own windows.

Use `browser_app` to discover and run user-owned website extension packages.
Their Python code and guides live outside the plugin installation and can be
updated independently. Version 0.10.3 bundles Flow 0.3.0 with real-account rolling,
portable reference files and destination character/voice preparation. Classic and
Agent rolling both produced original MP4 files, with the Agent test run by Hermes.
Provider quota-reset acceptance and the Gemini package follow the open checklist in
[PLAN.md](PLAN.md).

On first package discovery, bundled site packages are copied to `browser-apps/`
in the active Hermes profile, or the configured `apps_directory`. The default
profile uses `~/.hermes/browser-apps`. Existing user
packages and persistent disable/remove choices are preserved during host updates.
The installed copy is editable independently of this plugin. Read its current
operations and guide with `browser_app` action `describe`, app `flow`.

Flow uses native UI actions in the extension's owned Chrome window. Settings and
progress are read through targeted DOM queries. Downloads use Chrome's original
download action and a page-bound download GUID. Collected files include SHA-256
and decoded metadata. Install FFmpeg and ffprobe on the Hermes process PATH for
these media checks. Credit fields report the balance displayed in that page.
Concurrent activity in another window can make a displayed balance stale.

Agent settings expose model, aspect and output-count defaults. The package also
includes these choices in the Agent instruction. Duration and resolution on the
inspected Agent UI are prompt requests. Classic uses the numeric controls exposed
by the chosen model. The package guide describes the current acceptance scope.

## Requirements

| Component | Requirement |
| --- | --- |
| Operating system | macOS with an active, logged-in graphical desktop |
| Browser | Google Chrome installed at `/Applications/Google Chrome.app` |
| Chrome profile | An existing profile belonging to the current macOS user |
| Debugging | Chrome's remote-debugging setting enabled |
| macOS permissions | Accessibility access for the application running Hermes |
| Hermes | BrowserProvider support, the Browser Automation picker, and `pre_tool_call` argument modification |
| Toolsets | Native Browser Automation and Terminal enabled for the intended Hermes surface |

The plugin declares `psutil>=5.9,<8` and `websockets>=15,<17` for macOS. Hermes
manages these Python dependencies during installation and enablement. The platform
markers keep its universal dependency resolver from applying this plugin's package
ranges to Hermes's Android or other operating-system environments.

Version 0.10.3 uses documented public Hermes plugin APIs for BrowserProvider,
configuration, session-route context, and CDP supervisor teardown. A regression
check rejects private Hermes runtime imports. The plugin owns its Chrome startup,
consent, CDP relay, targets, and cleanup. Hermes manages its native browser driver
and session cache. [Hermes public plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api)

The compatibility baseline is Hermes commit
`b200f5bc60e31588ba2cb60e288029c4a54ba5fa` and `browser-harness` 0.1.13 on macOS.
Run the tests below when upgrading Hermes or Chrome. Startup and consent use macOS
APIs. Native Stop route handling and late-session rejection remain covered.

## Install

Prepare Chrome once using the profile you want Hermes to use.

1. In Google Chrome, open `chrome://inspect/#remote-debugging`.
2. Under **Remote debugging**, check **Allow remote debugging for this browser
   instance**.
3. In macOS **System Settings → Privacy & Security → Accessibility**, allow the
   application that launches Hermes. For example, this can be Terminal, your IDE,
   or the Hermes application, depending on how Hermes runs.

Chrome remembers the checkbox after you quit and reopen it. Leave it checked so
Hermes can start Chrome on the next browser request. The plugin handles Chrome's
separate connection dialog during startup. See the
[detailed Chrome setup](docs/TUTORIAL.md#enable-chrome-remote-debugging-once).

Install and enable the plugin through Hermes.

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-cdp
hermes plugins enable original-chrome-default
hermes tools
```

Review the source and dependency prompts that Hermes displays. In Browser Automation,
select **Original Chrome · CDP**. Enable the native Browser Automation and Terminal
toolsets on the surface where you will use the agent.

Hermes separates plugin installation, activation, and browser selection. Its plugin
manager handles these operations through the normal plugin commands. [Hermes plugin guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)

## Configure

Merge the following settings into the active Hermes profile's `config.yaml`. The
normal default location is `~/.hermes/config.yaml`. Preserve your existing
configuration sections when editing it.

```yaml
browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  use_real_profile: false

plugins:
  entries:
    original-chrome-default:
      settings:
        profile_directory: Default
```

The enable command manages `plugins.enabled`. The provider reads the default
`profile_directory` from its own plugin settings. `Default`, `Profile 1`, and
`Profile 2` are examples of Chrome directory IDs. `chrome_profiles` reads their
current IDs and display names from Chrome metadata. The final component of
**Profile Path** in `chrome://version` also identifies the directory.

| Setting | Purpose |
| --- | --- |
| `browser.cloud_provider` | Selects this registered browser provider |
| `browser.auto_local_for_private_urls: false` | Keeps Hermes's private-URL sidecar from choosing another browser backend |
| `browser.use_real_profile: false` | Leaves profile attachment to this provider |
| `plugins.entries.original-chrome-default.settings.profile_directory` | Default existing Chrome profile for new sessions |
| `plugins.entries.original-chrome-default.settings.apps_directory` | External package root, defaulting to `browser-apps/` in the active Hermes profile |

Clear competing `browser.cdp_url`, `BROWSER_CDP_URL`, `BU_CDP_URL`, and `BU_CDP_WS`
overrides when selecting this provider. Hermes's normal private-URL permissions
continue to govern localhost and private-network navigation.

After changing settings, apply Hermes's reload or restart action for the affected
process if it reports one. The selected profile takes effect for new browser sessions.

## Select profiles per agent

The plugin provides `chrome_profiles` alongside native `browser_exec`. Its tool
schema supplies profile guidance directly to the agent. These are example tool
arguments.

```json
{"action": "list"}
```

Choose a directory ID from the returned list and select it for a named session.

```json
{"action": "select", "profile": "Profile 2", "session": "research"}
```

Use the same session alias in `browser_exec`.

```json
{"session": "research", "code": "# Opening a page in the selected profile\nnew_tab('https://example.com')\nprint(page_info())"}
```

Each agent has its own session namespace and windows, including when agents use
the same alias and the same profile. An agent can use several named sessions with
different profiles. Selection uses the original Chrome profile directly.

For a shared profile, set the saved default for new agent sessions, or have each
agent select the same returned profile ID. For different profiles, give each agent
its intended ID and have it select that profile for its own named session.

To switch an existing named session, call `select` again with the destination
profile. The plugin closes that session's previous owned browser resources and
assigns a fresh native connection name. Its next `browser_exec` opens the selected
profile. Repeating the current selection reuses its connection. The calling task's
normal finalization releases the selection together with its browser resources.

To persist a default for future sessions, use the following arguments.

```json
{"action": "set_default", "profile": "Default"}
```

Each active session uses its own selected profile. A fresh named session uses the
current default when it first browses. Explicit selection takes precedence for
that session. Default changes use Hermes's public plugin settings writer.

Profile creation and removal are handled by Chrome's profile management. The
plugin refreshes inventory for each list and selection, reflecting additions,
removals and display-name changes. A removed or replaced profile produces a
selection diagnostic so the caller can choose an available profile from the fresh
inventory.

Saving a `fixed` rule binds it to the current profile directory. If Chrome
replaces that directory, select the intended profile and save the rule again.
Older rules still use their saved directory ID. Re-save them to bind the
directory identity. Changes that switch an active browser session are saved
after cleanup succeeds. Changes deferred by an in-progress site operation
report that they apply to future browsing.

## User-owned website extensions

The plugin registers the [site-controls skill](skills/site-controls/SKILL.md) as
`original-chrome-default:site-controls`. It points Hermes to mapped browser
actions when the request names a site such as Gemini Web or Google Flow.

The Gemini Web package provides mapped actions for opening a conversation,
entering a prompt, selecting a tool or model, sending, and reading the result.
Use the package's named session for related actions. If a control needs inspection,
pass the session returned by `browser_app` to native `browser_exec` to use the
same window. See the [Gemini package guide](site_apps/gemini/SKILL.md).

The `browser_app` tool accepts `list`, `describe`, `run`, `enable`, `disable`,
`remove`, and `record_missing_control`. Package discovery and
help read files without executing package code or opening Chrome. An operation
uses an app-specific browser session bound to the calling agent and conversation.
Different apps and ordinary browsing have separate windows, including when their
agents share the same Chrome profile.

```json
{"action": "list"}
{"action": "describe", "app": "my-site"}
{"action": "run", "app": "my-site", "operation": "inspect", "session": "work", "params": {}}
```

Create packages in `browser-apps/<id>/` within the active Hermes profile, or
configure `apps_directory`.
The package contains `app.json`, `app.py`, and an optional `SKILL.md`. The ID must
match its directory and use letters, numbers, underscores, or hyphens. The first
character is a letter or number. `describe` supplies operation parameter schemas
and the current guide to the agent. Package code receives the supplied parameter
object and validates the operation's required values.

Use the same alias for related calls. Pass the returned private `session` to
native `browser_exec` for DOM inspection, screenshots or other unmapped UI
actions in the same Chrome window. If the package reports pending work, that
session can also be used on the next turn in the same conversation. The package
decides when navigation is necessary. The host loads
the current source on each call and preserves the loaded module during an active
operation. Relative imports such as `from .helpers import inspect_page` use the
package's own namespace and current source. Files beside `app.py` can be located
using `Path(__file__).parent`.

After using DOM or screenshot fallback for a confirmed unmapped control, Hermes
records the page or mode and the control in `missing-controls.jsonl` under that
package's `data_directory`. This uses the same app and exact session with
`browser_app` action `record_missing_control`.

Packages execute trusted local Python code with the permissions of the Hermes
process. The bound browser context is valid during `run`. Its browser helpers use
the native dispatch and the plugin's target ownership and input checks.

Pass `app` to `chrome_profiles` to select or configure a website package's profile.
Its choices are independent of ordinary browsing and other packages.

```json
{"action": "select", "app": "my-site", "profile": "Profile 2", "session": "work"}
{"action": "set_rule", "app": "my-site", "scope": "session", "mode": "fixed", "profile": "Profile 2", "session": "work"}
{"action": "set_rule", "app": "my-site", "scope": "default", "mode": "random"}
```

Use `set_rule` for persistent `fixed`, `default`, or `random` policy and
`clear_rule` to restore inherited policy. Resolution follows session/agent,
subagent role, platform, parent, and service default. `random` chooses once for
an active session from current Chrome inventory. `default` uses the legacy
`profile_directory`. Session rules persist for the conversation and alias.
Agent rules address the current Hermes task ID. Platform rules target a channel
such as `whatsapp` or `telegram`. Subagent rules target a public role name or `*`.
Parent choices come from the public `subagent_start` hook. Each service has its
own policy namespace. Defaults affect new sessions, while an explicit current
selection uses the existing owned-session switching path.

`list` returns `selected_profile`, the resolved `rule`/`rule_source`, and the
`default_rule`. A random default reports `default_profile` as null and its active
choice through `selected_profile`.

Packages declaring `profile_policy: rotate_on_limit` can use generic account
rolling. Their UI callbacks identify the service account, supply quota evidence,
prepare destination references and reconcile source requests. Host jobs preserve
the source profile and provider receipt across interruption. `describe` lists
recoverable jobs, and `run` accepts a returned `job` ID. The current account is
remembered for the conversation/alias until exhaustion. See the
[rolling contract](docs/ROLLING.md) for callbacks, evidence and recovery.

An app returning `running` or `needs_inspection` retains its owned session across
turns in that Hermes process. Call the same app and alias to continue observing.
The source profile remains attached to that pending result. A newly saved policy
is reported as deferred when a result is pending. `context.checkpoint(value)`
atomically saves the package's known work position. Package result envelopes
are saved as `result.json` beside its artifacts. Stop, finalization, disable and
unload release the owned browser resources.

```json
{"action": "disable", "app": "my-site"}
{"action": "enable", "app": "my-site"}
{"action": "remove", "app": "my-site"}
```

Disable persists availability and releases that package's sessions owned by the
serving Hermes process. Every bound browser call checks availability. Other
Hermes processes observe the saved flag on their next call. An in-flight command
in another process follows that process's own lifecycle. `cleanup_pending` means
an active invocation or unconfirmed cleanup remains. Retry the action after it
settles. Re-enabling starts a fresh owned session. Remove deletes the source
folder after cleanup, preserving checkpoints and artifacts under plugin data.
For a linked package, removal unlinks its package entry.

See the [extension package tutorial](docs/TUTORIAL.md#create-a-website-extension)
for a complete example and the context/result contract.

## First use

Ask Hermes to perform a small browsing task.

> Open https://example.com with browser_exec and report the page title.

Chrome may show its debugging-consent dialog. The plugin verifies the dialog and
connection identity, waits for stable geometry, and uses an Accessibility `AXPress`
to approve that exact dialog. Normal website interaction uses CDP.
Automatic dialog matching currently recognizes English and Indonesian Chrome
debugging dialogs. Compatibility with other Chrome UI languages needs verification.

To verify an existing website login, ask Hermes to open a site you already use in
the selected profile and report whether the expected signed-in interface is visible.
Keep any page content or screenshots produced during that check local.

The [step-by-step tutorial](docs/TUTORIAL.md) covers installation checks, profile
changes, parallel sessions, updates, and switching back to the built-in browser.

## How sessions work

1. Hermes calls this plugin's registered `BrowserProvider` through its native tool.
2. The provider exposes a loopback-only CDP relay for that session.
3. On first use, it opens a uniquely identified startup tab directly in the requested
   original Chrome profile and verifies the resulting Chrome process and profile path.
4. The relay presents that session's owned tabs and opener-linked popups to the driver.
5. Provider-instance, task, conversation, and turn identities namespace native named
   sessions, so agents can independently use the same session alias. Replacement
   turns and reloaded providers receive new names. Pending extension operations
   reuse their owned session when continued in the same conversation.
6. Session-finalization hooks close owned targets, their CDP supervisor, and the
   relay. Hermes manages its native driver processes and session cache through
   its own lifecycle. Other agents and pre-existing manual pages retain ownership.

Startup covers Chrome stopped, running without windows, and running with existing
windows. Production sessions use the original Chrome application and its Dock entry.
The explicit profile-directory launch selects the requested profile directly.

Each session opens one initial window. After consent and profile verification,
the relay hands that same blank page to the native driver's first bootstrap
request. The handoff is consumed once. Later target requests create additional
owned windows according to the existing session ownership rules.

For running Chrome, the plugin forwards explicit profile/window arguments through
Chrome's local ProcessSingleton socket after checking the connected process ID,
process creation time, and IPC nonce. Cold startup uses normal macOS LaunchServices.
The original application owns the agent windows and uses its existing Dock entry.
Subsequent browsing uses CDP. The startup message follows Chromium's implementation.
[Chromium ProcessSingleton source](https://github.com/chromium/chromium/blob/main/chrome/browser/process_singleton_posix.cc)

Chrome can reject creation through a persistent profile's context ID after another
profile becomes last-used. On that specific pre-creation refusal, the relay uses
the same verified singleton to open an owned window in the explicitly selected
profile, then resumes CDP operations. The session's unique startup page identifies
the new window and retains it for cleanup if creation is interrupted.
[Chromium browser-context resolution](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/browser/devtools/devtools_browser_context_manager.cc)

Authentication comes from each user's local Chrome profile. The installation
configuration consists of the browser backend and an existing profile-directory
name. Profile paths are resolved from the macOS user's home directory at runtime.

Shared-profile cookies and website storage follow Chrome's normal behavior. Signing
out, changing account settings, or modifying shared website data can affect every
user of that same profile. Tab ownership governs the plugin's target routing. Native
`browser_exec` runs Python with the permissions of the Hermes process, so agents
should receive the same trust you would give an operator of that signed-in browser.

The relay refuses browser-wide shutdown, browser-wide cookie/cache clearing, and
operations targeting another session's windows. It forwards native DOM, JavaScript,
input, screenshots, iframe, and shadow-DOM operations for owned targets.
CDP window-activation requests are acknowledged while Chrome keeps its current
foreground window. Native helpers select and operate on their owned CDP targets
in the background. New targets use separate agent-owned windows in the selected
profile.

For keyboard events, the relay omits a mirrored native keycode when the helper
copies the Windows keycode into the macOS-native field. DOM key/code, modifiers,
text and editor commands retain their values. Explicit distinct native keycodes
are forwarded. This avoids Cocoa menu fallback for that malformed encoding.
[Chromium keyboard dispatch](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/browser/devtools/protocol/input_handler.cc)

## Update and lifecycle

```sh
hermes plugins update original-chrome-default
hermes plugins list
```

Apply any activation or dependency-environment action reported by your Hermes build.

To switch to Hermes's built-in browser, run `hermes tools` and select **Local** in
Browser Automation before disabling or removing this provider.

```sh
hermes plugins disable original-chrome-default
```

To enable it again, use the following command and select **Original Chrome · CDP**
in the browser picker.

```sh
hermes plugins enable original-chrome-default
hermes tools
```

To uninstall it, select Local first, then run the native removal command.

```sh
hermes plugins remove original-chrome-default
```

In the tested Hermes build, CLI disable requests a gateway plugin reload. Dashboard
disable reports a reload requirement, and removal deletes the installed files while
the running process still needs a plugin reload. Apply the supported reload action
on that Hermes surface. Ordinary reload preserves the selected browser setting.
Hermes-managed plugin data can survive removal.

Unload closes admission before collecting sessions for cleanup. A late native call
to a retired provider receives a failing CDP endpoint, which keeps it on the CDP
error path. Failed cleanup retains exact session ownership for another attempt and
an in-process exit callback. That recovery state lasts for the lifetime of the
Hermes process. If the process ends before cleanup succeeds, owned tabs may remain.

Hermes Stop events identify their route through `session_key`. The provider records
that task-local route during each browser call and closes the matching browser names
when Stop arrives. Finalized native names lose admission, and replacement turns use
different names to keep delayed calls scoped to their original turn.

For ordinary browsing, a disconnected Chrome session first reports the interruption
and retires its exact native name once cleanup is confirmed. A subsequent
`browser_exec` call can open a new window in the selected profile. Check the
site state after an interrupted click or submission before issuing it again.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Provider absent from the picker | Confirm macOS, the Chrome application path, plugin enablement, and Hermes BrowserProvider compatibility |
| Accessibility error | Grant access to the application that actually runs Hermes and apply the process restart macOS requests |
| Remote-debugging error | [Check the Remote debugging checkbox](docs/TUTORIAL.md#enable-chrome-remote-debugging-once) in your installed Chrome, then retry in Hermes |
| Selected profile missing | Create or open that profile in Chrome, then verify its directory in `chrome://version` |
| Browser/profile override conflict | Review the competing CDP override settings listed above |
| Private URL rejected | Review Hermes's normal private-URL permission setting for the intended destination |
| Plugin configured after removal | Select Local in the native Browser Automation picker and apply the reported reload |
| Cleanup unconfirmed | Inspect the identified session before retrying cleanup, preserving other agents' and manual tabs |
| Chrome disconnected while browsing | Wait for the previous session to be retired, then call `browser_exec` again to open a new window |

Chrome or an operating-system permission can reject a connection. Report a failing
case with plugin, Hermes, Chrome, and macOS versions, the startup state, and a
redacted error. Keep credentials, browser data, page contents, and unredacted logs
out of issue reports.

## Development and verification

From a checkout of this repository, use the Hermes Python environment.

```sh
hermes plugins validate .
hermes --run-module unittest discover -s tests -p 'test_*.py'
```

The 0.10.3 regression suite covers registration, task
namespaces, startup and consent identity, input focus, target ownership, transport
responses, concurrent unload, retryable cleanup, and dependency platform markers.
Regression cases also cover foreground preservation, late window creation during
cleanup, late client admission, and independent agent hooks during slow cleanup.
Lifecycle regressions use native Stop payloads and cover peer preservation, late
session rejection, replacement turns admitted during cleanup, and provider reload.
The runtime import check restricts Hermes imports to the documented public APIs
used here.

Profile regressions also cover fresh discovery, additions/removals/renames,
directory replacement, default changes with active agents, independent named
sessions, repeated selection, round-trip switches, native JSON results and
Stop arriving during a profile switch.
Policy regressions cover service isolation, persistent session rules, default and
random selection, scope precedence, parent/child inheritance, channel rules,
separate Hermes configurations, malformed saved rules, and profile replacement.
Package lifecycle cases cover active-code cancellation, retryable cleanup,
checkpoint/receipt preservation, fresh sessions after re-enable, linked and broken
package removal, and peer access during slow source deletion.

Startup regressions cover warm-process forwarding, cold LaunchServices arguments,
connected-peer identity, IPC nonce replacement, long socket paths, fragmented
acknowledgements, early peer closure, and failed-start seed cleanup. Post-close
Accessibility verification observes transient macOS reads within its existing
deadline after the single close action.

For real Chrome acceptance, run this command with the Python environment used by Hermes.

```sh
python tests/live_native.py --check-native-focus --require-unmodified-harness
python tests/live_profiles.py
python tests/live_apps.py
python tests/live_rolling.py
python tests/live_parallel.py
```

The multi-profile native test requires two existing Chrome profiles. It uses local
fixture pages and an isolated Hermes home for its temporary default settings.

This test opens local fixture pages through four native agents, checks distinct
Chrome window IDs, parallel responses, input/click, screenshots, iframe/shadow DOM,
popups, native Stop during an in-flight request, late-session rejection, provider
reload within the same turn, and peer-preserving cleanup.
It creates and closes its own test targets. Saved-login verification uses
the separate first-use check above. Native package hash checking verifies the
installed harness against its package RECORD.

The browser and rolling suites also compare the native macOS Chrome window
inventory before and after teardown. Accessibility reads observe that inventory
without activating Chrome. An extra native window fails cleanup acceptance.

The parallel suite uses six distinct native Hermes task/conversation identities
and one shared site package on local fixture pages. It exercises a shared profile
and two mixed profiles, concurrent input, individual Stop/completion, peer/manual
preservation and native window cleanup. It requires one initial window per session
and six added native windows for six owners. Additional targets read back their
actual profile directory after both profiles are active. The browser and parallel
suites also check macOS logs for unexpected About This Mac events from Chrome.

The site-package native test uses external temporary packages, two apps, parent
and child identities, a simulated Telegram route, and ordinary browsing. It checks
six separate windows on one profile, repeated calls without navigation, package
and operation discovery, source updates in two agents, targeted native inspection,
and cleanup that preserves peers and existing manual targets. These are native
tool/route tests. Receiving real Telegram or WhatsApp messages is a separate
channel acceptance step.

The source files `plugin.py`, `relay.py`, `startup.py`, `consent.py`, `cdp_peers.py`,
and `input_guard.py` implement provider registration, transport, startup, consent,
Chrome peer identity, and the plugin-owned input focus check. BrowserProvider
registration follows Hermes's provider interface. [Hermes public plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api)

## License

MIT, copyright 2026 dhansxd. The complete terms are in [LICENSE](LICENSE).
Hermes, Chrome, and Python dependencies retain their respective licenses.
