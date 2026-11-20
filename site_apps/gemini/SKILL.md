# Inspect Gemini Web

Read the current operations with `browser_app` action `describe` and app `gemini`.
Choose an existing Chrome profile using `chrome_profiles` with `app: gemini`.
Use the same named `session` for `browser_app` and call `operation: inspect`.
The host gives this package its own Chrome window in the chosen profile.

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

When deciding what to do about a limit, inspect the evidence and pick the next
profile explicitly if appropriate. Keep an unresolved provider request on its
original account until its outcome is known.

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
