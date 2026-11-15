# Original Chrome for Hermes

Use your installed, signed-in Google Chrome as the browser backend for Hermes Agent.
Choose **Original Chrome · CDP** in Hermes's Browser Automation picker, then use the
native `browser_exec` tool and browser helpers.

The plugin connects through Chrome DevTools Protocol (CDP). Each agent session gets
its own Chrome window and owned tabs in the selected existing profile. Saved website
sign-ins come from that Chrome profile. Separate agents can work alongside manual
browsing in the same Chrome application.

Use `chrome_profiles` to list current profiles, choose a profile for an agent's
named browser session, or change the default for new sessions. Several agents can
choose the same profile or different profiles, each with their own windows.

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

Version 0.5.2 uses documented public Hermes plugin APIs for BrowserProvider,
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

1. Open Chrome and visit `chrome://inspect/#remote-debugging`.
2. Enable remote debugging using the controls provided by your Chrome version.
3. In macOS **System Settings → Privacy & Security → Accessibility**, allow the
   application that launches Hermes. For example, this can be Terminal, your IDE,
   or the Hermes application, depending on how Hermes runs.

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
   turns and reloaded providers receive new names.
6. Session-finalization hooks close owned targets, their CDP supervisor, and the
   relay. Hermes manages its native driver processes and session cache through
   its own lifecycle. Other agents and pre-existing manual pages retain ownership.

Startup covers Chrome stopped, running without windows, and running with existing
windows. Production sessions use the original Chrome application and its Dock entry.
The explicit profile-directory launch selects the requested profile directly.

For running Chrome, the plugin forwards explicit profile/window arguments through
Chrome's local ProcessSingleton socket after checking the connected process ID,
process creation time, and IPC nonce. Cold startup uses normal macOS LaunchServices.
The original application owns the agent windows and uses its existing Dock entry.
Subsequent browsing uses CDP. The startup message follows Chromium's implementation.
[Chromium ProcessSingleton source](https://github.com/chromium/chromium/blob/main/chrome/browser/process_singleton_posix.cc)

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

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Provider absent from the picker | Confirm macOS, the Chrome application path, plugin enablement, and Hermes BrowserProvider compatibility |
| Accessibility error | Grant access to the application that actually runs Hermes and apply the process restart macOS requests |
| Remote-debugging error | Check `chrome://inspect/#remote-debugging` in your installed Chrome |
| Selected profile missing | Create or open that profile in Chrome, then verify its directory in `chrome://version` |
| Browser/profile override conflict | Review the competing CDP override settings listed above |
| Private URL rejected | Review Hermes's normal private-URL permission setting for the intended destination |
| Plugin configured after removal | Select Local in the native Browser Automation picker and apply the reported reload |
| Cleanup unconfirmed | Inspect the identified session before retrying cleanup, preserving other agents' and manual tabs |

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

The 0.5.2 regression suite contains 170 unit tests. It covers registration, task
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

Startup regressions cover warm-process forwarding, cold LaunchServices arguments,
connected-peer identity, IPC nonce replacement, long socket paths, fragmented
acknowledgements, early peer closure, and failed-start seed cleanup. Post-close
Accessibility verification observes transient macOS reads within its existing
deadline after the single close action.

For real Chrome acceptance, run this command with the Python environment used by Hermes.

```sh
python tests/live_native.py --check-native-focus --require-unmodified-harness
python tests/live_profiles.py
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

The source files `plugin.py`, `relay.py`, `startup.py`, `consent.py`, `cdp_peers.py`,
and `input_guard.py` implement provider registration, transport, startup, consent,
Chrome peer identity, and the plugin-owned input focus check. BrowserProvider
registration follows Hermes's provider interface. [Hermes public plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api)

## License

MIT, copyright 2026 dhansxd. The complete terms are in [LICENSE](LICENSE).
Hermes, Chrome, and Python dependencies retain their respective licenses.
