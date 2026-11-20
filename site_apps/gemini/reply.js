(origin, chat, snapshot, control) => {
    const page = snapshot(origin);
    if (page.chat_id !== chat || page.page === 'signed_out') return {chat_id: page.chat_id};

    const visible = node => node && node.getClientRects().length > 0 &&
        getComputedStyle(node).visibility === 'visible' && !node.closest('[aria-hidden="true"]');
    const matching = selector => Array.from(document.querySelectorAll(selector)).filter(visible);
    const editors = matching('[role="textbox"][contenteditable="true"]');
    const editor = editors.length === 1 ? editors[0] : null;
    const sends = matching('button[aria-label="Send message"],button[aria-label="Kirim pesan"]');
    const stop = matching('button[aria-label="Stop response"],button[aria-label="Hentikan respons"]');

    function point(node) {
        if (!node || node.matches(':disabled,[aria-disabled="true"]')) return null;
        const box = node.getBoundingClientRect();
        const x = box.left + box.width / 2;
        const y = box.top + box.height / 2;
        return node.contains(document.elementFromPoint(x, y)) ? [x, y] : null;
    }

    const users = Array.from(document.querySelectorAll('user-query'));
    const answers = Array.from(document.querySelectorAll('model-response'));
    const busy = stop.length > 0 || answers.at(-1)?.getAttribute('aria-busy') === 'true';
    function turn(offset) {
        const user = users.at(-offset);
        const answer = answers.at(-offset);
        if (!user || !answer || !(user.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING)) {
            return null;
        }
        const lines = Array.from(user.querySelectorAll('.query-text-line'));
        const body = answer.querySelector('message-content, [data-test-id="response-content"]');
        const finished = Array.from(answer.querySelectorAll(
            'button[aria-label="Copy response"],button[aria-label="Salin respons"],' +
            'button[aria-label="Good response"],button[aria-label="Respons bagus"],' +
            'button[data-test-id="copy-button"],button[data-test-id="good-response-button"]'
        )).some(button => visible(button) && !button.matches(':disabled,[aria-disabled="true"]'));
        return {
            prompt: lines.length ? lines.map(line => line.innerText).join('\n').trim() : null,
            answer: visible(body) ? body.innerText.trim() : null,
            finished
        };
    }

    return {
        chat_id: page.chat_id,
        email: page.account.status === 'identified' ? page.account.email : null,
        document: performance.timeOrigin,
        model: page.model,
        editor: editor?.innerText.trim() ?? null,
        focused: editor !== null && document.activeElement === editor,
        busy,
        media: matching('[data-test-id="deselect-drawer-item-gem-button"], ' +
                        '.attachment-preview-wrapper uploader-file-preview').length > 0,
        users: users.length,
        answers: answers.length,
        latest: turn(1),
        previous: turn(2),
        point: control === 'editor' ? point(editor) :
            control === 'send' && sends.length === 1 ? point(sends[0]) : null
    };
}
