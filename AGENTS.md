# Contributor instructions

Read the [active browser contract and checklist](PLAN.md#1-status-dan-langkah-berikutnya)
before planning, changing, or testing anything in this repo. Use that contract
to interpret older docs, commits, and reference repos. Check the actual diff
and verification evidence before calling a checklist item complete.

## Product scope

- The goal is general browsing in the user's installed Google Chrome over CDP
  through Hermes's native `browser_exec`. Reuse Hermes's CDP support. The plugin
  adds Chrome profile selection and task window ownership to that path.
- Site extensions add ready-to-use UI controls for repeated actions. Gemini
  and Google Flow are the first packages. A control acts on the current page
  through the same `browser_exec`. Any site Chrome can reach can use ordinary
  navigation, DOM, and screenshots regardless of its extension coverage.
- Check general browsing on a site without an extension. Judge each mapped
  control by what it does in the site UI. A site's service behavior or the
  completion of one example task does not define general browser acceptance.

## Browser tasks

- Hermes upstream owns all chat behavior, including ordinary messages sent
  during an active turn, message priority, slash commands, steering,
  interruption, model responses, and non-browser tools. The plugin supplies
  explicit browser controls and progress readers. It must not rewrite replies,
  insert automatic tool calls, or reroute terminal or native browser scripts
  to check progress.
- Keep `browser_exec` as the single browsing tool and retain its native DOM and
  screenshot operations in the task window. Keep `browser_app` out of the
  manifest and registry. Verify tool discovery and installed site controls in
  a fresh Hermes session.
- Execute site behavior only on explicit `site_control` calls. Leave native
  fallback clicks and results to Hermes. Use `record_missing_control` to report
  findings explicitly in the same owned session.
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
- During design discussions, update the active plan as requirements are clarified.
  Record explicit prohibitions and behavior the user rejects as constraints.
  Apply those constraints when reading the plan, guides and Git history before
  planning or editing. Correct or remove conflicting guidance at its source.
  Keep suggestions and examples out of the contract unless the user adopts
  them. Label historical behavior as such.
- Make the smallest change that addresses an observed issue or requested feature.
- State material assumptions and concrete success criteria. Reuse existing code
  and keep planning and verification proportional to the change.
- Preserve native Hermes provider registration and normal `browser_exec` calls.
  Limit changes for mapped controls to the site extension integration.
- Keep changes within this plugin. Preserve Hermes core and managed dependencies.
- Protect other agents' and manual Chrome targets during every test and cleanup.
- Keep credentials, browser state, personal identities, private media, and runtime
  logs out of commits. Scan staged changes before committing.
- Complete regression checks before publishing a change. Verify the remote SHA
  after an authorized push.
- Report failed tests and pushes accurately. Do not force-push unless the user
  explicitly authorizes the history replacement for the task.
- Work alone for this project. Keep browser verification free of content generation.
