# Original Chrome Default for Hermes

A macOS browser provider that runs Hermes browser work in the installed Google Chrome GUI and its original `Default` profile. Existing logins stay in Chrome. The plugin creates and controls its own windows, and leaves unrelated user windows alone.

This is a personal build: production use is restricted to the account allowlist in `plugin.py`. Configuring a different account does not expand that scope. It does not copy profiles, export cookies, or fall back to a headless or cloud browser.

## Requirements

- macOS with a logged-in Aqua desktop and Google Chrome at `/Applications/Google Chrome.app`.
- Chrome 144 or newer with remote debugging enabled by the operator at `chrome://inspect/#remote-debugging`. Chrome asks permission for new debugging connections.
- Accessibility permission for the process that actually runs Hermes. A successful check in Terminal does not establish permission for a gateway, or vice versa.
- The plugin enabled in the intended Hermes profile, with the `tools.override` capability granted through Hermes.
- Browser provider `original-chrome-default` and the expected account configured below. Current Hermes selects the provider through `browser.cloud_provider`; a legacy `browser.backend: browser-use` is accepted, but is not required.
- Both the `browser` and `terminal` toolsets enabled in the agent session. Installed Hermes gates `browser_exec` on terminal availability even though this plugin's browser script cannot execute shell commands.

The installed Hermes build is the compatibility reference. Browser and lifecycle integration use registered tools, the browser-provider API, and plugin hooks. Forced output redaction still calls Hermes's internal `agent.redact` utility because the installed public API has no equivalent. Compatibility with arbitrary Hermes versions, catalog approval, and other operating systems are not claimed.

Hermes documents [granted built-in tool overrides](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/#overriding-a-built-in-tool), which this plugin needs for `browser_exec` and `browser_vault`. In the checked core revision `67d47601bc5f8ed322451a672c843ed0e1a7c42c`, the catalog validator still rejects those two declared names as built-in collisions, even with `tools.override` declared. This is an outstanding catalog-admission limitation. The official Git install, enable, and runtime doctor paths use separate checks; the manifest keeps the actual tool names visible.

## Install and select

Use Hermes's plugin lifecycle commands in the intended profile. Pin a reviewed full commit SHA for a reproducible installation:

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-default-plugin --ref <full-40-character-commit>
hermes plugins enable original-chrome-default
hermes tools
```

Accept the declared dependency and capability prompts only when you intend to enable them. In Browser Automation, select **Original headed Chrome · Default**. The row is available after the plugin has loaded with its required grant.

The resulting browser settings and the plugin's profile-local setting are:

```yaml
browser:
  cloud_provider: original-chrome-default
plugins:
  entries:
    original-chrome-default:
      settings:
        expected_account: "<account approved by this build>"
```

Hermes owns the enabled list and capability grants; use its commands and consent flow to change them. Preserve other configuration entries. After a plugin change, start a new agent session so its tool definitions reflect the loaded code.

```sh
hermes plugins disable original-chrome-default
hermes plugins enable original-chrome-default
hermes plugins uninstall original-chrome-default
```

These are the official disable, re-enable, and removal paths. If switching away from this provider, select the replacement through `hermes tools` as well; browser selection is separate from the plugin's own settings.

Before opening a window, the plugin prepares a private snapshot of its worker code. This contains plugin source only, never a Chrome profile or cookies. While browser resources exist, a small watcher detects sustained removal of the installed source. It cancels this provider's script workers, cleans owned windows using the prepared code, releases its journal leases, and stops. Normal disable/reload also performs this cleanup through `on_unload`. Cleanup still reports uncertainty if ownership or closure cannot be proved. No browser process is killed.

Disabling or uninstalling removes this plugin's enforcement and restores Hermes's native browser handler. Leaving `browser.cloud_provider: original-chrome-default` in the config does **not** enforce original Chrome once the plugin is absent: the checked Hermes version catches the missing-provider error and can route to its local browser resolver. If alternate browser execution must remain prohibited, disable browser tools through `hermes tools` before disabling or removing this plugin, then start a new agent session. The plugin leaves no hidden guard active after removal.

## Normal browser work

Ask the Hermes agent to browse normally. `browser_exec` accepts a bounded Python-like script with named browser helpers, assignments, loops, conditions, and plain data. It does not execute arbitrary Python, imports, filesystem/process/network calls, raw JavaScript, or raw CDP supplied by the agent.

For example, a tool call can use:

```python
goto_url('https://example.com')
wait_for_load(timeout=10)
print(read_page(limit=2000))
```

Other helpers cover visible controls, click/type/scroll, screenshots, owned tabs, and explicit dialog answers. The loaded tool description lists their exact signatures. Reuse the same `session` name for related calls within a turn; ownership is also scoped by the calling task, so separate agents do not share their owned tabs.

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

While this provider is selected, vault page actions such as fill, save-login, and enter-code are unavailable. `list` and `unlock` can use only the native synchronous handler already registered by Hermes. Missing native support produces a refusal; there is no private vault adapter or credential fallback.

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

The installation regression dispatches the official CLI against a disposable local Git source and Hermes home, including capability consent, real registration, disable/re-enable, and uninstall. It replaces PM's dependency-environment solve/publication with a fixture while retaining its manifest checks, so it does not claim to test dependency installation. `validate` currently exits with the two collision errors described above; a passing runtime `doctor` does not imply catalog acceptance.

Vendored browser helper code retains its [upstream license](vendor/LICENSE.browser-harness). The repository's current source and tests are the behavior reference.
