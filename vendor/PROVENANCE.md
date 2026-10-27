# Browser helper snapshot

Source: https://github.com/browser-use/browser-harness (MIT, Copyright 2026 Browser Use).
Installed distribution: browser-harness 0.1.13. Snapshot of installed files, not an assumed tag/commit.
- helpers.py upstream SHA256: `5ea8560a01b74281833923720ffd23ca8e4f6b873c2419c821f7695a04091cf3`
- recorder.py upstream SHA256: `ccf987870ab88cff7dbefe586165eaac122bba53dc73813e8202d65c840814e8`

`helpers.py` preserves helper algorithms and their constants. Excluded upstream startup/env loading, daemon IPC, tab recovery/creation/switch implementations and agent-helper auto-import: the existing plugin worker owns those boundaries. Screenshot/debug files use the execution workspace. Recording start/stop/directory plus required internals are bound to that same workspace/transport instead of importing upstream unbound helpers. Automatic action recording was not integrated by the previous worker and is not added here.

Worker executes this local source in a fresh mapping; no live upstream function/global cloning or imports. Host helper updates do not silently change it. Review upstream fixes explicitly and exercise helper/Chrome regressions before updating. This snapshot does not expand iframe/target permissions or change existing BoundBrowser restrictions.
Internal profile preflight has no user workspace yet: domain-skill lookup skips only when AGENT_WORKSPACE is None. Normal execution injects its session workspace before custom helpers/user code.
