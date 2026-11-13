# Original Chrome for Hermes

Use your installed, signed-in Google Chrome as the browser backend for Hermes Agent.
Choose **Original Chrome · CDP** in Hermes's Browser Automation picker, then use the
native `browser_exec` tool and browser helpers.

The plugin connects through Chrome DevTools Protocol (CDP). Each agent session gets
its own Chrome window and owned tabs in the selected existing profile. Saved website
sign-ins come from that Chrome profile. Separate agents can work alongside manual
browsing in the same Chrome application.

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

The plugin declares `psutil>=5.9,<8` and `websockets>=15,<17`. Hermes manages these
Python dependencies during installation and enablement.

Version 0.4.4 was tested against Hermes commit
`b200f5bc60e31588ba2cb60e288029c4a54ba5fa` and `browser-harness` 0.1.13 on macOS.
It also uses Hermes's session-cleanup and harness-directory helpers. Compatibility
with another Hermes revision should be checked with the tests below. Its startup
and consent implementation uses macOS APIs.

Hermes's validator currently warns about private imports used for native session
cleanup, CDP supervisor teardown, browser environment construction, and harness
directory namespacing. These helpers can change between Hermes releases. Native
provider registration and hooks use the plugin interfaces, while the documented
tested revision defines the compatibility baseline for those cleanup helpers.

## Install

Prepare Chrome once using the profile you want Hermes to use.

1. Open Chrome and visit `chrome://inspect/#remote-debugging`.
2. Enable remote debugging using the controls provided by your Chrome version.
3. In macOS **System Settings → Privacy & Security → Accessibility**, allow the
   application that launches Hermes. For example, this can be Terminal, your IDE,
   or the Hermes application, depending on how Hermes runs.

Install and enable the plugin through Hermes.

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-default-plugin
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

The enable command manages `plugins.enabled`. The provider reads `profile_directory`
from its own plugin settings. `Default`, `Profile 1`, and `Profile 2` are examples of
Chrome directory names. Find the actual name in `chrome://version` under **Profile
Path**, then use the final directory component. Chrome's display name for a person
can differ from this directory name.

| Setting | Purpose |
| --- | --- |
| `browser.cloud_provider` | Selects this registered browser provider |
| `browser.auto_local_for_private_urls: false` | Keeps Hermes's private-URL sidecar from choosing another browser backend |
| `browser.use_real_profile: false` | Leaves profile attachment to this provider |
| `plugins.entries.original-chrome-default.settings.profile_directory` | Selects an existing Chrome profile for new sessions |

Clear competing `browser.cdp_url`, `BROWSER_CDP_URL`, `BU_CDP_URL`, and `BU_CDP_WS`
overrides when selecting this provider. Hermes's normal private-URL permissions
continue to govern localhost and private-network navigation.

After changing settings, apply Hermes's reload or restart action for the affected
process if it reports one. The selected profile takes effect for new browser sessions.

## First use

Ask Hermes to perform a small browsing task.

> Open https://example.com with browser_exec and report the page title.

Chrome may show its debugging-consent dialog. The plugin verifies the dialog and
connection identity, waits for stable geometry, and uses an Accessibility `AXPress`
to approve that exact dialog. Normal website interaction uses CDP.

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
5. Task and conversation identities namespace native named sessions, so agents can
   independently use the same session alias.
6. Session-finalization hooks close owned targets, the native session daemon, and
   the relay. Other agents and pre-existing manual pages retain their ownership.

Startup covers Chrome stopped, running without windows, and running with existing
windows. Production sessions use the original Chrome application and its Dock entry.
The explicit profile-directory launch selects the requested profile directly.

Shared-profile cookies and website storage follow Chrome's normal behavior. Signing
out, changing account settings, or modifying shared website data can affect every
user of that same profile. Tab ownership governs the plugin's target routing. Native
`browser_exec` runs Python with the permissions of the Hermes process, so agents
should receive the same trust you would give an operator of that signed-in browser.

The relay refuses browser-wide shutdown, browser-wide cookie/cache clearing, and
operations targeting another session's windows. It forwards native DOM, JavaScript,
input, screenshots, iframe, and shadow-DOM operations for owned targets.

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

The 0.4.4 regression suite contains 114 unit tests. It covers registration, task
namespaces, startup and consent identity, input focus, target ownership, transport
responses, concurrent unload, and retryable cleanup.

For real Chrome acceptance, run this command with the Python environment used by Hermes.

```sh
python tests/live_native.py --check-native-focus --require-unmodified-harness
```

This test opens local fixture pages through four native agents, checks parallel
responses, input/click, screenshots, iframe/shadow DOM, popups, and peer-preserving
cleanup. It creates and closes its own test targets. Saved-login verification uses
the separate first-use check above. Native package hash checking verifies the
installed harness against its package RECORD.

The source files `plugin.py`, `relay.py`, `startup.py`, `consent.py`, `cdp_peers.py`,
and `input_guard.py` implement provider registration, transport, startup, consent,
Chrome peer identity, and the plugin-owned input focus check. BrowserProvider
registration follows Hermes's provider interface. [Hermes public plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api)

## License

MIT, copyright 2026 dhansxd. The complete terms are in [LICENSE](LICENSE).
Hermes, Chrome, and Python dependencies retain their respective licenses.
