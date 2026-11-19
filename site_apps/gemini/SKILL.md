# Inspect Gemini Web

Read the current operations with `browser_app` action `describe` and app `gemini`.
Choose an existing Chrome profile using `chrome_profiles` with `app: gemini`.
Use the same named `session` for `browser_app` and call `operation: inspect`.
The host gives this package its own Chrome window in the chosen profile.

`inspect` opens Gemini when needed, then reads the account indicator, the active
model label and known visible controls. It waits up to eight seconds for the
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
original account until its outcome is known. This release provides inspection.
