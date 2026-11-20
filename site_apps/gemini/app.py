"""Inspect Gemini Web through the caller's existing Hermes browser context."""

import json
import re
from pathlib import Path


ORIGIN = 'https://gemini.google.com'
SNAPSHOT = (Path(__file__).parent / 'snapshot.js').read_text(encoding='utf-8')
RESULT_MARKER = 'GEMINI_INSPECT='
CHAT_PATH = r'/(?:u/\d+/)?app/([a-zA-Z0-9-]+)/?'


def run(context, operation, params):
    if operation != 'inspect' or set(params) - {'chat'}:
        raise ValueError('Gemini inspect accepts only an optional chat ID.')
    chat = params.get('chat')
    if 'chat' in params:
        if not isinstance(chat, str) or not re.fullmatch(r'(?:c_)?[a-zA-Z0-9-]+', chat):
            raise ValueError('Gemini chat must be a conversation ID.')
        chat = 'c_' + chat.removeprefix('c_')

    code = f'''import hashlib, json, re, time
origin = {ORIGIN!r}
chat = {chat!r}
route = js("({{origin: location.origin, path: location.pathname}})")
if chat:
    opened = re.fullmatch({CHAT_PATH!r}, route['path'])
    if route['origin'] != origin or not opened or 'c_' + opened[1] != chat:
        goto_url(origin + '/app/' + chat[2:])
elif route['origin'] != origin or not re.match(r'^/(?:u/\\d+/)?app(?:/|$)', route['path']):
    goto_url(origin + '/app')

snapshot = {SNAPSHOT!r}
expression = '(' + snapshot + ')(' + json.dumps(origin) + ')'
deadline = time.monotonic() + 8
while True:
    state = js(expression)
    # Gemini can render the composer before the model picker has a readable label.
    if state['page'] == 'signed_out':
        break
    if state['page'] == 'ready' and state['model'] and (not chat or state['chat_id'] == chat):
        break
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        break
    time.sleep(min(0.25, remaining))

account = state['account']
email = account.pop('email', None)
if email:
    user, domain = email.rsplit('@', 1)
    account.update(id=hashlib.sha256(email.encode()).hexdigest(), hint=user[0] + '…@' + domain)
print({RESULT_MARKER!r} + json.dumps(state, ensure_ascii=False))
'''
    result = context.browser_exec(code, timeout_s=35)
    if not result.get('success') or result.get('exit_code', 0):
        return {'status': 'failed', 'message': 'The selected browser session could not inspect Gemini Web.'}
    lines = [line[len(RESULT_MARKER):] for line in result.get('output', '').splitlines()
             if line.startswith(RESULT_MARKER)]
    if len(lines) != 1:
        return {'status': 'failed', 'message': 'Gemini returned no unambiguous inspection snapshot.'}
    try:
        data = json.loads(lines[0])
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {'status': 'failed', 'message': 'Gemini returned an invalid inspection snapshot.'}
    if chat and (data.get('chat_id') != chat or data.get('page') != 'ready'):
        return {'status': 'failed', 'data': data,
                'message': 'The requested Gemini chat could not be confirmed in the selected Chrome profile.'}
    return {'status': 'ok', 'data': data}
