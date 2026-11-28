---
name: site-controls
description: Browse websites in Original Chrome with browser_exec, use mapped site controls, select files for upload, download, and resume a kept window.
---

# Browsing in Original Chrome

Use `browser_exec.site_control` for structured browser actions and site
operations in Original Chrome. Pass each request as JSON text and keep the task's session.
For Gemini Web, use its
`open_chat` operation and the controls listed in the Gemini guide.

Use these actions in `site_control` to open a known address and fill a field
that can be identified by one CSS selector on the current page:

```json
{"action":"navigate","params":{"url":"https://example.com"}}
```

```json
{"action":"type","params":{"selector":"#search","text":"Search terms"}}
```

Keep the same `browser_exec.session` across calls. Typing replaces the existing
text by default. Pass `"clear_first":false` in `params` to type at the current
insertion point.

Read visible text from the open page with `{"action":"read"}`. To read a
specific part of the page, pass a CSS selector in `params`. The result
contains the page title, text, and a `truncated` flag. If the text was
truncated, read a smaller section in the same browser session.
`read` can also take `max_chars` and a CSS `frame` selector for an iframe.
Use `inspect` with a selector to see element attributes, or `page_info` for
the current URL, title, viewport and scroll position.

To activate a named control in the current page, use
`{"action":"click","params":{"target":"Show details"}}`. If it returns a
`screenshot_id`, use the screenshot to locate that same control. Repeat the
action and target with the returned ID and `point: [x, y]`. Measure each
coordinate as a fraction of the screenshot width or height from the top-left
corner. Use the same browser session. For `stale_screenshot`, request the
named click again. Once the click is dispatched, inspect the outcome before
deciding to click again.

The plugin selects matching site controls or catalog entries before trying
DOM and screenshot fallback. Use `read` to check the result of a dispatched
click. Use `screenshot` when the requested result is an image of the page.
A screenshot from that action carries no click continuation ID.

## Select a file

Use `upload` in the current tab with the intended file's absolute path.
When the page has one enabled file input, pass `path` by itself. When a
button opens the picker, add its visible label as `target`.

```json
{"action":"upload","params":{"path":"/absolute/path/video.mp4","target":"Pilih file"}}
```

If this returns a screenshot ID, continue the same named click with its ID
and position. The file request remains attached to that click. Pass `paths`
instead of `path` for a file input that accepts multiple files. Check the page
for upload progress after `file_selected`. Read the result before retrying an
unconfirmed selection.

## Native browser actions

- `scroll` accepts `dx`, `dy`, and optional viewport coordinates `x`, `y`.
- `press_key` accepts a `key` and the optional native modifier bitmask.
  Enter or Space on a focused control uses the named click path when that
  key activates the control.
- `wait` accepts `mode` of `load`, `element`, `network_idle`, or `seconds`.
  Use `selector` for `element` and `seconds` for a fixed delay.
- `tabs` accepts `mode` of `list`, `current`, `open`, `switch`, `close`, or
  `ensure`. Pass `url` to `open` and a task `target_id` to `switch` or `close`.
- `events` returns a summary of CDP observations from the current session.
- `screenshot` accepts optional `full`, `max_dim`, and a new absolute PNG
  `path`.

For a request naming a site section, open the site first and request the
named control. For an explicit URL, open that address. Use
`{"action":"describe","app":"gemini"}` or `{"action":"describe","app":"flow"}`
for site-specific operations. Select profiles only on the active Chrome
device with the task's session alias. Report an unavailable device.

For a confirmed UI gap on a site with a package, use `record_missing_control`
with the site ID, page or mode, control and fallback. The report records the
finding in the same session.

After submitting once, follow `next_control` in that session while the site
reports `running`. The plugin spaces out these progress checks.
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
that exact ID as `browser_exec.session` for site controls or ordinary browsing.
Check the existing page or job without starting it again. If asked to close a
kept window, pass `{"action":"close_window"}` with its exact session ID. Ask
which window only if the request is ambiguous and several windows match.
