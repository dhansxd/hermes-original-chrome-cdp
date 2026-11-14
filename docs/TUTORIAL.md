# Tutorial

This walkthrough connects Hermes's native browser tools to your original Google
Chrome profile on macOS. It uses your own local Chrome installation and sign-ins.

## Prepare Chrome and macOS

1. Install Hermes Agent and Google Chrome. Confirm Chrome is available at
   `/Applications/Google Chrome.app`.
2. Open the Chrome profile you want to use. Visit `chrome://version` and look at
   **Profile Path**. Note its final component, for example `Default` or `Profile 2`.
3. Visit `chrome://inspect/#remote-debugging` and enable remote debugging.
4. Open **System Settings → Privacy & Security → Accessibility**. Grant access to
   the application that runs Hermes. Follow any restart request from macOS.

The permission belongs to the launching application or process. A Terminal-launched
Hermes session and an IDE-launched session can have different permission identities.

## Install the provider

Run the following commands in the environment where you use Hermes.

```sh
hermes plugins install https://github.com/dhansxd/hermes-original-chrome-cdp
hermes plugins enable original-chrome-default
hermes plugins list
```

Hermes displays source-scan and dependency information during installation or
enablement. Review the findings for the revision being installed. The declared
Python dependencies are `psutil` and `websockets`.

Open the native configuration picker.

```sh
hermes tools
```

Enable Browser Automation and Terminal on the intended Hermes surface, then select
**Original Chrome · CDP** as the browser backend.

## Apply the provider settings

Open the active Hermes profile's `config.yaml`, normally `~/.hermes/config.yaml`
for the default profile. Merge these keys into the existing sections.

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

Use the Chrome directory recorded earlier. The plugin enable command manages the
enabled-plugin list. Preserve other plugin entries and browser settings you need.

Review existing direct-CDP settings. Clear `browser.cdp_url`, `BROWSER_CDP_URL`,
`BU_CDP_URL`, and `BU_CDP_WS` when choosing this backend, so the selected provider
can own the browser connection. Apply the supported reload or restart action that
your Hermes version reports for configuration or dependency changes.

## Run a first browsing task

Start or return to a Hermes chat and send the following request.

> Use browser_exec to open https://example.com and report its title.

The first CDP connection can activate Chrome briefly for its debugging permission
dialog. The plugin checks the exact Chrome process, dialog, and socket before
performing the Accessibility press.

The task should use a new agent-owned Chrome window in the chosen profile. Chrome
can initially be stopped, running without windows, or already have windows open.
At task finalization, the plugin closes the targets it owns.

For a sign-in check, ask Hermes to open a website that you already use in that
profile and describe the signed-in state. This verifies the login stored by Chrome.
Review any screenshots or page excerpts locally before sharing them.

## Use another Chrome profile

Ask Hermes to list the current Chrome profiles with `chrome_profiles`. The result
contains each directory ID and display name. Profile additions, removals and name
changes are reflected on the next read.

Use this tool with the following arguments to select a profile for a named session.

```json
{"action": "select", "profile": "Profile 2", "session": "research"}
```

Run the browsing work through `browser_exec` with `session` set to `research`.
Several agents can use the same alias and profile with separate owned windows.
The same agent can also choose another profile for another named session.

Call `select` with a different profile and the same alias to switch that session.
The previous owned connection is cleaned up and the next browser call opens the
destination profile directly. Returning to an earlier profile gets a fresh
connection. Repeating the current choice preserves the active connection.

For example, ask Hermes the following.

> List my Chrome profiles, select Profile 2 for the research browser session, then
> open example.com in that session and report its title.

To change the saved default for future sessions, use `chrome_profiles` with the
following arguments, choosing a directory ID from your actual inventory.

```json
{"action": "set_default", "profile": "Profile 2"}
```

The default is stored in `plugins.entries.original-chrome-default.settings.profile_directory`.
Each active session keeps its own choice. A new named session uses the current
default when it first browses. Separate Hermes profile homes have their own plugin
settings. A profile removed from Chrome can be replaced by selecting an available
profile from the refreshed inventory.

## Check parallel browsing

1. Keep a manual Chrome tab open with a page you can recognize.
2. In two distinct Hermes agent tasks, ask each agent to open a different page with
   `browser_exec`. Both agents may use the same native session alias.
3. Confirm each task has its own window and page.
4. Finish one task and verify that the other task and the manual tab remain usable.

Repeat with agents assigned to different Chrome profiles. Change the default while
they are active, then create a new named session and check its chosen profile.

Hermes task and conversation identities separate the native session names. The
relay routes each session to its owned tabs and opener-linked popups. Within the
same Chrome profile, cookies and website storage remain shared. Signing out of a
site can therefore affect the other agent and manual browsing on that profile.

## Update

```sh
hermes plugins update original-chrome-default
hermes plugins list
```

Review the update result and apply the reload or dependency-environment action
requested by Hermes. Check the provider selection in `hermes tools` afterward.

## Switch back, disable, and uninstall

Select **Local** in `hermes tools → Browser Automation` to use Hermes's built-in
browser. Then disable this provider through the native command.

```sh
hermes plugins disable original-chrome-default
```

To use Original Chrome again, enable the plugin and select it in the picker.

```sh
hermes plugins enable original-chrome-default
hermes tools
```

For removal, select Local first and run the following command.

```sh
hermes plugins remove original-chrome-default
```

In the tested Hermes build, CLI disable asks the gateway to reload plugins.
Dashboard disable and removal need a supported plugin reload to release the loaded
provider. Follow the lifecycle status shown by the Hermes surface you use.
Hermes-managed plugin data can remain after removal.

## Understand cleanup limits

Normal finalization closes the agent-owned targets, relay, and CDP supervisor.
Hermes manages its native driver processes and session cache through its own
lifecycle. Unload first closes admission, so concurrent calls cannot leave a new
active relay after its cleanup snapshot. A late call fails through the CDP path.

An unconfirmed cleanup retains session ownership in memory for another attempt
and an exit callback. When cleanup succeeds, that state is released. If the process
ends before cleanup succeeds, the in-memory record is lost and an owned tab may
remain. Inspect the exact session before attempting manual cleanup.

## Report a problem

Include plugin, Hermes, Chrome, and macOS versions, whether Chrome started stopped
or already running, the selected profile-directory type, and the redacted error.
Describe whether the problem happened during startup, browsing, or cleanup.
Keep account identities, cookies, credentials, full profile paths, and page contents
local when preparing a public issue.

Native install and lifecycle commands are described in the official documentation.
[Hermes plugin guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
