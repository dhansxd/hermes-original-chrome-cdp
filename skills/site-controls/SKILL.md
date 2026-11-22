---
name: site-controls
description: Use mapped Chrome controls for Gemini Web and Google Flow tasks, including images, video, Deep Research, chats and downloads.
---

# Website controls in Original Chrome

Use `browser_exec` throughout the browser task. Calls named `browser_app` in
older chats now use the `site_control` parameter on `browser_exec`.
For a request specifying Gemini Web, open Gemini with `open_chat` and use its
controls in the same browser session. Pass a site's mapped operation
as JSON text in the tool's `site_control` parameter. Mapped operations run alone. A confirmed missing-control report can accompany fallback code. Use `code`
with `site_control` omitted or null for an ordinary DOM or screenshot call. For example, in an open Gemini chat:

```json
{"app":"gemini","operation":"click","params":{"control":"deep_research"}}
```

Use a known control directly. For the site's operations and guide, pass
`{"action":"describe","app":"gemini"}` or `{"action":"describe","app":"flow"}`
as `site_control`. Use `{"action":"list"}` to discover other installed packages.
Keep the same `browser_exec.session` across calls. On an ordinary website, use
the usual browser helpers. When a mapped control needs inspection, use the
normal DOM and screenshot helpers in this window and continue the task there.

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
