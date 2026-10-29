# Original Chrome Default for Hermes

A macOS browser provider that runs Hermes browser work in the installed Google Chrome GUI and its original `Default` profile. Existing logins stay in Chrome. The plugin creates and controls its own windows, and leaves unrelated user windows alone.

This is a personal build: production use is restricted to the account allowlist in `plugin.py`. Configuring a different account does not expand that scope. It does not copy profiles, export cookies, or fall back to a headless or cloud browser.

## Requirements

- macOS with a logged-in Aqua desktop and Google Chrome at `/Applications/Google Chrome.app`.
- Chrome 144 or newer with remote debugging enabled by the operator at `chrome://inspect/#remote-debugging`. Chrome asks permission for new debugging connections.
- Accessibility permission for the process that actually runs Hermes. A successful check in Terminal does not establish permission for a gateway, or vice versa.
- The plugin and its `original_chrome` toolset enabled in the intended Hermes profile. Version 0.3.0 registers `browser_original_chrome_exec` and `browser_original_chrome_vault`; it does not replace native tools or request `tools.override`.
- Browser provider `original-chrome-default` and the expected account configured below. Current Hermes selects the provider through `browser.cloud_provider`; a legacy `browser.backend: browser-use` is accepted, but is not required.
- Both `browser` and `browser-use` listed in `agent.disabled_toolsets`. The plugin refuses browser work if either entry is missing. Its own toolset does not require the `terminal` toolset.

The installed Hermes build is the compatibility reference. Browser and lifecycle integration use registered tools, the browser-provider API, plugin hooks, and the public tool dispatcher. Tool schemas are bundled with this plugin. It does not change Hermes core or import Hermes's internal secret redactor. Compatibility with arbitrary future Hermes versions, catalog approval, and other operating systems are not claimed.

## Install and select

Use Hermes's plugin lifecycle commands in the intended profile. Pin a reviewed full commit SHA for a reproducible installation:

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-default-plugin --ref <full-40-character-commit>
hermes plugins enable original-chrome-default
hermes tools
```

In the tools picker, select **Original headed Chrome · Default** as the browser provider and enable the plugin's **original_chrome** toolset for the intended platform. Install the declared dependencies through Hermes. No tool-override capability grant is required.

Provider selection alone is insufficient. In that Hermes profile's configuration, retain the following settings, preserving other disabled toolsets and unrelated entries:

```yaml
browser:
  cloud_provider: original-chrome-default
agent:
  disabled_toolsets:
    - browser
    - browser-use
plugins:
  entries:
    original-chrome-default:
      settings:
        expected_account: "<account approved by this build>"
```

Hermes owns plugin activation and the platform tool selection; use its commands to change them. The two global suppression entries keep native browser tools out of model sessions, including after this plugin is disabled or removed. The tools picker can change these entries when native browser groups are re-enabled, so verify them after changing tool selection. Read-only status reports `native_browser_tools_disabled`; it must be true. Start a new agent session after changing plugin or tool configuration.

For migration from 0.2.x, install the reviewed 0.3.0 revision, enable `original_chrome`, and add both suppression entries. Replace saved calls to `browser_exec` or `browser_vault` with `browser_original_chrome_exec` or `browser_original_chrome_vault`. An old `tools.override` grant is no longer used; inspect remaining grants with `hermes plugins capabilities original-chrome-default`. Existing session definitions must be refreshed with a new session.

```sh
hermes plugins disable original-chrome-default
hermes plugins enable original-chrome-default
hermes plugins uninstall original-chrome-default
```

These are the official disable, re-enable, and removal paths. Disable/removal unregisters only this plugin's tools. The native browser and vault handlers remain unchanged, and Hermes retains `agent.disabled_toolsets` in the profile configuration after uninstall. Browser provider selection is also retained separately.

Before opening a window, the plugin prepares a private snapshot of its worker code. This contains plugin source only, never a Chrome profile or cookies. While browser resources exist, a small watcher detects sustained removal of the installed source. It cancels this provider's script workers, cleans owned windows using the prepared code, releases its journal leases, and stops. Normal disable/reload also performs this cleanup through `on_unload`. Cleanup still reports uncertainty if ownership or closure cannot be proved. No browser process is killed.

Keep the native suppression entries when disabling or uninstalling if browser execution must remain unavailable. The plugin leaves no hidden guard after removal; the persistent restriction belongs to Hermes configuration. To intentionally switch to a native browser provider, select its provider and tools through Hermes, explicitly change the suppression entries, and start a new session. Provider selection alone is not a fallback-prevention mechanism. This policy applies to the configured profile and current native browser tool groups, not every future plugin or browser-like tool.

## Normal browser work

Ask the Hermes agent to browse with `browser_original_chrome_exec`. It accepts a bounded Python-like script with named browser helpers, assignments, loops, conditions, and plain data. It does not execute arbitrary Python, imports, filesystem/process/network calls, raw JavaScript, or raw CDP supplied by the agent.

For example, a tool call can use:

```python
goto_url('https://example.com')
wait_for_load(timeout=10)
print(read_page(limit=2000))
```

Other helpers cover visible controls, click/type/scroll, screenshots, owned tabs, and explicit dialog answers. The loaded tool description lists their exact signatures. Reuse the same `session` name for related calls within a turn; ownership is also scoped by the calling task, so separate agents do not share their owned tabs. They still share the original Chrome profile and its login state: a website login or logout in one owned window can affect other windows using that profile.

Owned windows are short-lived. They are cleaned when the run ends successfully, fails, is interrupted, or its Hermes session is finalized. A tracked host human-input wait defers ordinary end-of-run cleanup; interruption still cancels it. The next turn can open a fresh owned session using the same original Chrome login. This policy follows the host's run outcome, not a guess about whether the conversation's overall research goal is complete. An explicit `finish_browser()` remains available for earlier cleanup, but is not required in the user's prompt.

Timeout recovery preserves any returned partial findings and does not replay clicks, typing, navigation, or dialog answers. Follow the tool result's recovery state. After confirmed cleanup, another call with the same session name can start fresh. If cleanup cannot be confirmed, the plugin reports that limitation instead of claiming the windows disappeared.

The plugin never quits the original shared Chrome application. JavaScript dialog answers are explicit; ambiguous native dialogs and unrelated permission prompts are refused. Chrome login UI and OS permission changes remain operator-controlled.

## Status and diagnostics

Read-only status does not connect to Chrome or trigger a browser permission prompt:

```sh
hermes original-chrome status --json
```

In a Hermes conversation, `/original-chrome-status` runs the check in the actual gateway process. `ready` means the listed prerequisites passed; `browser_connection: not_probed` is deliberately separate from successful browser acceptance.

`chrome_gui` separately reports a stopped Chrome process, a running process with no windows, a running process with windows, or an unknown state. Missing permission or an incomplete native inventory yields unknown counts rather than an assumed zero. Titles, URLs, and page contents are not included.

`/original-chrome-test` is an operator diagnostic. It opens three owned sessions at `https://example.com`, starts them sequentially, performs page work concurrently, checks ownership, and cleans them up. `/original-chrome-test manual` waits for the operator's debugging-permission click. This command exercises the registered browser handler; it is not a test of three LLM agents.

`/original-chrome-test removal` opens one owned example.com session using a temporary copy of plugin source, deletes that temporary copy, and verifies automatic cleanup, journal retirement, and worker-snapshot removal. It does not uninstall the installed plugin or change its grants/configuration. Package-manager installation is tested separately.

## Vault and data boundaries

`browser_original_chrome_vault` exposes only `list` and `unlock`, dispatched through Hermes's public tool API to its registered native vault handler. Page actions such as fill, save-login, and enter-code are unavailable. Missing native support produces a refusal; there is no private vault adapter or credential fallback. The native `browser_vault` handler is not replaced.

Page text returned by `browser_original_chrome_exec` is sent to the model as-is, without secret filtering. A secret visible on a page can therefore appear in tool output and the conversation. Screenshots are also returned without redaction. The plugin retains its public result structure and error minimization, but neither is a secret filter.

The plugin reads Chrome's account/profile metadata and `DevToolsActivePort` to verify the original profile and current browser process. It reads process and Accessibility information, launches Chrome through macOS `open`, and uses loopback CDP. Requested navigation contacts the selected websites using Chrome's existing session. Workspaces, setup seed files, screenshots, and connection-coordination records are written locally. It does not upload that data to a plugin service or implement a self-updater.

These browser-script restrictions do not sandbox other Hermes tools or arbitrary code installed on the host.

## Development and verification

Use the existing Hermes interpreter with its dependencies already available:

```sh
HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1 <Hermes-python> tests/run_policy_suite.py
hermes plugins doctor /absolute/path/to/this/plugin --ci
hermes plugins validate /absolute/path/to/this/plugin --json
git diff --check
```

The regression runner uses inert browser transports, an isolated Hermes home, and network/GUI vetoes. It does not install dependencies. Live acceptance must separately cover Chrome fully exited, Chrome running without windows, existing user windows, and simultaneous agents. The operator prepares any condition that requires closing Chrome.

The installation regression dispatches the official CLI against a disposable local Git source and Hermes home, including real registration, disable/re-enable, and uninstall. It checks that native handlers remain intact, the plugin's own tools disappear after removal, and global browser suppression survives uninstall. It replaces PM's dependency-environment solve/publication with a fixture while retaining its manifest checks, so it does not claim to test dependency installation. A passing runtime `doctor` or manifest validation does not imply catalog acceptance or compatibility with every future Hermes release.

Vendored browser helper code retains its [upstream license](vendor/LICENSE.browser-harness). The repository's current source and tests are the behavior reference.

## Cooperation with Flow

GUI batches on Flow share a process-safe lease with the companion Flow service, keyed by the verified original profile. Flow URL aliases use one key. Other sites remain independent. Each script releases its leases on completion, exception, or process exit; a busy batch is not replayed automatically. Runtime source snapshots include the lease helper.

This is cooperative coordination, not a separate login session. Manual activity and other programs do not honor the lease. Navigation through a redirect may reach Flow before its destination is known; subsequent GUI helpers check the actual origin before acting. The plugin continues to own and clean only its own targets.
