# Contributor instructions

- Read HANDOFF.md for the reset-recovery handoff and the current development pause.
- Read PLAN.md for the agreed scope and verification baseline.
- Read and apply the user's coding guidelines before modifying code.
- Make the smallest change that addresses an observed issue or requested feature.
- State material assumptions and concrete success criteria. Reuse existing code
  and keep planning and verification proportional to the change.
- Preserve native Hermes provider registration and browser_exec behavior.
- Keep changes within this plugin. Preserve Hermes core and managed dependencies.
- Protect other agents' and manual Chrome targets during every test and cleanup.
- Keep credentials, browser state, personal identities, private media, and runtime
  logs out of commits. Scan staged changes before committing.
- Complete regression checks before publishing a change. Verify the remote SHA
  after an authorized push.
- Report failed tests and pushes accurately. Do not force-push unless the user
  explicitly authorizes the history replacement for the task.
- Work alone for this project. Keep browser verification free of content generation.
