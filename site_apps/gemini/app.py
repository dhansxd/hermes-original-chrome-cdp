"""Use Gemini Web through the caller's existing Hermes browser context."""

import hashlib
import json
import re
from pathlib import Path

from . import controls, reply


ORIGIN = 'https://gemini.google.com'
_SNAPSHOT = (Path(__file__).parent / 'snapshot.js').read_text(encoding='utf-8')
SNAPSHOT = f'(origin) => ({_SNAPSHOT})(origin, {json.dumps(controls.SELECTORS)})'
RESULT_MARKER = 'GEMINI_INSPECT='
CHAT_PATH = r'/(?:u/\d+/)?app/([a-zA-Z0-9-]+)/?'


def chat_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:c_)?[a-zA-Z0-9-]+', value):
        raise ValueError('Gemini chat must be a conversation ID.')
    return 'c_' + value.removeprefix('c_')


def navigation(chat, *, fresh=False):
    return f'''import re
origin = {ORIGIN!r}
chat = {chat!r}
route = js("({{origin: location.origin, path: location.pathname}})")
base = re.match(r'^/(?:u/\\d+/)?app(?=/|$)', route['path']) if route['origin'] == origin else None
home = base[0] if base else '/app'
if chat:
    opened = re.fullmatch({CHAT_PATH!r}, route['path'])
    if route['origin'] != origin or not opened or 'c_' + opened[1] != chat:
        goto_url(origin + home + '/' + chat[2:])
elif not base or ({fresh!r} and route['path'].rstrip('/') != home):
    goto_url(origin + home)
'''


def run(context, operation, params):
    if operation == 'open_chat':
        if set(params) - {'chat'}:
            raise ValueError('Gemini open_chat accepts only an optional chat ID.')
        chat = chat_id(params['chat']) if 'chat' in params else None
        return controls.execute(context, ORIGIN, operation, chat, navigation=navigation(chat))
    if operation in {'click', 'type_prompt', 'select_model'}:
        field = {'click': 'control', 'type_prompt': 'text', 'select_model': 'model'}[operation]
        value = params.get(field)
        if set(params) != {field} or not isinstance(value, str) or not value.strip():
            raise ValueError(f'Gemini {operation} requires a nonempty {field}.')
        if operation == 'click' and value not in controls.CLICKABLE:
            return {'status': 'needs_inspection', 'data': {'reason': 'unmapped_control'},
                    'message': 'Use this browser session to locate the requested control.'}
        return controls.execute(context, ORIGIN, operation, value.strip())
    if operation == 'read_result':
        if params:
            raise ValueError('Gemini read_result takes no parameters.')
        return controls.execute(context, ORIGIN, operation)
    if operation == 'reply':
        if 'continuation' in params:
            return managed_reply(context, params)
        if set(params) != {'chat', 'prompt', 'request_id'}:
            raise ValueError('Gemini reply requires chat, prompt, and request_id.')
        chat = chat_id(params['chat'])
        return reply.run(context, chat, params['prompt'], params['request_id'], navigation(chat), ORIGIN, SNAPSHOT)
    if operation != 'inspect' or set(params) - {'chat'}:
        raise ValueError('Gemini inspect accepts only an optional chat ID.')
    chat = chat_id(params['chat']) if 'chat' in params else None
    return inspect(context, chat)


def inspect(context, chat=None):
    code = navigation(chat) + f'''import hashlib, json, time
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


def continuation(params):
    if set(params) != {'chat', 'prompt', 'request_id', 'continuation'}:
        raise ValueError('Gemini continuation requires chat, prompt, request_id and continuation.')
    options = params['continuation']
    if (not isinstance(options, dict) or set(options) != {'model', 'checkpoint'}
            or any(not isinstance(options[key], str) or not options[key].strip() for key in options)):
        raise ValueError('Gemini continuation requires the selected model label and a nonempty portable checkpoint.')
    return options


def quota_scope(model):
    return 'reply:' + model.casefold()


def identify(context, operation, params):
    chat_id(params.get('chat'))
    options = continuation(params)
    reply.normalize_input(params['prompt'], params['request_id'])
    result = inspect(context)
    if result['status'] != 'ok':
        raise RuntimeError(result['message'])
    data = result['data']
    if data['page'] == 'signed_out':
        return {'available': False, 'evidence': 'Gemini shows its sign-in page.'}
    account = data['account'].get('id')
    if not account:
        raise RuntimeError('Gemini could not verify the active Google account.')
    context.gemini_account = account
    return {'account': {'id': account, 'evidence': 'Active account read back from Gemini.'},
            'quota': {'scope': quota_scope(options['model']), 'requires_fresh_evidence': True}}


def managed_reply(context, params, *, observe_only=False):
    options = continuation(params)
    chat = chat_id(params['chat']) if params['chat'] is not None else None
    value = reply.run(context, chat, params['prompt'], params['request_id'],
                      navigation(chat, fresh=chat is None), ORIGIN, SNAPSHOT,
                      expected={'account': context.gemini_account, 'model': options['model']},
                      observe_only=observe_only)
    if value['status'] == 'ok':
        data = value['data']
        # The UI verifies the turn against its baseline and does not expose a provider request ID.
        receipt = hashlib.sha256(json.dumps([context.gemini_account, data['chat_id'],
                                             data['request_id']]).encode()).hexdigest()
        return {**value, 'request': {'state': 'completed', 'id': receipt}}
    if value['status'] == 'quota_exhausted':
        return {**value, 'request': {'state': 'rejected'},
                'quota': {**value['notice'], 'scope': quota_scope(options['model']), 'exhausted': True},
                'handoff': {'source_chat': chat}}
    if value['status'] == 'failed' and 'request' not in value:
        return {**value, 'request': {'state': 'rejected', 'evidence': 'Gemini did not confirm a send.'}}
    return value


def handoff(context, packet):
    params = packet['params']
    options = continuation(params)
    prompt = ('Continue the task using the following user-provided checkpoint as prior context.\n\n'
              f"Checkpoint:\n{options['checkpoint']}\n\nCurrent request:\n{params['prompt']}")
    return {'status': 'ok', 'params': {**params, 'chat': None, 'prompt': prompt},
            'request': {'state': 'not_submitted', 'evidence': 'Only destination text was prepared.'}}


def resume(context, record):
    if record['phase'] == 'handoff':
        return handoff(context, record['handoff'])
    return managed_reply(context, record['current_params'], observe_only=True)
