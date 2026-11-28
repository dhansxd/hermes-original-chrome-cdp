async (origin, selectors, kind, name, label, researchState = null, savedSubmission = null, dispatchSend = false, visualPoint = null) => {
    const route = location.pathname.match(/^(\/(?:u\/\d+\/)?app)(?:\/([a-zA-Z0-9-]+))?\/?$/);
    const chatId = route?.[2] ? 'c_' + route[2] : null;
    if (location.origin !== origin || !/^\/(?:u\/\d+\/)?app(?:\/|$)/.test(location.pathname)) {
        return {reason: location.origin === 'https://accounts.google.com' ? 'signed_out' : 'outside_gemini'};
    }

    const visible = (node) => node && node.getClientRects().length > 0 &&
        getComputedStyle(node).visibility === 'visible' && !node.closest('[aria-hidden="true"]');
    const all = (selector) => [...document.querySelectorAll(selector)].filter(visible);
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    const digest = async (text) => Array.from(
        new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))),
        byte => byte.toString(16).padStart(2, '0')).join('');
    const matchesLabel = (node, value) => {
        const copy = node.cloneNode(true);
        copy.querySelectorAll('svg, mat-icon, [aria-hidden="true"]').forEach((icon) => icon.remove());
        return clean(copy.textContent) === value || clean(node.getAttribute('aria-label')) === value;
    };

    const buttonSelector = 'button, [role="button"], input[type="button"], input[type="submit"]';
    const hasName = (node, names) => {
        const idRefs = clean(node.getAttribute('aria-labelledby')).split(' ').filter(Boolean);
        const labelled = clean(idRefs.map(id => document.getElementById(id)?.textContent ?? '').join(' '));
        return names.some(name => matchesLabel(node, name) || clean(node.getAttribute('title')) === name ||
            labelled === name || (node instanceof HTMLInputElement && clean(node.value) === name));
    };

    if (kind === 'page') {
        return {reason: label && label !== chatId ? 'missing' : 'ready', chat_id: chatId};
    }
    const composer = () => all(selectors.composer);
    const composerArea = editor => editor.closest('fieldset, input-area-v2, input-area, form');
    function researchActive() {
        const editors = composer();
        if (editors.length !== 1) return false;
        const area = composerArea(editors[0]);
        return !!area && [...area.querySelectorAll('[data-test-id="deselect-drawer-item-gem-button"] button')]
            .some(b => visible(b) && (matchesLabel(b, 'Deep Research') ||
                /^(?:Deselect|Batalkan pilihan) Deep Research$/i.test(b.getAttribute('aria-label') || '')));
    }
    const submission = Symbol.for('hermes.gemini.researchSubmission');
    let current = window[submission];
    const intent = savedSubmission?.prompt_hash ? savedSubmission : null;
    const onSourceRoute = intent && route?.[1] === intent.home && (!intent.chat || intent.chat === chatId);
    if (kind === 'research_mode') {
        return {reason: researchActive() ? 'ready' : 'missing', document: performance.timeOrigin,
            chat_id: chatId, same_submission: Boolean(onSourceRoute || current && current.chat === chatId ||
                chatId && savedSubmission?.chat === chatId)};
    }
    const labels = {
        start_research: ['Start research', 'Mulai riset', 'Mulai penelitian'],
        open_research_report: ['Open report', 'View report', 'Buka laporan', 'Lihat laporan'],
    };
    const unavailable = ':disabled, [aria-disabled="true"]';
    const clicked = Symbol.for('hermes.gemini.researchActions');
    const cardSelector = 'immersive-entry-chip gem-processing-card';
    let turn = all('model-response').at(-1);
    const researchButtons = (control, response = turn) => {
        const mapped = [...response?.querySelectorAll('button, [role="button"]') || []]
            .filter(node => visible(node) && labels[control].some(text => matchesLabel(node, text)));
        if (control !== 'start_research' || mapped.length) return mapped;
        return [...response?.querySelectorAll('deep-research-confirmation-widget') || []]
            .filter(visible).flatMap(panel => [...panel.querySelectorAll(buttonSelector)])
            .filter(node => visible(node) && hasName(node, labels[control]));
    };
    const queryText = group =>
        clean([...group?.querySelectorAll('user-query .query-text-line') || []].map(node => node.innerText).join('\n'));
    function submittedPlan(response) {
        const starts = researchButtons('start_research', response);
        if (starts.length !== 1 || !starts[0].matches(unavailable)) return '';
        const widget = starts[0].closest('deep-research-confirmation-widget');
        const title = widget?.querySelector('[data-test-id="title"]');
        return visible(title) && clean(title.innerText) ? clean(widget.innerText) : '';
    }
    const readsResearch = kind === 'result' || kind === 'activate_research';
    const bound = researchState === 'submitted' || (researchState === 'selected' && !!current);
    const withReceipt = result => {
        if (!bound || !current?.id || !current.chat || current.chat !== chatId) return result;
        const {chat, id, home, confirmation, started, finished} = current;
        return {...result, _research_receipt: {chat, id, home, confirmation, started, finished}};
    };
    const pending = (stage, control) => withReceipt({reason: 'running', chat_id: chatId, stage, control});
    let planAccepted = false;
    if (readsResearch && bound) {
        const groups = [...document.querySelectorAll('.conversation-container[id]')].filter(g => g.querySelector('user-query'));
        if (intent && !onSourceRoute) return {reason: 'research_submission_unconfirmed'};
        if (intent && (!current?.id || current.finished)) {
            const before = groups.findIndex(group => group.id === intent.previous);
            if (intent.previous && before < 0) return {reason: 'research_turn_not_visible'};
            const next = groups[before + 1];
            const text = queryText(next);
            if (!text || !chatId) return {reason: 'running', stage: 'awaiting_response', chat_id: chatId};
            if (await digest(text) !== intent.prompt_hash) return {reason: 'research_prompt_mismatch'};
            if (!next.isConnected || queryText(next) !== text || location.pathname !== route[0] ||
                groups.filter(group => group.id === next.id).length !== 1) {
                return {reason: 'research_turn_unconfirmed'};
            }
            current = window[submission] = {chat: chatId, home: route[1], id: next.id};
        }
        if (!current && chatId && savedSubmission?.chat === chatId && savedSubmission.id &&
            (!savedSubmission.home || savedSubmission.home === route?.[1])) {
            if (groups.filter(group => group.id === savedSubmission.id).length !== 1) {
                return {reason: 'research_turn_not_visible'};
            }
            current = window[submission] = {...savedSubmission};
        }
        if (!current?.id || current.chat !== chatId || (current.home && current.home !== route?.[1])) {
            return {reason: 'research_submission_unconfirmed'};
        }
        const topicIndex = groups.findIndex(g => g.id === current.id);
        if (topicIndex < 0) return {reason: 'research_turn_not_visible'};
        const topic = groups[topicIndex];
        turn = topic.querySelector('model-response');
        let confirmed = groups[topicIndex + 1];
        if (confirmed && queryText(topic) && queryText(confirmed) === queryText(topic)) {
            // A repeated prompt is only a copy of this plan when both widgets agree and
            // Gemini placed a research card immediately after the repeated plan.
            const plan = submittedPlan(turn);
            const afterCopy = groups[topicIndex + 2];
            if (plan && plan === submittedPlan(confirmed.querySelector('model-response')) &&
                labels.start_research.includes(queryText(afterCopy)) &&
                afterCopy.querySelector('model-response ' + cardSelector)) {
                confirmed = afterCopy;
            }
        }
        if (!current.confirmation) {
            const start = researchButtons('start_research');
            const submitted = current.started || (start.length === 1 && start[0].matches(unavailable));
            if (submitted && confirmed && labels.start_research.includes(queryText(confirmed))) {
                current.confirmation = confirmed.id;
            }
        }
        planAccepted = Boolean(current.started || current.confirmation);
        if (planAccepted && name === 'start_research' && kind === 'activate_research') {
            return withReceipt({reason: 'already_clicked'});
        }
        if (current.confirmation) {
            if (confirmed?.id !== current.confirmation || !labels.start_research.includes(queryText(confirmed))) {
                return {reason: 'research_turn_not_visible'};
            }
            turn = confirmed.querySelector('model-response');
        }
        if (!turn) {
            return pending(current.confirmation ? 'research_in_progress' : 'awaiting_response');
        }
    }
    const reportTurn = bound ? Boolean(current?.confirmation) :
        Boolean(chatId && labels.start_research.includes(queryText(turn?.closest('.conversation-container[id]'))));
    const reportCards = reportTurn
        ? [...turn?.querySelectorAll(cardSelector + '.completed') || []].filter(visible) : [];
    const reportButtons = [...researchButtons('open_research_report'), ...reportCards];

    if (kind === 'result') {
        const panelId = reportButtons.length === 1 && reportButtons[0].getAttribute('aria-controls');
        const panel = panelId && document.getElementById(panelId);
        let report = visible(panel) && panel.querySelector('article, [role="document"]');
        const selected = all(cardSelector + '.selected');
        const activeCard = reportButtons.length === 1 && selected.length === 1 && selected[0] === reportCards[0];
        if (activeCard) {
            // The report panel is outside the conversation turn and is shared by its cards.
            const panels = all('immersive-panel');
            const title = clean(selected[0].querySelector('.card-title')?.innerText);
            if (title && panels.length === 1 && title === clean(panels[0].querySelector('h2')?.innerText)) {
                report = panels[0].querySelector('#extended-response-markdown-content');
            }
        }
        const reportText = visible(report) && report.innerText.trim();
        if (reportText) {
            if (bound && current) current.finished = true;
            return withReceipt({reason: 'ready', stage: 'report_ready', chat_id: chatId, text: reportText.slice(0, 4000),
                truncated: reportText.length > 4000});
        }
        for (const control of ['open_research_report', 'start_research']) {
            const buttons = control === 'open_research_report' ? reportButtons : researchButtons(control);
            if (buttons.length > 1) return {reason: 'ambiguous'};
            if (buttons.length === 1 && !buttons[0].matches(unavailable)) {
                if (control === 'start_research' && planAccepted) continue;
                if (control === 'open_research_report' && activeCard) return pending('opening_report');
                if (turn[clicked]?.has(control)) {
                    return control === 'open_research_report' ? {reason: 'inspect_open_report'} : pending('research_in_progress');
                }
                return pending(control === 'start_research' ? 'plan_ready' : 'report_available', control);
            }
        }
        const indicators = [...turn?.querySelectorAll('thinking-overlay, [role="status"], [role="progressbar"]') || []]
            .filter(visible).map(node => clean(node.innerText || node.getAttribute('aria-label')));
        const planning = /membuat rencana (riset|penelitian)|creating (a |the |your )?research plan|planning (your |the )?research/i;
        const working = /sedang (melakukan riset|meneliti)|research in progress|researching/i;
        if (indicators.some(text => planning.test(text))) return pending('planning');
        if (indicators.some(text => working.test(text))) return pending('research_in_progress');
        if (all('button[aria-label="Stop response"], button[aria-label="Hentikan respons"]').length ||
            turn?.getAttribute('aria-busy') === 'true') {
            return pending();
        }
        if (planAccepted) return pending('research_in_progress');
        if (visible(turn?.querySelector('deep-research-confirmation-widget'))) return {reason: 'research_plan_unconfirmed'};
        const body = turn?.querySelector('message-content, [data-test-id="response-content"]');
        const text = visible(body) ? body.innerText.trim() : '';
        if (!text) return bound ? pending('awaiting_response') : {reason: 'missing'};
        if (bound) current.finished = true;
        return withReceipt({reason: bound ? 'research_no_plan' : 'ready', chat_id: chatId, text: text.slice(0, 4000),
            truncated: text.length > 4000});
    }

    const activeResearch = name === 'send' && researchActive();
    const guardedSend = name === 'send' && (researchState || activeResearch || dispatchSend);
    if (guardedSend) {
        if (!activeResearch) return {reason: 'deep_research_not_active'};
        const held = window[submission] || savedSubmission;
        if ((held && !held.finished && !(dispatchSend && held === intent)) ||
            (researchState === 'submitted' && !held)) {
            return {reason: 'research_submission_pending'};
        }
    }

    let nodes;
    if (Object.hasOwn(labels, name)) {
        nodes = name === 'open_research_report' ? reportButtons : researchButtons(name);
        if (turn?.[clicked]?.has(name)) return {reason: 'already_clicked'};
        if (name === 'open_research_report' && nodes.length === 1 && nodes[0].matches(cardSelector + '.selected')) {
            return {reason: 'already_clicked'};
        }
    } else if (kind === 'model') {
        nodes = all('gem-menu-item[data-mode-id], [role="menu"] [role="menuitemradio"], ' +
                    '[role="listbox"] [role="option"]').filter((node) => matchesLabel(node, label));
    } else if (kind === 'more_tools') {
        nodes = all('[role="menu"] button, [role="menu"] [role="menuitem"], gem-menu-item')
            .filter((node) => matchesLabel(node, 'More tools') || matchesLabel(node, 'Alat lainnya'));
    } else {
        nodes = all(selectors[name]);
        if (name === 'send' && (!nodes.length || visualPoint)) {
            const editors = composer();
            const area = editors.length === 1 && composerArea(editors[0]);
            if (!area || !clean(editors[0].innerText)) return {reason: 'send_composer_unconfirmed'};
            const sendNames = ['Send', 'Send message', 'Kirim', 'Kirim pesan'];
            nodes = [...area.querySelectorAll(buttonSelector)]
                .filter(node => visible(node) && (node.matches(selectors.send) || hasName(node, sendNames)));
        }
    }
    if (visualPoint && ['send', 'start_research'].includes(name)) {
        const viewport = window.visualViewport;
        const hit = document.elementFromPoint(visualPoint[0] + (viewport?.offsetLeft ?? 0),
                                              visualPoint[1] + (viewport?.offsetTop ?? 0));
        nodes = nodes.filter(node => node.contains(hit));
        if (nodes.length !== 1) return {reason: 'visual_target_mismatch'};
    }
    if (!nodes.length) return {reason: 'missing'};
    if (nodes.length !== 1) return {reason: 'ambiguous'};
    const node = nodes[0];
    if (node.closest(unavailable)) return {reason: 'disabled'};
    let box = node.getBoundingClientRect();
    if (kind === 'activate_research' && (box.top + box.height / 2 < 0 || box.top + box.height / 2 >= innerHeight)) {
        node.scrollIntoView({block: 'center', behavior: 'instant'});
        box = node.getBoundingClientRect();
    }
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    if (!node.contains(document.elementFromPoint(x, y))) return {reason: 'obscured'};
    if (kind === 'activate_research' && Object.hasOwn(labels, name)) {
        (turn[clicked] ||= new Set()).add(name);
        if (bound && name === 'start_research') current.started = true;
        node.click();
        return withReceipt({reason: 'clicked'});
    }
    const state = {reason: 'ready', point: [x, y], expanded: node.getAttribute('aria-expanded') === 'true',
        document: performance.timeOrigin, chat_id: chatId};
    if (guardedSend) {
        const editor = composer()[0];
        const draft = clean(editor.innerText);
        if (!draft) return {reason: 'research_draft_missing'};
        if (!route) return {reason: 'research_submission_unconfirmed'};
        const prior = [...document.querySelectorAll('user-query')].at(-1);
        const previous = prior?.closest('.conversation-container[id]')?.id || null;
        if (prior && !previous) return {reason: 'research_turn_unconfirmed'};
        const baseline = {chat: chatId, home: route[1], previous, document: state.document,
            prompt_hash: await digest(draft)};
        if (location.pathname !== route[0] || clean(editor.innerText) !== draft ||
            !researchActive() || !node.contains(document.elementFromPoint(x, y)) || node.closest(unavailable)) {
            return {reason: 'research_composer_changed'};
        }
        if (dispatchSend) {
            if (window[submission] && !window[submission].finished) return {reason: 'research_submission_pending'};
            if (!intent || Object.keys(baseline).some(key => baseline[key] !== intent[key])) {
                return {reason: 'research_composer_changed'};
            }
            window[submission] = baseline;
        } else {
            state._research_intent = baseline;
        }
        state.mode_active = true;
    }
    if (kind === 'more_tools') {
        state.focused = node.contains(document.activeElement);
    } else if (name === 'composer') {
        state.value = node.innerText.trim();
        state.focused = document.activeElement === node;
    }
    return state;
}
