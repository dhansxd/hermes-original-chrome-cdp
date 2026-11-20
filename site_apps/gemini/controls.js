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
    if (kind === 'result') {
        const turn = all('model-response').at(-1);
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
    if (kind === 'model') {
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
