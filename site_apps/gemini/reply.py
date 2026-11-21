"""Send and reconcile a text follow-up in an existing Gemini Web conversation."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


REPLY_UI = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
MARKER = 'GEMINI_REPLY='
RESPONSE_WAIT = 45

NATIVE = r'''
import hashlib, json, re, time

def read(control=None):
    args = [json.dumps(origin), json.dumps(chat), '(' + snapshot + ')', json.dumps(control)]
    return js('(' + ui + ')(' + ','.join(args) + ')')

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

def account(state):
    email = state.get('email')
    return digest(email) if email else None

def anchor(turn):
    if turn and turn['prompt'] is not None and turn['answer']:
        return digest([turn['prompt'], turn['answer']])
    return None

def original(state):
    route_matches = (state.get('chat_id') == chat if chat else state.get('document') == baseline['document'])
    return route_matches and account(state) == baseline['account']

def unchanged(state):
    return (original(state) and state.get('chat_id') == chat and state['document'] == baseline['document']
            and state['users'] == state['answers'] == baseline['turns']
            and anchor(state['latest']) == baseline['anchor']
            and (baseline['model'] is None or state['model'] == baseline['model'])
            and not state['busy'] and not state['media'])

def ready():
    deadline = time.monotonic() + 12
    while True:
        state = read('editor')
        if state.get('editor') and state.get('chat_id') == chat:
            return {'status': 'not_submitted', 'message': 'Gemini already has an unsent draft.'}
        if expected and state.get('email') and (hashlib.sha256(state['email'].encode()).hexdigest()
                != expected['account'] or (state.get('model') and state['model'] != expected['model'])):
            return {'status': 'not_submitted', 'message': 'The Gemini account or selected model differs from the requested continuation.'}
        previous = anchor(state.get('latest'))
        anchored = (previous and state['latest']['finished']) if chat else state.get('users') == 0
        if (state.get('chat_id') == chat and state.get('point') and account(state) and state['editor'] == ''
                and not state['busy'] and not state['media'] and state['users'] == state['answers']
                and anchored and (not expected or state['model'] == expected['model'])):
            return {'status': 'ready', 'baseline': {
                'account': account(state), 'document': state['document'], 'anchor': previous,
                'turns': state['users'], 'model': state['model']}}
        if time.monotonic() >= deadline:
            return {'status': 'not_submitted',
                    'message': 'Gemini did not show a ready text composer and completed source turn.'}
        time.sleep(.25)

def quota_refusal(state):
    if not expected or not state.get('send_disabled') or state['editor'] != prompt:
        return None
    model = re.escape(expected['model'])
    prefix = r"you(?:['’]ve| have) reached your "
    pattern = (prefix + rf'(?:limit (?:on|for) {model}|{model} (?:usage )?limit)'
               + rf'|anda (?:telah|sudah) mencapai batas (?:penggunaan )?(?:model )?{model}')
    for notice in state.get('quota', {}).get('notices', []):
        if re.match(rf'^(?:{pattern})(?=$|[\s.,!])', notice['evidence'], re.IGNORECASE):
            return notice
    return None

def send():
    state = read('editor')
    if not unchanged(state) or state['editor'] != '' or not state['point']:
        return {'status': 'not_submitted', 'message': 'The original Gemini chat or composer changed before typing.'}
    click_at_xy(*state['point'])
    state = read()
    if not unchanged(state) or state['editor'] != '' or not state['focused']:
        return {'status': 'not_submitted', 'message': 'Gemini did not focus the original empty composer.'}
    type_text(prompt)
    deadline = time.monotonic() + 5
    while True:
        state = read('send')
        if not unchanged(state):
            break
        if state['point'] and state['editor'] == prompt:
            click_at_xy(*state['point'])
            return observe()
        notice = quota_refusal(state)
        if notice:
            return {'status': 'quota_exhausted', 'notice': notice}
        if time.monotonic() >= deadline:
            break
        time.sleep(.15)
    return {'status': 'not_submitted', 'message': 'Gemini did not confirm the draft and Send control.'}

def observe():
    deadline = time.monotonic() + response_wait
    while True:
        state = read()
        if state.get('chat_id') and not original(state):
            break
        if original(state) and state.get('chat_id'):
            latest = state['latest']
            if (state['users'] == state['answers'] == baseline['turns'] + 1
                    and latest and latest['prompt'] == prompt and latest['answer']
                    and anchor(state['previous']) == baseline['anchor']
                    and latest['finished'] and not state['busy'] and state['editor'] == ''):
                answer = latest['answer']
                truncated = False
                # Keep the result inside the native browser output and redaction boundary.
                while len(json.dumps(answer, ensure_ascii=False)) > 16_000:
                    answer = answer[:len(answer) // 2]
                    truncated = True
                return {'status': 'ok', 'answer': answer, 'model': baseline['model'], 'chat_id': state['chat_id'],
                        'answer_truncated': truncated}
        if time.monotonic() >= deadline:
            break
        time.sleep(.5)
    return {'status': 'needs_inspection',
            'message': 'The reply is unconfirmed. Inspect this request on the original profile.'}

outcome = {'ready': ready, 'send': send, 'observe': observe}[action]()
print(marker + json.dumps(outcome, ensure_ascii=False))
'''


def _digest(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _save(path, journal):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(journal, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _native(context, script, action, baseline=None, navigation=''):
    source = navigation + script + f'\naction = {action!r}\nbaseline = {baseline!r}\n' + NATIVE
    try:
        result = context.browser_exec(source, timeout_s=RESPONSE_WAIT + 30)
        if result.get('success') and not result.get('exit_code', 0):
            lines = [line[len(MARKER):] for line in result.get('output', '').split('\n')
                     if line.startswith(MARKER)]
            if len(lines) == 1:
                value = json.loads(lines[0])
                if isinstance(value, dict):
                    return value
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def _pre_send_failure(path, journal, key, receipt, data, outcome, *, destination):
    result = {'status': 'failed', 'data': data, 'message': outcome['message']}
    if destination:
        result['request'] = {'state': 'not_submitted', 'evidence': outcome['message']}
        journal[key] = {**receipt, 'result': result}
        _save(path, journal)
    elif key in journal:
        del journal[key]
        _save(path, journal)
    return result


def _reply(context, path, key, request_id, chat, prompt, script, navigation, *, expected, observe_only):
    journal = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    receipt = journal.get(key)
    profile = context.profile
    prompt_hash = _digest(prompt)
    data = {'chat_id': chat, 'request_id': request_id}
    if receipt:
        if (receipt['profile'] != profile or receipt['prompt_hash'] != prompt_hash
                or (expected and receipt.get('expected') not in (None, expected))):
            return {'status': 'failed', 'data': data,
                    'message': 'Use the original Chrome profile, account, model and prompt to reconcile this request.'}
        result = receipt.get('result')
        if result:
            if (result['status'] == 'quota_exhausted' and context.job_id
                    and receipt.get('job') != context.job_id):
                return {'status': 'failed', 'data': data,
                        'message': 'Resume the original site operation job for this quota refusal.'}
            if observe_only or result.get('request', {}).get('state') != 'not_submitted':
                return {**result, 'cached': True}
            receipt = None
    action = 'observe'
    if not receipt:
        if observe_only:
            return {'status': 'needs_inspection', 'data': data,
                    'message': 'Gemini has no saved send receipt to reconcile. The request was not repeated.'}
        if any(not item.get('result') for item in journal.values()):
            return {'status': 'failed', 'data': data,
                    'message': 'This chat has an unresolved reply. Reconcile the original request first.'}
        receipt = {'profile': profile, 'prompt_hash': prompt_hash, 'job': context.job_id, 'expected': expected}
        prepared = _native(context, script, 'ready', navigation=navigation)
        if prepared and prepared['status'] == 'not_submitted':
            return _pre_send_failure(path, journal, key, receipt, data, prepared, destination=chat is None)
        if not prepared or prepared['status'] != 'ready':
            return {'status': 'failed', 'data': data, 'message':
                    (prepared or {}).get('message', 'The original Gemini chat could not be prepared.')}
        receipt['baseline'] = prepared['baseline']
        journal[key] = receipt
        _save(path, journal)
        action = 'send'

    outcome = _native(context, script, action, receipt['baseline'],
                      navigation=navigation if action == 'observe' else '')
    if outcome and outcome['status'] == 'ok':
        data.update(answer=outcome['answer'], model=outcome['model'], chat_id=outcome['chat_id'])
        if outcome['answer_truncated']:
            data['answer_truncated'] = True
        receipt['result'] = {'status': 'ok', 'data': data}
        _save(path, journal)
        return receipt['result']
    if outcome and outcome['status'] == 'quota_exhausted' and action == 'send':
        receipt['result'] = {'status': 'quota_exhausted', 'notice': outcome['notice'], 'data': data}
        _save(path, journal)
        return receipt['result']
    if outcome and outcome['status'] == 'not_submitted' and action == 'send':
        return _pre_send_failure(path, journal, key, receipt, data, outcome, destination=chat is None)
    return {'status': 'needs_inspection', 'data': data,
            'message': 'Gemini reply is unconfirmed. Repeat this request ID on its original profile to observe it.'}


def normalize_input(prompt, request_id):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Gemini reply requires a nonempty text prompt.')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_id):
        raise ValueError('Use a stable request_id containing 1–80 letters, digits, underscores or hyphens.')
    return prompt.replace('\r\n', '\n').replace('\r', '\n').strip()


def run(context, chat, prompt, request_id, navigation, origin, snapshot, *, expected=None, observe_only=False):
    if not context.session_id:
        raise ValueError('Gemini reply requires an owning Hermes conversation.')
    prompt = normalize_input(prompt, request_id)
    script = (f'origin = {origin!r}\nchat = {chat!r}\nprompt = {prompt!r}\n'
              f'ui = {REPLY_UI!r}\nsnapshot = {snapshot!r}\nmarker = {MARKER!r}\n'
              f'response_wait = {RESPONSE_WAIT!r}\nexpected = {expected!r}\n')
    identity = _digest(chat) if chat else _digest('destination', context.job_id, context.profile)
    root = context.directory.parent / 'reply-receipts' / identity
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'failed', 'message': 'A Gemini reply is already active on this chat.'}
        return _reply(context, root / 'journal.json', _digest(context.session_id, request_id),
                      request_id, chat, prompt, script, navigation if chat or not observe_only else '',
                      expected=expected, observe_only=observe_only)
