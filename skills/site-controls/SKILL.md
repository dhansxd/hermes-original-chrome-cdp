---
name: site-controls
description: Use mapped Chrome controls for Gemini Web and Google Flow tasks, including images, video, Deep Research, chats and downloads.
---

# Website controls in Original Chrome

When the user requests work on a specific website, carry out the work on that
site. Use the site's mapped controls through `browser_app` first.

- **Gemini Web** (`gemini.google.com`). Call `browser_app` with
  `action: describe` and `app: gemini`. For an image, use the available actions
  to open the chat, select Create image, enter the prompt, and click Send.
- **Google Flow**. Call `browser_app` with `action: describe` and `app: flow`.
  Use the operation for the selected project and task. Keep the returned job
  ID when continuing a generation or downloading its result.
- **Other sites**. Use `browser_app list` to find an installed site package.
  Read its current guide and available operations with `describe`.

Use the same session for the work. For a control the package cannot reach,
pass its exact returned `session` to `browser_exec` and inspect the relevant
DOM in that window. Use a screenshot when the DOM is insufficient.

When fallback was needed for a control that exists in the site's UI and has no
mapped action in its package, record the finding before the final answer. Call
`browser_app` with `action: record_missing_control`, the same `app` and exact
returned `session`, and `params` containing `page_or_mode`, `control` (the button
label or action), and `fallback` (`dom` or `screenshot`). Check the relevant panel
and selected model first. Keep the finding to those UI details.

Confirm the new result and finish any requested download before reporting
completion. If the requested site fails, report what blocked it there and
ask before substituting another generator or service.
