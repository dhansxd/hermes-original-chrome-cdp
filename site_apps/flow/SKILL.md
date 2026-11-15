# Google Flow through Original Chrome

Use `browser_app` with `app: "flow"`. The extension uses the calling agent's
owned Chrome window and original profile. General browsing and other extensions
have separate sessions. Read `browser_app` action `describe` for current operations.

1. Choose the starting profile with `chrome_profiles` using `app: "flow"` and
   the same session alias used for the operations below.
2. Run `create_project` with a title, or pass an existing canonical `project` ID
   or URL to an operation. Project selection is kept per Chrome profile.
3. Run `inspect` for the current model names and setting options. `configure`
   selects `mode`, `kind`, `model`, `aspect`, `count`, and the controls exposed
   by the selected model. Classic video supports `duration`, `resolution`, and
   `input_type` where the current UI provides them.
4. Run `generate_image` or `generate_video` with a prompt and the settings.
   Keep the returned `job` ID. A running/uncertain response belongs to that
   source request. Resume with that same `job`, operation and session alias.
5. A completed response includes native request identity, original file path,
   byte count, SHA-256, decoded media metadata and observed credit balance.

Example call arguments follow.

```json
{
  "action": "run",
  "app": "flow",
  "session": "production",
  "operation": "generate_video",
  "params": {
    "project": "project-id-from-create-project",
    "mode": "classic",
    "model": "model-name-from-inspect",
    "aspect": "9:16",
    "resolution": "720p",
    "duration": 3,
    "count": 1,
    "prompt": "A locked-off close-up of steam rising from a ceramic teapot. Quiet room ambience, no music."
  }
}
```

Resume by keeping `job` from the result at the tool's top level and passing
`params: {}`. Recovery observes the original project and download receipt.
It does not repeat Generate. Stop and tool timeouts require this recovery path.

## Agent mode

`mode: "agent"` uses native Agent settings and automatic approval as authorized
by the user. Image/video model, aspect and count are Agent defaults. The extension
also includes these choices in the Agent instruction. Agent may choose different
generation parameters, so compare the decoded result with the requested output.
The inspected Agent settings have no hard duration or resolution controls.
Include desired seconds/resolution in the prompt and report them as requests.

## References

Use `upload` with a local `path`, then `bind_reference` with the returned exact
`title` and `kind`. Images can use `slot: "first"` or `slot: "last"` in classic
Frames mode. The native picker and loaded ingredient/frame are checked.
Generation also accepts a `references` array containing local `path`, `kind` and
optional `slot`. It uploads and binds after filling the prompt.

Local reference files can be uploaded again on a destination account. A saved
character/voice name requires that account's native entity or a portable source
before it can continue there. Preserve unresolved source jobs and reference evidence.

## Current acceptance scope

Classic and Agent image/video generation/download have real-file evidence. JPEG
upload, image Ingredients, and video using both first/last Frames are verified.
Character/voice acceptance and real-account quota handoff remain open in PLAN.md.
Use the native browser
session for inspection when the extension reports an unavailable control.
Keep such findings explicit and preserve the original job.

FFmpeg and ffprobe must be available to the Hermes process for media decoding.
Chrome's normal download directory is used. Receipts and collected files live in
plugin data outside this editable source package. Keep those private files out of Git.
