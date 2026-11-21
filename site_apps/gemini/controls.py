"""Small Gemini UI actions on the Chrome page owned by this browser session."""

import json
from pathlib import Path


SELECTORS = {
    'composer': '[role="textbox"][contenteditable="true"]',
    'model_picker': '[data-test-id="bard-mode-menu-button"], '
                    'button[aria-label^="Select model"], button[aria-label^="Pilih model"]',
    'tools_menu': 'button[aria-haspopup="menu"]:has(mat-icon[fonticon="plus"]), '
                  'button[aria-label="Tools"], button[aria-label="Alat"], '
                  'button[aria-label="Upload and tools"], button[aria-label="Upload & alat"]',
    'send': 'button[aria-label="Send message"], button[aria-label="Kirim pesan"]',
    'create_image': 'gem-menu-item:has(mat-icon[fonticon="image_create"]), '
                    '[aria-label="Create image"], [aria-label="Buat gambar"]',
    'create_video': 'gem-menu-item:has(mat-icon[fonticon="movie"]), '
                    '[aria-label="Create video"], [aria-label="Buat video"]',
    'deep_research': 'gem-menu-item:has(mat-icon[fonticon="deep_research"]), [aria-label="Deep Research"]',
    'create_music': 'gem-menu-item:has(mat-icon[fonticon="music"]), '
                    '[aria-label="Create music"], [aria-label="Buat musik"]',
}
TOOL_ITEMS = {'create_image', 'create_video', 'deep_research', 'create_music'}
CLICKABLE = {'model_picker', 'tools_menu', 'send', 'download_video', 'start_research', 'open_research_report'} | TOOL_ITEMS
CONTROL_UI = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
MARKER = 'GEMINI_CONTROL='

NATIVE = r'''
import json, time


def read(kind, name=None, label=None):
    inputs = ','.join(json.dumps(value) for value in (origin, selectors, kind, name, label))
    return js('(' + ui + ')(' + inputs + ')')


def wait_for(kind, name=None, label=None, *, seconds=2):
    deadline = time.monotonic() + seconds
    while True:
        state = read(kind, name, label)
        if state['reason'] not in {'missing', 'outside_gemini'} or time.monotonic() >= deadline:
            return state
        time.sleep(.15)


def blocked(control, state):
    return {'status': 'needs_inspection', 'data': {'control': control, 'reason': state['reason']},
            'message': 'Inspect this browser session before continuing.'}


def click(state):
    click_at_xy(*state['point'])


def choose_tool(control):
    target = read('control', control)
    if target['reason'] != 'missing':
        return target
    menu = read('control', 'tools_menu')
    if menu['reason'] == 'ready' and not menu['expanded']:
        click(menu)
        target = wait_for('control', control)
    if target['reason'] == 'missing':
        more = read('more_tools')
        if more['reason'] == 'ready' and not more['expanded']:
            click(more)
            target = wait_for('control', control, seconds=.35)
            if target['reason'] != 'missing':
                return target
            focused = read('more_tools')
            if (focused['reason'] == 'ready' and focused['focused'] and not focused['expanded']
                    and focused['document'] == more['document'] and focused['chat_id'] == more['chat_id']):
                press_key('ArrowRight')
            target = wait_for('control', control)
    return target


def run():
    if op == 'open_chat':
        page = wait_for('page', label=argument, seconds=6)
        if page['reason'] != 'ready':
            return blocked('chat', page)
        return {'status': 'ok', 'data': {'chat_id': page['chat_id']}}
    if op == 'read_result':
        state = read('result')
        if state['reason'] == 'running':
            data = {'chat_id': state['chat_id']}
            if state.get('stage'):
                data['stage'] = state['stage']
            result = {'status': 'running', 'data': data}
            if state.get('control'):
                result['next_control'] = {'app': 'gemini', 'operation': 'click',
                                          'params': {'control': state['control']}}
            return result
        if state['reason'] != 'ready':
            return blocked('result', state)
        return {'status': 'ok', 'data': {key: state[key] for key in ('chat_id', 'text', 'truncated')}}
    if op == 'type_prompt':
        state = wait_for('control', 'composer')
        if state['reason'] != 'ready':
            return blocked('composer', state)
        if state['value'] == argument:
            return {'status': 'ok', 'data': {'control': 'composer', 'typed': True}}
        if state['value']:
            return blocked('composer', {'reason': 'existing_draft'})
        click(state)
        focused = read('control', 'composer')
        if (focused['reason'] != 'ready' or not focused['focused'] or focused['value']
                or focused['document'] != state['document'] or focused['chat_id'] != state['chat_id']):
            return blocked('composer', {'reason': 'composer_changed'})
        type_text(argument)
        after = read('control', 'composer')
        if (after.get('value') != argument or after.get('document') != state['document']
                or after.get('chat_id') != state['chat_id']):
            return blocked('composer', {'reason': 'typing_unconfirmed'})
        return {'status': 'ok', 'data': {'control': 'composer', 'typed': True}}
    if op == 'select_model':
        choice = read('model', label=argument)
        if choice['reason'] == 'missing':
            picker = read('control', 'model_picker')
            if picker['reason'] != 'ready':
                return blocked('model_picker', picker)
            if not picker['expanded']:
                click(picker)
            choice = wait_for('model', label=argument)
        if choice['reason'] != 'ready':
            return blocked('model_picker', choice)
        click(choice)
        return {'status': 'ok', 'data': {'control': 'model_picker', 'clicked': True}}
    if argument in {'start_research', 'open_research_report'}:
        state = read('activate_research', argument)
        if state['reason'] in {'clicked', 'already_clicked'}:
            return {'status': 'running', 'data': {'control': argument, 'clicked': state['reason'] == 'clicked'}}
        return blocked(argument, state)
    state = choose_tool(argument) if argument in tool_items else wait_for('control', argument)
    if state['reason'] != 'ready':
        return blocked(argument, state)
    click(state)
    return {'status': 'running' if argument == 'send' else 'ok',
            'data': {'control': argument, 'clicked': True}}


print(marker + json.dumps(run(), ensure_ascii=False))
'''


def execute(context, origin, operation, argument=None, *, navigation=''):
    values = {
        'origin': origin, 'selectors': SELECTORS, 'ui': CONTROL_UI, 'op': operation,
        'argument': argument, 'tool_items': sorted(TOOL_ITEMS), 'marker': MARKER,
    }
    code = navigation + ''.join(f'{key} = {value!r}\n' for key, value in values.items()) + NATIVE
    result = context.browser_exec(code, timeout_s=25)
    if result.get('success') and not result.get('exit_code', 0):
        lines = [line[len(MARKER):] for line in result.get('output', '').splitlines()
                 if line.startswith(MARKER)]
        if len(lines) == 1:
            try:
                value = json.loads(lines[0])
            except ValueError:
                value = None
            if isinstance(value, dict):
                return value
    return {'status': 'needs_inspection', 'data': {'reason': 'action_unconfirmed'},
            'message': 'Inspect this browser session before repeating the action.'}
