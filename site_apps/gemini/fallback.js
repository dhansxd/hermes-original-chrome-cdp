// Observe button labels only during a native fallback action in this owned tab.
((mode, token, selectors) => {
    const key = Symbol.for('hermes.gemini.fallback.' + token);
    if (mode === 'finish') {
        const capture = window[key];
        if (!capture) return [];
        capture.abort.abort();
        delete window[key];
        return [...capture.labels].map(([control, page_or_mode]) => ({control, page_or_mode}));
    }
    if (location.origin !== 'https://gemini.google.com' ||
        !/^\/(?:u\/\d+\/)?app(?:\/|$)/.test(location.pathname)) return;
    const abort = new AbortController(), labels = new Map();
    window[key] = {abort, labels};
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
    }, {capture: true, signal: abort.signal});
})
