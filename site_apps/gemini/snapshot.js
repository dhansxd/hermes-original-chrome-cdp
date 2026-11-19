(origin) => {
    const account = {status: 'unknown'};
    const result = {page: 'redirected', account, model: null, controls: {},
        quota: {status: 'unknown', notices: []}};
    if (location.origin !== origin) {
        if (location.origin === 'https://accounts.google.com') {
            result.page = 'signed_out';
            account.status = 'signed_out';
        }
        return result;
    }

    if (!/^\/(?:u\/\d+\/)?app(?:\/|$)/.test(location.pathname)) return result;

    const visible = (node) => node.getClientRects().length > 0 &&
        getComputedStyle(node).visibility === 'visible' && !node.closest('[aria-hidden="true"]');
    const all = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
    const clean = (value, limit = 100) => (value || '').replace(/\s+/g, ' ').trim().slice(0, limit);
    const labelContent = (node) => {
        const copy = node.cloneNode(true);
        copy.querySelectorAll('svg, mat-icon, [aria-hidden="true"]').forEach((child) => child.remove());
        return clean(copy.textContent);
    };
    const text = (node) => labelContent(node) || clean(node.getAttribute('aria-label')) || null;
    const modelLabel = (node) => {
        const aria = clean(node.getAttribute('aria-label'), Infinity);
        const current = aria.match(/(?:^|,\s*)(?:currently|saat ini)\s+(.+)$/i)?.[1];
        const label = current ? clean(current) : labelContent(node);
        return label && !/^(?:select|pilih) model$/i.test(label) ? label : null;
    };
    const control = (key, selector) => {
        const nodes = all(selector);
        if (nodes.length !== 1) {
            return {status: nodes.length ? 'ambiguous' : 'not_observed'};
        }
        const node = nodes[0];
        const disabled = node.matches(':disabled, [aria-disabled="true"]');
        const state = {status: disabled ? 'disabled' : 'visible'};
        if (key !== 'composer') state.label = key === 'model_picker' ? modelLabel(node) : text(node);
        return state;
    };

    const avatars = all('a[href*="accounts.google.com/SignOutOptions"], ' +
        '[aria-label^="Google Account:"], [aria-label^="Akun Google:"]');
    const emails = new Set(avatars.flatMap((node) => {
        const label = node.getAttribute('aria-label') || '';
        return (label.match(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi) || []).map((email) => email.toLowerCase());
    }));
    // Some variants present an avatar without a readable address.
    const activeEmail = window.WIZ_global_data?.oPEP7c;
    if (typeof activeEmail === 'string' && /^[\w.+-]+@[\w.-]+\.[a-z]{2,}$/i.test(activeEmail)) {
        emails.add(activeEmail.toLowerCase());
    }
    if (emails.size === 1) {
        account.status = 'identified';
        account.email = emails.values().next().value;
    } else if (emails.size > 1) {
        account.status = 'ambiguous';
    } else if (all('a[href*="accounts.google.com/ServiceLogin"], ' +
        'a[href*="accounts.google.com/v3/signin"]').length) {
        account.status = 'signed_out';
    }

    const known = {
        composer: '[role="textbox"][contenteditable="true"]',
        model_picker: '[data-test-id="bard-mode-menu-button"], ' +
            'button[aria-label^="Select model"], button[aria-label^="Pilih model"]',
        tools_menu: 'button[aria-haspopup="menu"]:has(mat-icon[fonticon="plus"]), ' +
            'button[aria-label="Tools"], button[aria-label="Alat"]',
        send: 'button[aria-label="Send message"], button[aria-label="Kirim pesan"]',
        create_image: 'gem-menu-item:has(mat-icon[fonticon="image_create"]), ' +
            '[aria-label="Create image"], [aria-label="Buat gambar"]',
        create_video: 'gem-menu-item:has(mat-icon[fonticon="movie"]), ' +
            '[aria-label="Create video"], [aria-label="Buat video"]',
        deep_research: 'gem-menu-item:has(mat-icon[fonticon="deep_research"]), [aria-label="Deep Research"]',
        create_music: 'gem-menu-item:has(mat-icon[fonticon="music"]), ' +
            '[aria-label="Create music"], [aria-label="Buat musik"]'
    };
    result.controls = Object.fromEntries(Object.entries(known)
        .map(([key, selector]) => [key, control(key, selector)]));
    result.model = result.controls.model_picker.label ?? null;

    // Limit notices are advisory. Read only the status UI, never chat responses or draft text.
    const noticeSelector = '[role="alert"], [role="status"], mat-snack-bar-container, [data-test-id*="limit-banner"]';
    const limitText = /\b(?:usage limit|quota|rate limit|limit (?:for|reached)|reached your.{0,40}limit|batas (?:penggunaan|pemakaian|harian)|kuota)\b/i;
    const resetText = /\b(?:resets? (?:at|on|in|tomorrow)|try again (?:at|after|in|tomorrow)|direset|diatur ulang|coba lagi (?:pada|setelah|besok))\b.*/i;
    const chat = 'model-response, user-query, [contenteditable="true"]';
    const notices = [...new Set(all(noticeSelector).filter((node) => !node.closest(chat) && !node.querySelector(chat))
        .map((node) => clean(node.innerText, 320))
        .filter((label) => limitText.test(label)))].slice(0, 3);
    result.quota = {status: notices.length ? 'notice_visible' : 'unknown',
        notices: notices.map((evidence) => ({evidence, reset_text: evidence.match(resetText)?.[0] || null}))};
    result.page = account.status === 'signed_out' ? 'signed_out' :
        result.controls.composer.status === 'visible' || result.controls.model_picker.status === 'visible' ? 'ready' : 'waiting';
    return result;
}
