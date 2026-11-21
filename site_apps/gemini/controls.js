(origin, selectors, kind, name, label) => {
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
    const turn = all('model-response').at(-1);
    const labels = {
        start_research: ['Start research', 'Mulai riset', 'Mulai penelitian'],
        open_research_report: ['Open report', 'View report', 'Buka laporan', 'Lihat laporan'],
    };
    const researchButtons = control => [...turn?.querySelectorAll('button, [role="button"]') || []]
        .filter(node => visible(node) && labels[control].some(text => matchesLabel(node, text)));
    const clicked = Symbol.for('hermes.gemini.researchActions');

    if (kind === 'result') {
        const pending = (stage, control) => ({reason: 'running', chat_id: chatId, stage, control});
        const reportButtons = researchButtons('open_research_report');
        const panelId = reportButtons.length === 1 && reportButtons[0].getAttribute('aria-controls');
        const panel = panelId && document.getElementById(panelId);
        const report = visible(panel) && panel.querySelector('article, [role="document"]');
        const reportText = visible(report) && report.innerText.trim();
        if (reportText) {
            return {reason: 'ready', chat_id: chatId, text: reportText.slice(0, 4000), truncated: reportText.length > 4000};
        }
        for (const control of ['open_research_report', 'start_research']) {
            const buttons = control === 'open_research_report' ? reportButtons : researchButtons(control);
            if (buttons.length > 1) return {reason: 'ambiguous'};
            if (buttons.length === 1 && !buttons[0].matches(':disabled, [aria-disabled="true"]')) {
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
        const body = turn?.querySelector('message-content, [data-test-id="response-content"]');
        const text = visible(body) ? body.innerText.trim() : '';
        return text ? {reason: 'ready', chat_id: chatId, text: text.slice(0, 4000), truncated: text.length > 4000} :
            {reason: 'missing'};
    }

    let nodes;
    if (Object.hasOwn(labels, name)) {
        nodes = researchButtons(name);
        if (turn?.[clicked]?.has(name)) return {reason: 'already_clicked'};
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
    if (node.closest(':disabled, [aria-disabled="true"]')) return {reason: 'disabled'};
    const box = node.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    if (!node.contains(document.elementFromPoint(x, y))) return {reason: 'obscured'};
    if (kind === 'activate_research' && Object.hasOwn(labels, name)) {
        (turn[clicked] ||= new Set()).add(name);
        node.click();
        return {reason: 'clicked'};
    }
    const state = {reason: 'ready', point: [x, y], expanded: node.getAttribute('aria-expanded') === 'true',
        document: performance.timeOrigin, chat_id: chatId};
    if (kind === 'more_tools') {
        state.focused = node.contains(document.activeElement);
    } else if (name === 'composer') {
        state.value = node.innerText.trim();
        state.focused = document.activeElement === node;
    }
    return state;
}
