# Gemini Web controls

Read the current operations with `browser_app` action `describe` and app `gemini`.
Choose an existing Chrome profile using `chrome_profiles` with `app: gemini`.
Use the same named `session` for each related `browser_app` call. Start with
`open_chat` and pass `chat` when opening an existing conversation. Chrome opens
Gemini in the selected profile.

Call the mapped action directly when you know which control to use.

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
