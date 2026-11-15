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

To share one profile across several agents, give each agent the same current
directory ID and have each call `select` for its own session. To use different
profiles, assign the intended directory ID to each agent and use the same flow.

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

To move several active agents to one profile, have each agent call `select` with
the shared destination ID. Refresh `list` when a profile is added, removed or
renamed, or when selection reports that a profile is unavailable or replaced.
Chrome's profile management handles profile creation and removal.

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

## Create a website extension

Version 0.7.0 provides `browser_app`. Your packages live in `~/.hermes/browser-apps`,
independently of the installed plugin. A different root can be set through
`plugins.entries.original-chrome-default.settings.apps_directory`.

Create `~/.hermes/browser-apps/my-site/app.json` with the following content.

```json
{
  "api_version": 1,
  "id": "my-site",
  "name": "My website",
  "operations": {
    "inspect": {
      "description": "Open the site when requested and read its current title.",
      "parameters": {
        "type": "object",
        "properties": {"url": {"type": "string"}}
      }
    }
  }
}
```

Create `app.py` beside it.

```python
def run(context, operation, params):
    code = ''
    if params.get('url'):
        code += f"goto_url({params['url']!r})\n"
    code += 'print(js("document.title"))'
    result = context.browser_exec(code)
    return {
        'status': 'ok' if result.get('success') else 'failed',
        'data': result,
    }
```

Ask Hermes to call `browser_app` with the following arguments.

```json
{"action": "list"}
{"action": "describe", "app": "my-site"}
{"action": "run", "app": "my-site", "operation": "inspect", "session": "work", "params": {"url": "https://example.com"}}
{"action": "run", "app": "my-site", "operation": "inspect", "session": "work", "params": {}}
```

The final call reads the current document. Navigating depends on the code in
`run`. Reusing an alias keeps the owned browser session for related calls within
the caller's turn. Each app, agent, and conversation gets its own namespace.
The app's returned private `session` can be used with native `browser_exec` by
the same caller in that turn when further DOM inspection is needed.

Add an optional `SKILL.md` in the package to explain its operations. `describe`
reads its latest content. New packages and operations appear on the next tool
call. Edited Python source is compiled fresh, including rapid edits with the
same size. Relative Python imports keep each invocation's module namespace
separate. The loaded functions of an active operation remain in that invocation.

The context exposes the following values and methods.

| Member | Meaning |
| --- | --- |
| `app` | Package ID |
| `task_id`, `session_id`, `turn_id` | Calling Hermes identities |
| `session` | Prepared private browser-session name |
| `profile` | Current Chrome profile directory ID |
| `directory` | Created on access for app/owner artifacts under plugin data |
| `checkpoint(value)` | Atomically save JSON work position to `checkpoint.json` beside artifacts |
| `browser_exec(code, timeout_s=120)` | Native browser execution, with a decoded JSON result |

Return a JSON-serializable object. The host wraps ordinary values as `status`
`ok` with `data`. An explicit `status` may be `ok`, `running`, `quota_exhausted`,
`needs_inspection`, or `failed`. Add service evidence, a job ID, and artifact
paths as needed. The host adds the app, operation, private session and profile.
`success` is true for `ok` and `running`. Execution errors contain the exception
type/message and the requested app/operation.

The host validates the manifest's contract version, identity and operation
schema shape. The operation validates its own parameter values. `list` and
`describe` execute no package code. Errors in a package leave other valid
packages discoverable.

Package Python runs with the Hermes process's local permissions. Install code
you trust. Context/browser access lasts for the `run` invocation. Service rolling
and the initial Gemini/Flow packages remain in the [PRD checklist](../PLAN.md).

## Configure profiles for a website package

Pass the package ID as `app` to `chrome_profiles`, with the same session alias
used by `browser_app`. Ordinary browsing and each package have separate choices.

```json
{"action": "list", "app": "my-site", "session": "work"}
{"action": "select", "app": "my-site", "profile": "Profile 2", "session": "work"}
{"action": "set_default", "app": "my-site", "profile": "Profile 2"}
{"action": "set_rule", "app": "my-site", "scope": "session", "mode": "fixed", "profile": "Profile 2", "session": "work"}
{"action": "clear_rule", "app": "my-site", "scope": "session", "session": "work"}
```

`select` changes the current named session. `set_rule` persists a policy in plugin
configuration. Session policy follows the conversation and alias across turns.
Agent policy targets a Hermes task ID, which can change on the next turn.
`fixed` selects `profile`, `default` uses `profile_directory`, and `random` samples
current profiles once for the active session. Use `set_rule` with `scope` set to
`default` to configure future sessions for this service.

Platform rules can select different profiles for WhatsApp and Telegram. Subagent
rules can select a profile for a role or for every child using `*`.

```json
{"action": "set_rule", "app": "my-site", "scope": "platform", "target": "whatsapp", "mode": "fixed", "profile": "Profile 2"}
{"action": "set_rule", "app": "my-site", "scope": "platform", "target": "telegram", "mode": "default"}
{"action": "set_rule", "app": "my-site", "scope": "subagent", "target": "*", "mode": "random"}
```

Resolution starts with session, then agent, subagent role, platform, parent and
service default. An explicit child rule takes precedence over the parent's
selection. Parent selection is captured from the public lifecycle hook for the
matching service and alias. `list` reports both active selection and policy.
Several agents can resolve to the same profile and retain separate Chrome windows.

## Continue and manage a package

Before a long-running website operation returns, save its known job position and
write output files under `context.directory`.

```python
context.checkpoint({'job_id': job_id, 'phase': 'waiting'})
return {'status': 'running', 'data': {'job_id': job_id}}
```

`running` and `needs_inspection` preserve the owned browser session across turn
end in the serving Hermes process. Continue through the same package and alias
to retain the document, source profile and artifact directory. A completed result
returns `ok`. Stop, session finalization, disable and host unload close the owned
connection. The saved checkpoint and `result.json` remain available through the
`data_directory` shown by `describe`. Recovery after host restart follows the
package's saved checkpoint. Automatic job recovery/rolling is tracked in the PRD.

```json
{"action": "disable", "app": "my-site"}
{"action": "enable", "app": "my-site"}
{"action": "remove", "app": "my-site"}
```

Disable persists the flag and closes this package's owned sessions in the serving
Hermes process. A bound operation rechecks availability before driving Chrome.
An already-running Python callback can still be returning. While that callback or
native cleanup remains, the result contains `cleanup_pending` and source removal
waits. Retry the management action when it settles. Other processes check the
saved flag on their next call and own their in-flight command lifecycle.
Re-enabling uses fresh native names. Remove deletes its source after cleanup,
retaining plugin-data artifacts, checkpoints and receipts. Linked packages are
removed by unlinking the directory entry. A saved disabled flag also records
removal for future template installation.

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
