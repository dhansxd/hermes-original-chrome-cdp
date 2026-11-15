# Rolling and provider-request recovery

Version 0.8.0 supplies generic rolling for website packages declaring
`"profile_policy": "rotate_on_limit"` in `app.json`. The package supplies UI
interaction and provider evidence. The host supplies profile selection, account
deduplication, handoff, durable receipts and reconciliation. Initial Gemini and
Google Flow packages are tracked in [PLAN.md](../PLAN.md).

## Package callbacks

The package defines four synchronous functions.

| Function | Contract |
| --- | --- |
| `identify(context, operation, params)` | Read the service account and operation quota scope from the selected profile's current UI |
| `run(context, operation, params)` | Perform the requested operation, reporting acceptance and its result |
| `handoff(context, packet)` | Prepare the destination project/chat and local references, returning destination `params` |
| `resume(context, record)` | Reconcile the recorded source request or interrupted preparation |

`identify` returns the following shape, populated from current website evidence.
Wait for the relevant UI to finish loading before reading it.

```json
{
  "account": {"id": "stable-service-account-id", "evidence": "Current account UI readback"},
  "quota": {"scope": "video:model-name", "available": true, "evidence": "Current availability readback"}
}
```

`available` may be omitted when the service exposes no quota readback. Known
exhausted accounts require fresh positive availability evidence before reuse.
`quota.scope` identifies the affected service operation/model pool. An account
that appears in multiple profiles shares its recorded quota state within that
package and scope. An unusable profile can return top-level `available: false`
with evidence, such as an absent sign-in. A technical probe failure returns an
inspection outcome for that job.

## Submit and report outcomes

Each host job owns one provider request or request group. Immediately after the
website accepts it, call `context.accepted(provider_request_id, data)` to save the
receipt before waiting. `context.job_id` identifies the host job and can help the
package reconcile its UI operation. Save portable progress through
`context.checkpoint(value)` and files under `context.directory`.

```json
{"status": "running", "request": {"state": "accepted", "id": "provider-request-id"}}
```

Return a matching completed request when its verified result is ready.

```json
{
  "status": "ok",
  "request": {"state": "completed", "id": "provider-request-id"},
  "data": {"files": ["/absolute/path/to/result.mp4"]}
}
```

A proven quota refusal has the following shape.

```json
{
  "status": "quota_exhausted",
  "request": {"state": "rejected"},
  "quota": {
    "scope": "video:model-name",
    "exhausted": true,
    "evidence": "Provider refusal for this request",
    "reset_at": "2099-01-01T00:00:00Z"
  },
  "handoff": {
    "instructions": "Portable work context",
    "settings": {"aspect_ratio": "9:16"},
    "files": ["/absolute/path/to/reference.png"],
    "completed": ["already-downloaded-result"],
    "remaining_count": 2
  }
}
```

The quota scope must match the account probe. A previously accepted request also
needs the matching ID and `terminal: true` on a definitive rejection. A different
request ID, timeout, or incomplete evidence leads to source reconciliation.
Definitive non-quota refusals can return `failed` with a rejected request and
its evidence.

## Destination handoff

The host passes `handoff` a packet containing the original operation/params,
source profile/account/receipt, checkpoint, local artifact directory, remaining
work, and destination profile/account. It checks declared `remaining.files`
before calling the destination preparation.

Create or resume the destination's own project/chat, upload the local files, and
bind its references. Return `{"status": "ok", "params": {...}}` with the
destination's native IDs and remaining work. Completed source outputs stay in
their local artifact paths. Preflight exhaustion and unavailable starting
profiles use this same destination preparation contract.

## Profile order and recovery

Candidates come from fresh Chrome metadata in natural directory order. Configure
preferred order in plugin settings when needed.

```yaml
rolling_profiles:
  my-site: [Default, Profile 2, Profile 1]
```

Other current profiles follow that preferred order. The selected starting profile
sets the initial cycle. A conversation/alias remembers its current working
profile between turns and continues there until quota is exhausted. A changed
profile policy takes precedence over that saved cursor. After a full exhausted
round, resumption checks availability again from the original cycle beginning.
Exhausted results include account/scope evidence and reset information supplied
by the package. The agent can resume when availability changes.

```json
{"action": "run", "app": "my-site", "operation": "generate", "session": "work", "params": {"prompt": "..."}}
{"action": "describe", "app": "my-site"}
{"action": "run", "app": "my-site", "operation": "generate", "session": "work", "job": "returned-host-job-id"}
```

`describe` lists recoverable jobs belonging to the calling conversation. Resume
uses the saved operation parameters and owning alias. Repeating the same pending
intent continues its existing job. Additional aliases support other work while
the original result is observed on its source account. Finished jobs return
their recorded result with `cached: true`.

The journal is written before submission. After an interruption, `resume` first
verifies the source profile identity and service account, then inspects the
recorded provider request. A read-only operation can return `ok` with
`request.state: "not_submitted"` and evidence. During reconciliation, proven
absence of a submission permits one continuation through `run`. Reconciliation
of interrupted handoff also returns prepared destination `params`.

Jobs, quota evidence and cursors live under plugin data, independently of package
source. A filesystem lease serializes one conversation/alias across processes.
Stop, disable and unload release the owned browser connection. The saved source
receipt remains available for explicit continuation after restart. Native browser
sessions follow the serving Hermes process's lifecycle.

## Verification

`tests/test_rolling.py` covers scripted provider outcomes, inventory changes,
deduplication, quota recovery, partial results, missing files, concurrent admission,
and a process exiting immediately after acceptance. `tests/live_rolling.py` uses
native Hermes tools, real Chrome profiles, CDP UI clicks and a local HTTP fixture.
The fixture counts submissions and checks source recovery alongside ordinary
browsing, another extension and manual targets. It produces local test artifacts.
