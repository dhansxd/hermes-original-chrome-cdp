// Observe an owned fallback action and preserve any pending research submission.
((mode, token, selectors, protectSend = false) => {
    const key = Symbol.for('hermes.gemini.fallback.' + token);
    if (mode === 'finish') {
        const capture = window[key];
        if (!capture) return [];
        capture.abort.abort();
        delete window[key];
        const findings = [...capture.labels].map(([control, page_or_mode]) => ({control, page_or_mode}));
        return {findings, send_blocked: capture.sendBlocked};
    }
    if (location.origin !== 'https://gemini.google.com' ||
        !/^\/(?:u\/\d+\/)?app(?:\/|$)/.test(location.pathname)) return;
    const abort = new AbortController(), labels = new Map();
    const capture = window[key] = {abort, labels, sendBlocked: false};
    const options = {capture: true, signal: abort.signal};
    if (protectSend) {
        const blockSend = event => {
            capture.sendBlocked = true;
            event.preventDefault();
            event.stopImmediatePropagation();
        };
        window.addEventListener('click', event => {
            if (event.composedPath().some(node => node.matches?.(selectors.send))) blockSend(event);
        }, options);
        window.addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing &&
                event.target.closest?.(selectors.composer)) blockSend(event);
        }, options);
        window.addEventListener('submit', event => {
            if (event.target.querySelector?.(selectors.composer)) blockSend(event);
        }, options);
    }
    document.addEventListener('click', e => {
        const button = e.target.closest?.('button,[role="button"]');
        if (!button || button.closest('conversations-list,nav,aside,[contenteditable="true"]')) return;
        if (Object.values(selectors).some(s => button.matches(s) || button.closest(s))) return;
        if (button.closest('gem-menu-item[data-mode-id],[role="listbox"],[role="menuitemradio"]')) return;
        const label = (button.getAttribute('aria-label') || button.getAttribute('title') || '').trim();
        if (!label || label.length > 120 || /@|https?:\/\//i.test(label)) return;
        const mapped = ['Start research', 'Mulai riset', 'Mulai penelitian', 'Open report', 'Buka laporan',
                        'View report', 'Lihat laporan', 'More tools', 'Alat lainnya'];
        if (mapped.some(s => s === label || s === button.innerText.trim())) return;
        if (button.closest('generated-video') && /^(download|unduh) video$/i.test(label)) return;
        labels.set(label, button.closest('generated-video') ? 'Gemini video response' : 'Gemini conversation');
    }, options);
})
