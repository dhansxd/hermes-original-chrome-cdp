# Contributor instructions

Read the [active browser contract and checklist](PLAN.md#1-status-dan-langkah-berikutnya)
before planning, changing, or testing anything in this repo. Use that contract
to interpret older docs, commits, and reference repos. Check the actual diff
and verification evidence before calling a checklist item complete.

## Browser tasks

- Expose one browser tool to Hermes for general browsing and mapped site
  controls. A site extension supplies ready-to-use UI controls inside that
  same browser task. It has no separate tool, browser session, or window
  lifecycle. Its site guide can document how to use those controls.
- Use one owned window in the original Chrome for the entire task. Reuse its
  CDP session for clicks, typing, progress checks, result collection and any
  requested delivery. Keep the other agents' and manual windows independent.
- Make the browser and relevant installed controls discoverable in a fresh
  Hermes session through the normal tool and skill catalogs. A request that
  only names the task must suffice. Keep routing independent of conversation
  memory, personal prompts, and user instructions about which tool to call.
- Treat pending work as progress. Verify the requested outcome and complete
  every requested step before the final answer. Close the task's owned browser
  resources at completion, and use the existing cleanup for Stop or failure.
- Use the mapped control directly when available. For an unmapped control,
  inspect the relevant DOM and use a screenshot as needed through the same
  browser tool and window. When this happens on a site with an extension,
  Hermes records the missing control for a later mapping update. Check the
  active mode and panel first, since a menu or banner can hide a mapped control.
- Keep Chrome in charge of profiles, login, and cookies. Drive the real UI
  through CDP and never copy or export cookies. Preserve the existing Chrome
  startup, profile selection, debugging consent, ownership and cleanup behavior.
- Follow the documented one-time Chrome Remote debugging setup. After that,
  exercise the plugin's native startup and consent path in tests for stopped
  Chrome, Chrome without windows, and Chrome with existing windows.
- Use OpenCLI only as a reference for mapped UI controls on relevant websites.
  Browser architecture, session ownership and tool selection follow this repo.
- Treat examples as examples. Add only behavior the user requests. Read the
  repository history and existing site integrations before changing their
  contracts. Keep Hermes and 9Router core on their upstream code.
- Treat leaving a window available for the user's continued use as a later
  feature, after the current regressions are fixed and verified.

## Working in this repository

- Read HANDOFF.md for the historical reset-recovery handoff. Read the relevant
  README, tutorial, and site guides before changing their behavior.
- Read and apply the user's coding guidelines before modifying code.
- Make the smallest change that addresses an observed issue or requested feature.
- State material assumptions and concrete success criteria. Reuse existing code
  and keep planning and verification proportional to the change.
- Preserve native Hermes provider registration and browser execution behavior
  while consolidating the browser tool available to the model.
- Keep changes within this plugin. Preserve Hermes core and managed dependencies.
- Protect other agents' and manual Chrome targets during every test and cleanup.
- Keep credentials, browser state, personal identities, private media, and runtime
  logs out of commits. Scan staged changes before committing.
- Complete regression checks before publishing a change. Verify the remote SHA
  after an authorized push.
- Report failed tests and pushes accurately. Do not force-push unless the user
  explicitly authorizes the history replacement for the task.
- Work alone for this project. Keep browser verification free of content generation.
