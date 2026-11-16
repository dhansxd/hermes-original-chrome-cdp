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
optional `slot`, or the exact native `title` for an existing asset. It uploads
and binds after filling the prompt. Character portraits and voice audio IDs are
checked in the actual chips. Completed results include the reference evidence.

## Saved characters and voices

Select classic video Ingredients with a compatible model, such as an available
Omni Flash model, before opening the native Voices picker. Use `create_voice`
with `base` from that picker, a unique `name`, exact sample `dialogue`, and
`performance` directions. It generates one preview, saves one custom voice and
returns its native audio ID, saved fields and decoded WAV. Retain the returned
job when preview/save is uncertain. Resume that job to retrieve the same draft
or saved voice.

Use `create_character` with a local image `path`, `name`, optional `description`
and optional exact saved `voice` name. The operation uploads the portrait,
creates one native character, saves its fields and reads them back from its
character URL. Recovery uses that same character ID.

Pass saved entities to generation as `{"title":"Saved name","kind":"character"}`
and `{"title":"Saved voice name","kind":"voice"}`. Explicitly bind the voice
when it is required. A character's voice label alone does not verify an audio
ingredient. Repeated binding verifies existing native identity before another
gesture. Use only the reference types enabled by the current mode/model.

Voice previews are genuine generated audio. Deliver samples to the user for
accent, timbre and naturalness judgments. File decoding and matching IDs establish
technical retrieval and binding.

## Account rolling and continuation

Flow has its own starting profile and rolling order. Choose them with
`chrome_profiles`, `app: "flow"`, and the operation's session alias. The host reads
the current Chrome profile inventory for each rolling round. It retains the
source job while its provider outcome is unresolved.

Native credit evidence triggers continuation on the next available account. The
classic composer supplies its current quote after references are attached. At zero
credits in Agent mode, the extension inspects the same model's native classic quote
and restores Agent settings before continuing. This is recorded as classic price
evidence. Free image generation remains available when its native quote is zero.

Each destination gets one checkpointed project for that job. Local image/video
references are uploaded there. Completed source files remain in the result when
the destination generates the remaining output count. Resume the same job after
an interruption during project, voice, character or video preparation.

For saved entities, include an original creation `definition` in each reference.
The extension also retains definitions from entities created in the same app
session. A voice definition contains `name`, `base`, `dialogue` and `performance`.
A character definition contains `name`, local portrait `path`, `description`, and
optional `voice`. Include `voice_definition` when that voice is custom and is
carried through the character. An explicit voice reference verifies the separate
audio ingredient for the generated video.

```json
{
  "title": "Saved voice",
  "kind": "voice",
  "definition": {
    "name": "Saved voice",
    "base": "base-name-from-native-picker",
    "dialogue": "Exact sample dialogue",
    "performance": "Original performance direction"
  }
}
```

The destination synthesizes a new voice from that recipe and creates a character
from the portable portrait. Results expose destination IDs, the preparation method
and the saved WAV for listener review. A manually created native entity needs its
creation definition supplied before cross-account preparation can continue.
Native Remix imported the tested character, while its custom voice remained
unavailable on the destination account. The tested continuation path uses the
explicit creation definitions above.

## Current acceptance scope

Classic and Agent image/video generation/download have real-file evidence. JPEG
upload, image Ingredients, and video using both first/last Frames are verified.
Classic and Agent rolling from an exhausted source account to a funded destination
produced decoded five-second MP4 files. Character/voice preparation resumed within
the same classic job. Hermes chat CLI ran the Agent rolling test with a local
portrait reference. A real provider quota-reset event remains open in PLAN.md.
The generic reset/revisit logic has regression and native fixture coverage.
Flow rejected a test asking to change speech in an uploaded video and displayed a
refund notice. Preserve that provider restriction when designing reference inputs.
Use the native browser
session for inspection when the extension reports an unavailable control.
Keep such findings explicit and preserve the original job.

FFmpeg and ffprobe must be available to the Hermes process for media decoding.
Chrome's normal download directory is used. Receipts and collected files live in
plugin data outside this editable source package. Keep those private files out of Git.
