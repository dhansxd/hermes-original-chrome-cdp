# Contributor instructions

## Browser tasks

- Use one owned window in the original Chrome for the entire task. Reuse its
  CDP session for clicks, typing, progress checks, result collection and any
  requested delivery. Keep the other agents' and manual windows independent.
- Treat pending work as progress. Verify the requested outcome and complete
  every requested step before the final answer. Close the task's owned browser
  resources at completion, and use the existing cleanup for Stop or failure.
- Site extensions provide ready-to-use UI controls through the existing
  browser. When a control is missing, use native `browser_exec` in the same
  session, inspecting the relevant DOM first and using a screenshot as needed.
- Keep Chrome in charge of profiles and cookies. Preserve the existing Chrome
  startup, profile selection, debugging consent, ownership and cleanup behavior.
- Treat examples as examples. Add only behavior the user requests. Read the
  repository history and existing site integrations before changing their
  contracts. Keep Hermes and 9Router core on their upstream code.

## Working in this repository

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
