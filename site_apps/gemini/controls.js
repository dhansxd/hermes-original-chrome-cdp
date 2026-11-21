(origin, selectors, kind, name, label, researchState = null) => {
    const chat = location.pathname.match(/^\/(?:u\/\d+\/)?app\/([a-zA-Z0-9-]+)\/?$/);
    const chatId = chat ? 'c_' + chat[1] : null;
    if (location.origin !== origin || !/^\/(?:u\/\d+\/)?app(?:\/|$)/.test(location.pathname)) {
        return {reason: location.origin === 'https://accounts.google.com' ? 'signed_out' : 'outside_gemini'};
    }

    const visible = (node) => node && node.getClientRects().length > 0 &&
        getComputedStyle(node).visibility === 'visible' && !node.closest('[aria-hidden="true"]');
    const all = (selector) => [...document.querySelectorAll(selector)].filter(visible);
    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
    const matchesLabel = (node, value) => {
        const copy = node.cloneNode(true);
        copy.querySelectorAll('svg, mat-icon, [aria-hidden="true"]').forEach((icon) => icon.remove());
        return clean(copy.textContent) === value || clean(node.getAttribute('aria-label')) === value;
    };

    if (kind === 'page') {
        return {reason: label && label !== chatId ? 'missing' : 'ready', chat_id: chatId};
    }
    const composer = () => all(selectors.composer);
    function researchActive() {
        const editors = composer();
        if (editors.length !== 1) return false;
        const area = editors[0].closest('fieldset, input-area-v2, input-area, form');
        return !!area && [...area.querySelectorAll('[data-test-id="deselect-drawer-item-gem-button"] button')]
            .some(b => visible(b) && (matchesLabel(b, 'Deep Research') ||
                /^(?:Deselect|Batalkan pilihan) Deep Research$/i.test(b.getAttribute('aria-label') || '')));
    }
    const submission = Symbol.for('hermes.gemini.researchSubmission');
    const current = window[submission];
    if (kind === 'research_mode') {
        return {reason: researchActive() ? 'ready' : 'missing', document: performance.timeOrigin,
            chat_id: chatId, same_submission: !!current && (!current.chat || current.chat === chatId)};
    }
    const labels = {
        start_research: ['Start research', 'Mulai riset', 'Mulai penelitian'],
        open_research_report: ['Open report', 'View report', 'Buka laporan', 'Lihat laporan'],
    };
    const unavailable = ':disabled, [aria-disabled="true"]';
    const pending = (stage, control) => ({reason: 'running', chat_id: chatId, stage, control});
    const clicked = Symbol.for('hermes.gemini.researchActions');
    let turn = all('model-response').at(-1);
    const researchButtons = (control, response = turn) =>
        [...response?.querySelectorAll('button, [role="button"]') || []]
            .filter(node => visible(node) && labels[control].some(text => matchesLabel(node, text)));
    const queryText = group =>
        clean([...group?.querySelectorAll('user-query .query-text-line') || []].map(node => node.innerText).join('\n'));
    const readsResearch = kind === 'result' || kind === 'activate_research';
    const bound = researchState === 'submitted' || (researchState === 'selected' && !!current);
    let planAccepted = false;
    if (readsResearch && bound) {
        if (!current || (current.chat && current.chat !== chatId)) return {reason: 'research_submission_unconfirmed'};
        const groups = [...document.querySelectorAll('.conversation-container[id]')].filter(g => g.querySelector('user-query'));
        if (!current.id) {
            const before = current.previous ? groups.findIndex(g => g.id === current.previous) : -1;
            if (current.previous && before < 0) return {reason: 'research_submission_unconfirmed'};
            const next = groups[before + 1];
            const text = queryText(next);
            if (text) {
                if (text !== current.prompt) return {reason: 'research_prompt_mismatch'};
                current.id = next.id;
                current.chat = chatId;
                delete current.prompt;
            }
        }
        const topicIndex = groups.findIndex(g => g.id === current.id);
        if (current.id && topicIndex < 0) return {reason: 'research_submission_unconfirmed'};
        turn = groups[topicIndex]?.querySelector('model-response');
        if (!current.confirmation) {
            const start = researchButtons('start_research');
            const submitted = current.started || (start.length === 1 && start[0].matches(unavailable));
            // Gemini inserts the confirmation as the next user turn after the plan.
            const next = groups[topicIndex + 1];
            if (submitted && next && labels.start_research.includes(queryText(next))) {
                current.confirmation = next.id;
            }
        }
        planAccepted = Boolean(current.started || current.confirmation);
        if (planAccepted && name === 'start_research' && kind === 'activate_research') {
            return {reason: 'already_clicked'};
        }
        if (current.confirmation) {
            turn = groups.find(group => group.id === current.confirmation)?.querySelector('model-response');
        }
        if (!turn) {
            if (!current.id && Date.now() - current.at > 15000) return {reason: 'research_submission_unconfirmed'};
            return pending(current.confirmation ? 'research_in_progress' : 'awaiting_response');
        }
    }
    const cardSelector = 'immersive-entry-chip gem-processing-card';
    const reportCards = current?.confirmation && bound
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
            return {reason: 'ready', chat_id: chatId, text: reportText.slice(0, 4000), truncated: reportText.length > 4000};
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
            return {reason: 'running', chat_id: chatId};
        }
        if (planAccepted) return pending('research_in_progress');
        if (visible(turn?.querySelector('deep-research-confirmation-widget'))) return {reason: 'research_plan_unconfirmed'};
        const body = turn?.querySelector('message-content, [data-test-id="response-content"]');
        const text = visible(body) ? body.innerText.trim() : '';
        if (text && bound && current) current.finished = true;
        return text ? {reason: 'ready', chat_id: chatId, text: text.slice(0, 4000), truncated: text.length > 4000} :
            {reason: 'missing'};
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
        return {reason: 'clicked'};
    }
    const state = {reason: 'ready', point: [x, y], expanded: node.getAttribute('aria-expanded') === 'true',
        document: performance.timeOrigin, chat_id: chatId};
    const activeResearch = name === 'send' && researchActive();
    if (name === 'send' && (researchState || activeResearch)) {
        if (!activeResearch) return {reason: 'deep_research_not_active'};
        if ((current && !current.finished && (!current.chat || current.chat === chatId)) ||
            (researchState === 'submitted' && !current)) {
            return {reason: 'research_submission_pending'};
        }
        const draft = clean(composer()[0].innerText);
        if (!draft) return {reason: 'research_draft_missing'};
        const prior = [...document.querySelectorAll('user-query')].at(-1);
        const previous = prior?.closest('.conversation-container[id]')?.id;
        if (prior && !previous) return {reason: 'research_turn_unconfirmed'};
        window[submission] = {chat: chatId, previous, prompt: draft, at: Date.now()};
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
