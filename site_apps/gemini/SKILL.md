# Gemini Web controls

Pass JSON text in the `site_control` parameter of `browser_exec` for each request
below. To read the site's operations, pass `{"action":"describe","app":"gemini"}`.
Keep the current Chrome profile and the same `browser_exec.session` throughout
the task. Choose an existing Chrome profile with `chrome_profiles` only when the
task calls for a different profile.

If Gemini is not open in this window, set `site_control` to
`{"app":"gemini","operation":"open_chat"}`. To resume a
specific conversation, pass its ID in `params.chat`. On the active page,
open a menu with a named click in that same session:

```json
{"action":"click","params":{"target":"Tools"}}
{"action":"click","params":{"target":"Model picker"}}
```

Read any required labels from the open menu using the native DOM helpers.
Use the package's mapped operations below for composing, selecting a tool or
model, and following a submission.

For an existing Deep Research report, open its conversation and call
`read_result`. Follow the offered `open_research_report` control and read
the report in that same session.

To start Deep Research, use the topic from the request or the conversation. Ask for
the topic if it is missing. Select `deep_research`, enter the topic, then send it
once. A confirmed selection returns `mode_active: true`. If Send reports that
Deep Research is inactive, inspect the composer in the same window and confirm
the selection before sending. Use the same composer actions for a research
follow-up. Follow `next_control` while Gemini is preparing the plan, including
when Send reports `research_submission_pending`. Use the browser progress
checks in the same window during the wait. After a reload, check the existing
submission there. For a request to run the research, use the start
button when Gemini presents the plan. Open a completed report when offered,
then read it with `read_result` (stage `report_ready`). If `read_result` fails
with `research_no_plan`, Gemini returned only text. Report what it said.
If the research panel needs inspection,
examine it in the same window and record a confirmed missing control with the
fallback.

| Operation | Action |
| --- | --- |
| `open_chat` | Open Gemini Web or an existing conversation by ID |
| `type_prompt` | Fill the empty composer without submitting |
| `click` | Use a named control such as `create_image`, `deep_research`, or `send`. Send reports `running` while the request is still awaiting its result. |
| `select_model` | Click the model matching the visible label |
| `read_result` | Read the latest visible text response or report that it is still running |

For example, select a mapped tool in the open chat using:

```json
{"action":"run","app":"gemini","operation":"click","session":"work","params":{"control":"create_image"}}
```

The action returns only its result. If a control is unmapped, hidden behind a
banner, or otherwise unavailable, the result is `needs_inspection`. Pass its
returned `session` to native `browser_exec`. Inspect the relevant DOM or use a
screenshot if needed, then continue with the same Chrome window. After Send,
verify that the new response has appeared and finish any requested download
before ending the turn. If Send is unconfirmed, check the chat before retrying.
For an existing or newly generated video, call `click` with `control: download_video`
on the requested response. Follow `read_result` while Chrome finishes its download.
Use the verified `data.file.path` for the current channel's requested attachment.
A “video ready” message only confirms generation. If verification fails, report the
download error and keep the real site as the source.
For an image request, verify the generated image in that response. Use Gemini's
download control in the same window, record a missing mapping if DOM inspection
was needed, and deliver the downloaded file when requested.

## Inspect the current page

`inspect` opens Gemini when needed, then reads the chat ID, account indicator,
active model label and known visible controls. Pass `params: {"chat": "c_CHAT_ID"}`
to open an existing conversation in the chosen profile. If that chat is already
open, the inspection reuses the current page. It waits up to eight seconds for the
active model label. If the label remains unreadable, it returns `model: null`.
An account is returned as an identifier and masked hint. `not_observed` means a
control was outside the visible snapshot.
Items inside closed menus can have this status. `ambiguous` means the page showed
more than one matching control or account. The inspection leaves the composer
and menus alone.

Treat usage notices as observed UI text. A notice can refer to a particular model
or action. `unknown` means there was no recognized visible notice. It gives no
evidence of available credit. Report a reset time only when the UI displays it.

Use the observed notice to decide whether to wait for reset or choose another
profile for future work. Keep an unresolved provider request on its original
account until its outcome is known.

## Reply to an existing chat

Use operation `reply` with the same Chrome profile and a previously verified
chat ID. Use the active text model and an empty composer. Choose a new
`request_id` for each intended follow-up.

```json
{"action":"run","app":"gemini","operation":"reply","session":"work","params":{"chat":"c_CHAT_ID","prompt":"Please expand on the second point.","request_id":"follow-up-1"}}
```

Save the request ID, chat ID and profile. The operation sends one message and
returns the new answer after matching it to that message. On a timeout or
`needs_inspection`, repeat the same `reply` with the original profile, chat,
prompt and request ID. This checks the original conversation for the response.
Keep using the original ID until the outcome is known. A completed ID returns
the saved result. Inspection may be necessary if the page stops exposing the
observed chat or response controls.
Long answers can return a preview with `answer_truncated: true`.
The complete text remains available in the original Gemini chat.

## Continue a text task on another profile

Add `continuation` to a new `reply` when the user authorizes cross-account
continuation. Set `model` to the exact label from `inspect` and `checkpoint` to
the portable text context the destination may receive. Include all context
needed for the follow-up. The destination starts a fresh chat with only this
checkpoint and the requested follow-up. The original chat, its upload IDs and
files belong to their original account.

The extension can hand off when the verified Gemini page explicitly reports
that the selected model's quota is exhausted and blocks Send for this draft.
The unsent draft stays on the source page. Use the displayed `reset_text` when
present. After Send, reconcile an uncertain result using the original job and
profile.

Manual handoff is the default. A result with `awaiting_profile: true` is ready
for a different Chrome profile with a distinct account. Pass the saved job ID
and the user's explicitly selected `target_profile` with the same operation
and session.

```json
{"action":"run","app":"gemini","operation":"reply","session":"work","job":"saved-job-id","target_profile":"Profile 2","params":{}}
```

For automatic handoff on new jobs, merge these settings under
`plugins.entries.original-chrome-default.settings` in Hermes configuration.

```yaml
handoff_mode:
  gemini: automatic
rolling_profiles:
  gemini: [Profile 2, Profile 10]
```

Select the same text model in your destination profiles. If a destination
confirms that it stopped before Send, manual mode keeps the job available for
another profile or a retry after fixing the model. Automatic mode moves to
the next configured profile. Confirmed replies include the destination chat ID.
To observe an unconfirmed request, pass the saved job ID alone. Fresh-chat
recovery requires the original observed document until the destination chat ID
has been verified.
