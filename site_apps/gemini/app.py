"""Inspect Gemini Web through the caller's existing Hermes browser context."""

import json
from pathlib import Path


ORIGIN = 'https://gemini.google.com'
SNAPSHOT = (Path(__file__).parent / 'snapshot.js').read_text(encoding='utf-8')
RESULT_MARKER = 'GEMINI_INSPECT='


def run(context, operation, params):
    if operation != 'inspect' or params != {}:
        raise ValueError('Gemini inspect accepts no parameters.')

    code = f'''import hashlib, json, re, time
origin = {ORIGIN!r}
route = js("({{origin: location.origin, path: location.pathname}})")
if route['origin'] != origin or not re.match(r'^/(?:u/\\d+/)?app(?:/|$)', route['path']):
    goto_url(origin + '/app')

snapshot = {SNAPSHOT!r}
expression = '(' + snapshot + ')(' + json.dumps(origin) + ')'
deadline = time.monotonic() + 8
while True:
    state = js(expression)
    if state['page'] not in ('waiting', 'redirected') or time.monotonic() >= deadline:
        break
    time.sleep(0.25)

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
    return {'status': 'ok', 'data': data}
