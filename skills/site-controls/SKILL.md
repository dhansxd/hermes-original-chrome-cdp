---
name: site-controls
description: Browse websites in Original Chrome with browser_exec, use mapped site controls, download files, and keep or resume a Chrome window across turns.
---

# Browsing in Original Chrome

Use `browser_exec` for website navigation, links, forms, page inspection, and
downloads in Original Chrome. Calls named `browser_app` in
older chats now use the `site_control` parameter on `browser_exec`.
For a request specifying Gemini Web, open Gemini with `open_chat` and use its
controls in the same browser session. Pass a site's mapped operation
as JSON text in the tool's `site_control` parameter. Mapped operations run alone. A confirmed missing-control report can accompany fallback code. Use `code`
with `site_control` omitted or null for an ordinary DOM or screenshot call. For example, in an open Gemini chat:

```json
{"app":"gemini","operation":"click","params":{"control":"deep_research"}}
```

On an open page in local Chrome, use the automatically learned controls via
`site_control` action `list_learned_controls`. To find an exact label, pass
`params.label`. Use `click_learned_control` with the listed ID in
`params.control`. If the control needs inspection or is absent, continue
using native DOM and then screenshot as needed in the same session. Check the
page before repeating a click reported as dispatched.

Use a known control directly. For the site's operations and guide, pass
`{"action":"describe","app":"gemini"}` or `{"action":"describe","app":"flow"}`
as `site_control`. Use `{"action":"list"}` to discover other installed packages.
Keep the same `browser_exec.session` across calls. On an ordinary website, use
the usual browser helpers. When a mapped control needs inspection, use the
normal DOM and screenshot helpers in this window and continue the task there.
All sessions use the one device reported by `chrome_profiles` with
`list_devices`. For an explicit request to switch Chrome devices, use
`set_device`. Select profiles only on the active device, with the same session
alias as `browser_exec`. Report an unavailable device to the user.

For a confirmed missing control on an installed site, use `site_control` with
`action: record_missing_control`, its `app`, and `params` containing
`page_or_mode`, `control`, and `fallback` (`dom` or `screenshot`). Check the
relevant panel and model first. Include that report alongside the native `code`
in the same `browser_exec` call when acting on the newly discovered control.
Use the same report for controls identified visually. A missing selector alone
does not confirm a finding.

After submitting once, follow `next_control` in that session while the site
reports `running`. The plugin spaces out these progress checks. A long sleep
inside a browser script can let Hermes close the owned window as idle.
If a running task has no usable mapped reader, use the returned `observe`
control to read the live page. Identify the finished result of this submission using
the relevant DOM or screenshot. Supply its unique CSS selector in
`params.result_selector` on the same `observe` control. The plugin reuses it
on subsequent checks. For an existing job ID, follow its package's job check.

Confirm the new result and finish any requested download and delivery before reporting
completion. If the requested site fails, report what blocked it there and
ask before substituting another generator or service.

## Keep a Chrome window available

Keep a window when the user explicitly asks to leave it open or when the
requested outcome clearly requires it to remain open after the turn. First
verify that the page or ongoing action the user asked to leave available is
ready. A `running` status alone does not request retention. When the user asks
to return later, report the confirmed progress as pending.

Pass `{"action":"keep_window"}` as `site_control` with the current
`browser_exec.session`. Wait for `state: kept` before
saying that the window will remain open. In a later turn in the same Hermes
conversation, `{"action":"list_windows"}` lists kept windows. To continue, use
that exact ID as `browser_exec.session` for site controls or native `code`.
Check the existing page or job without starting it again. If asked to close a
kept window, pass `{"action":"close_window"}` with its exact session ID. Ask
which window only if the request is ambiguous and several windows match.
