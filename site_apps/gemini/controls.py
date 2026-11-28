"""Small Gemini UI actions on the Chrome page owned by this browser session."""

import fcntl
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
    'deep_research': 'gem-menu-item:has(mat-icon[fonticon="deep_research"]), '
                     'gem-menu-item[aria-label="Deep Research"], [role="menu"] [aria-label="Deep Research"]',
    'create_music': 'gem-menu-item:has(mat-icon[fonticon="music"]), '
                    '[aria-label="Create music"], [aria-label="Buat musik"]',
}
TOOL_ITEMS = {'create_image', 'create_video', 'deep_research', 'create_music'}
CLICKABLE = {'model_picker', 'tools_menu', 'send', 'download_video', 'start_research', 'open_research_report'} | TOOL_ITEMS
CONTROL_UI = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
MARKER = 'GEMINI_CONTROL='

NATIVE = r'''
import json, time

receipt = None


def read(kind, name=None, label=None):
    global receipt
    inputs = ','.join(json.dumps(value) for value in (
        origin, selectors, kind, name, label, research_state, saved_submission, dispatch_send, visual_point))
    state = js('(' + ui + ')(' + inputs + ')')
    if state.get('_research_receipt'):
        receipt = state['_research_receipt']
    return state


def wait_for(kind, name=None, label=None, *, seconds=2, retry=('missing', 'outside_gemini')):
    deadline = time.monotonic() + seconds
    while True:
        state = read(kind, name, label)
        if state['reason'] not in retry or time.monotonic() >= deadline:
            return state
        time.sleep(.15)


def blocked(control, state):
    result = {'status': 'needs_inspection', 'data': {'control': control, 'reason': state['reason']},
              'message': 'Inspect this browser session before continuing.'}
    if control in {'send', 'start_research'}:
        if state['reason'] in {'missing', 'ambiguous', 'obscured'} and visual_point is None:
            result.update(_visual_fallback=True, dispatched=False)
        elif state['reason'] in {'stale_screenshot', 'visual_target_mismatch'}:
            result.update(reason=state['reason'], dispatched=False)
    return result


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
        return {'status': 'ok', 'data': {'chat_id': page['chat_id']}, '_changed_page': navigated}
    if op == 'read_result':
        state = wait_for('result', seconds=4, retry=('research_turn_not_visible',))
        if state['reason'] == 'running':
            data = {'chat_id': state['chat_id']}
            if state.get('stage'):
                data['stage'] = state['stage']
            result = {'status': 'running', 'data': data}
            if state.get('control'):
                result['next_control'] = {'app': 'gemini', 'operation': 'click',
                                          'params': {'control': state['control']}}
            return result
        if state['reason'] not in {'ready', 'research_no_plan'}:
            return blocked('result', state)
        data = {key: state[key] for key in ('chat_id', 'text', 'truncated')}
        if state['reason'] == 'research_no_plan':
            data['reason'] = state['reason']
            return {'status': 'failed', 'data': data, 'message': 'Gemini returned text without a research plan.'}
        if state.get('stage'):
            data['stage'] = state['stage']
        return {'status': 'ok', 'data': data}
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
        state = wait_for('activate_research', argument, seconds=4, retry=('research_turn_not_visible',))
        if state['reason'] in {'clicked', 'already_clicked'}:
            return {'status': 'running', 'data': {'control': argument, 'clicked': state['reason'] == 'clicked'}}
        return blocked(argument, state)
    if argument == 'deep_research':
        mode = read('research_mode')
        if mode['reason'] == 'ready':
            return {'status': 'ok', '_same_submission': mode.get('same_submission'),
                    'data': {'control': argument, 'clicked': False, 'mode_active': True}}
    state = choose_tool(argument) if argument in tool_items else wait_for('control', argument)
    if argument == 'send' and state['reason'] == 'research_submission_pending':
        return {'status': 'running', 'data': {'control': 'send', 'reason': state['reason']},
                'message': 'Check the existing research submission in this window.'}
    if state['reason'] != 'ready':
        result = blocked(argument, state)
        if dispatch_send:
            result['_send_not_dispatched'] = True
        return result
    if state.get('_research_intent'):
        return {'status': 'ok', '_research_intent': state['_research_intent']}
    click(state)
    if argument == 'deep_research':
        active = wait_for('research_mode')
        if (active['reason'] != 'ready' or active.get('document') != state.get('document')
                or active.get('chat_id') != state.get('chat_id')):
            return blocked(argument, {'reason': 'deep_research_selection_unconfirmed'})
        return {'status': 'ok', '_same_submission': active.get('same_submission'),
                'data': {'control': argument, 'clicked': True, 'mode_active': True}}
    if argument == 'send' and state.get('mode_active'):
        return {'status': 'running', 'data': {'control': 'send', 'clicked': True, 'mode_active': True}}
    return {'status': 'running' if argument == 'send' else 'ok',
            'data': {'control': argument, 'clicked': True}}


if visual_point is not None and not visual_matches():
    result = blocked(argument, {'reason': 'stale_screenshot'})
    if dispatch_send:
        result['_send_not_dispatched'] = True
else:
    result = run()
if receipt:
    result['_research_receipt'] = receipt
print(marker + json.dumps(result, ensure_ascii=False))
'''


def load_submission(checkpoint):
    try:
        return json.loads(checkpoint.read_text()).get('research_submission')
    except (FileNotFoundError, ValueError, AttributeError):
        return None


def run_native(context, values, navigation=''):
    visual = getattr(context, 'visual_click', None)
    if visual is not None:
        navigation += visual['check_code']
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


def dispatch_research(context, checkpoint, values, intent, previous):
    # Serialize research sends for this owner across the checkpoint and click.
    with (checkpoint.parent / 'research-send.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if load_submission(checkpoint) != previous:
            return {'status': 'needs_inspection', 'data': {'reason': 'research_submission_pending'},
                    'message': 'Check the existing submission in this browser session.'}
        context.checkpoint({'research_submission': intent})
        result = run_native(context, {**values, 'research_state': 'submitted',
                                      'saved_submission': intent, 'dispatch_send': True})
        if result.pop('_send_not_dispatched', False):
            context.checkpoint({'research_submission': previous})
        return result


def execute(context, origin, operation, argument=None, *, navigation=''):
    # Keep the selected mode specific to this owned browser session. A replaced
    # document must not silently downgrade a research submission to ordinary chat.
    marker = context.directory / 'deep-research-selected'
    checkpoint = context.directory / 'checkpoint.json'
    if operation == 'click' and argument == 'deep_research':
        marker.touch()
    try:
        research_state = marker.read_text() or 'selected'
    except FileNotFoundError:
        research_state = None
    saved_submission = load_submission(checkpoint)
    if saved_submission:
        research_state = 'submitted'
    values = {
        'origin': origin, 'selectors': SELECTORS, 'ui': CONTROL_UI, 'op': operation,
        'argument': argument, 'tool_items': sorted(TOOL_ITEMS), 'marker': MARKER,
        'research_state': research_state, 'saved_submission': saved_submission, 'dispatch_send': False,
        'visual_point': context.visual_click['point'] if getattr(context, 'visual_click', None) else None,
    }
    result = run_native(context, values, navigation)
    intent = result.pop('_research_intent', None)
    if intent:
        return dispatch_research(context, checkpoint, values, intent, saved_submission)
    changed_page = result.pop('_changed_page', False)
    same_submission = result.pop('_same_submission', True)
    receipt = result.pop('_research_receipt', None)
    if result['status'] == 'ok' and (changed_page or (operation == 'click' and argument in TOOL_ITEMS - {'deep_research'})):
        marker.unlink(missing_ok=True)
        checkpoint.unlink(missing_ok=True)
    elif not same_submission and research_state == 'submitted' and not (saved_submission or {}).get('prompt_hash'):
        marker.write_text('')
        checkpoint.unlink(missing_ok=True)
    elif research_state == 'submitted' and receipt and receipt != saved_submission:
        context.checkpoint({'research_submission': receipt})
    return result
