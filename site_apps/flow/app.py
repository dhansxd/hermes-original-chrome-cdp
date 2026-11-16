"""Google Flow UI extension for the Original Chrome provider."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from .ui import UI
from .downloads import collect, verify
from .references import upload, bind
from . import entities


ORIGIN = 'https://flow.google.com'
GENERATIONS = {'generate_image': 'image', 'generate_video': 'video'}
GROUPS = {
    'aspect': ('Rasio aspek', 'Aspect ratio'),
    'count': ('Jumlah output', 'Output count'),
    'resolution': ('Resolusi video', 'Video resolution'),
    'duration': ('Durasi video', 'Video duration'),
    'input_type': ('Jenis video', 'Video type'),
}
SETTINGS = {'project','mode','kind','model','aspect','count','duration','resolution','input_type'}
PARAMETERS = {'inspect': {'project','mode','kind'}, 'create_project': {'title'},
              'configure': SETTINGS, 'upload': {'project','path'},
              'bind_reference': {'project','title','kind','slot'},
              'create_voice': {'project','base','name','dialogue','performance'},
              'create_character': {'project','path','name','description','voice'},
              'generate_image': SETTINGS | {'prompt','references'},
              'generate_video': SETTINGS | {'prompt','references'}}


def scope(operation):
    return 'flow:' + GENERATIONS.get(operation, 'controls')


def local_state(context):
    path = context.directory / 'flow-session.json'
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(context, value):
    path = context.directory / 'flow-session.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def project_url(value):
    if re.fullmatch(r'[a-zA-Z0-9-]+', value):
        return ORIGIN + '/project/' + value
    if re.fullmatch(r'https://flow\.google\.com/project/[a-zA-Z0-9-]+', value):
        return value
    raise ValueError('project must be a Flow project ID or its canonical project URL')


def ensure(context, params):
    ui = UI(context)
    current = ui.read('location.href')
    saved = local_state(context)
    target = params.get('project') or saved.get('projects', {}).get(context.profile)
    if target:
        target = project_url(target)
    elif not current.startswith(ORIGIN + '/'):
        target = ORIGIN + '/'
    if target and current != target:
        ui.execute(f'goto_url({target!r})')
    ui.wait("!!document.querySelector('[aria-label=\"Detail akun\"],[aria-label=\"Account details\"]')", 30)
    if params.get('project'):
        saved.setdefault('projects', {})[context.profile] = project_url(params['project'])
        save_state(context, saved)
    return ui


def account(ui, *, credits=True):
    if not credits:
        label = ui.read("document.querySelector('a[href*=\"accounts.google.com/SignOutOptions\"]')?.getAttribute('aria-label') ?? ''")
        email = re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', label)
        if email:
            identity = hashlib.sha256(email.group().lower().encode()).hexdigest()
            return {'id': identity, 'evidence': 'Flow account avatar email hash ' + identity, 'credits': None}
    if ui.read("!!document.querySelector('flow-add-menu-popover-content')"):
        ui.execute("press_key('Escape')")
    ui.click('[aria-label="Detail akun"],[aria-label="Account details"]')
    ui.wait("!!document.querySelector('flow-account-panel')")
    try:
        value = ui.read("document.querySelector('flow-account-panel').innerText")
        email = re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', value)
        if not email:
            raise RuntimeError('Flow account identity is unavailable in the account panel')
        identity = hashlib.sha256(email.group().lower().encode()).hexdigest()
        credits = re.search(r'([\d.,]+)\s+(?:kredit Google Flow|Google Flow credits)', value, re.I)
        return {'id': identity, 'evidence': 'Flow account panel email hash ' + identity,
                'credits': int(re.sub(r'\D', '', credits.group(1))) if credits else None}
    finally:
        ui.click('flow-account-panel button.close-btn')


def identify(context, operation, params):
    # Probe the destination account before opening account-local project IDs.
    if operation == 'create_character':
        entities.capture_character(context, UI(context))
    owner = account(ensure(context, {}), credits=operation in GENERATIONS)
    quota = {'scope': scope(operation)}
    if owner['credits'] is not None and owner['credits'] > 0:
        quota.update(available=True, evidence=f"Flow account panel shows {owner['credits']} credits")
    return {'status': 'ok', 'account': owner, 'quota': quota}


def not_submitted(data):
    return {'status': 'ok', 'data': data,
            'request': {'state': 'not_submitted', 'evidence': 'This operation did not click Generate'}}


def selected_settings(settings, kind):
    groups = settings['groups']
    selected = {group['label']: next((o['value'] for o in group['options'] if o['selected']), None)
                for group in groups if group.get('label')}
    if settings['mode'] == 'agent' and len(groups) == 4:
        offset = 0 if kind == 'image' else 2
        selected = {'aspect': next(o['value'] for o in groups[offset]['options'] if o['selected']),
                    'count': next(o['value'] for o in groups[offset + 1]['options'] if o['selected'])}
    count = next((value for key, value in selected.items() if key in {'Jumlah output','Output count','count'}), 'x1')
    return {'mode': settings['mode'], 'selected': selected, 'models': settings['models'],
            'duration': settings['duration'], 'approval': settings['approval'],
            'quote': settings.get('quote'), 'count': int(count.removeprefix('x'))}


def configure(ui, params, *, kind=None):
    mode = params.get('mode', ui.snapshot()['mode'])
    ui.mode(mode)
    ui.settings(mode)
    try:
        if mode == 'classic' and kind:
            options = ui.snapshot()['groups'][0]['options']
            labels = {'image': {'Gambar', 'Image'}, 'video': {'Video'}}[kind]
            desired = next((o['value'] for o in options if o['value'] in labels), None)
            if desired is None:
                raise ValueError('Flow media kind control is unavailable')
            ui.choose(0, desired)
        if mode == 'agent':
            # Native radio 2 means the agent creates automatically. The user authorized this default.
            if ui.snapshot()['approval'] != '2':
                ui.click('flow-settings-view mat-radio-button:has(input[value="2"]) label')
                ui.wait("document.querySelector('flow-settings-view input[value=\"2\"]')?.checked")
        model_options = ui.model(mode, kind or params.get('kind', 'video'), params.get('model'))
        for key in ('input_type', 'aspect', 'resolution', 'count', 'duration'):
            if key not in params:
                continue
            state = ui.snapshot()
            if mode == 'agent':
                if key not in {'aspect', 'count'}:
                    raise ValueError(f'Agent settings do not expose a hard {key} control')
                if len(state['groups']) != 4:
                    raise RuntimeError('Agent settings group layout changed')
                index = (0 if (kind or params.get('kind', 'video')) == 'image' else 2) + (key == 'count')
            else:
                index = next((i for i, group in enumerate(state['groups']) if group['label'] in GROUPS[key]), None)
                if key == 'duration' and state['duration']:
                    ui.duration(params[key])
                    continue
                if index is None:
                    raise ValueError(f'The selected Flow model does not expose {key}')
            value = str(params[key])
            if key == 'count':
                value = 'x' + value
            if key == 'duration':
                choices = state['groups'][index]['options']
                value = next((item['value'] for item in choices if re.match(r'^' + re.escape(value) + r'\b', item['value'])), value)
            if key == 'input_type':
                aliases = {'ingredients': {'Bahan', 'Ingredients'}, 'frames': {'Frame', 'Frames'}}
                value = next((o['value'] for o in state['groups'][index]['options'] if o['value'] in aliases.get(value, {value})), value)
            ui.choose(index, value)
        result = ui.snapshot()
        result['model_options'] = model_options
        return result
    finally:
        ui.close_settings(mode)


def create_project(context, ui, title):
    if ui.read('location.pathname') != '/':
        ui.click('button[aria-label="Beranda"],button[aria-label="Home"]')
    ui.click('button.new-project-button')
    ui.wait("/^\\/project\\/[^/]+$/.test(location.pathname)")
    url = ui.read('location.href')
    saved = local_state(context)
    saved.setdefault('projects', {})[context.profile] = url
    save_state(context, saved)
    if title:
        ui.wait("!!document.querySelector('input.editable-text-input')")
        ui.fill('input.editable-text-input', title)
        ui.execute("press_key('Enter')")
    result = ui.snapshot()
    return result


def tile_key(tile):
    return tile.get('key') or tile.get('id') or tile.get('src')


def open_output(ui, tile, prompt, mode):
    if tile['kind'] == 'image' and tile.get('id'):
        selector = f'flow-{tile["kind"]}-tile:has([data-media-id="{tile["id"]}"]) > .container'
    else:
        selector = f'flow-video-tile img[src={json.dumps(tile["src"])}]'
    ui.click(selector)
    ui.wait("/\\/edit\\//.test(location.pathname)")
    prompts = ui.read("Array.from(document.querySelectorAll('.prompt-text')).map(e=>e.innerText)")
    if mode == 'classic' and not any(' '.join(text.split()) == ' '.join(prompt.split()) for text in prompts):
        raise RuntimeError('The native result prompt does not match this job')
    tile['edit_url'] = ui.read('location.href')
    tile['id'] = tile.get('id') or tile['edit_url'].rsplit('/', 1)[-1]


def observe_generation(context, ui, checkpoint):
    state = ui.snapshot()
    baseline = set(checkpoint['baseline'])
    outputs = [tile for tile in state['tiles'] if tile['kind'] == checkpoint['kind']
               and tile_key(tile) and tile_key(tile) not in baseline
               and tile.get('id') not in checkpoint.get('reference_ids', [])]
    previous = {tile_key(tile): tile for tile in checkpoint.get('outputs', [])}
    for tile in outputs:
        key = tile_key(tile)
        known = previous.get(key, {})
        tile.update({name: known[name] for name in ('id', 'edit_url') if name in known}, key=key)
        if tile['kind'] == 'video' and tile['ready'] and not tile.get('id'):
            open_output(ui, tile, checkpoint['prompt'], checkpoint['settings']['mode'])
            ui.click('button.back-button')
            ui.wait("!location.pathname.includes('/edit/')")
    checkpoint['outputs'] = outputs
    if outputs and not checkpoint.get('request_id'):
        native = outputs[0].get('id')
        if native:
            checkpoint['request_id'] = native
            context.checkpoint(checkpoint)
            context.accepted(native, {'project': checkpoint['project'], 'kind': checkpoint['kind']})
    context.checkpoint(checkpoint)
    identifier = checkpoint.get('request_id')
    request = {'state': 'accepted', 'id': identifier} if identifier else {'state': 'unknown'}
    new_notices = [text for text in state['notices'] if text not in checkpoint.get('notices_before', [])]
    evidence = next((text for text in new_notices if re.search(
        r'insufficient credits|not enough credits|kredit tidak cukup|kredit Anda (?:telah )?habis', text, re.I)), None)
    if evidence:
        references = checkpoint.get('portable_references', [])
        return {'status': 'quota_exhausted',
                'request': {'state': 'rejected', 'id': identifier, 'terminal': True, 'evidence': evidence},
                'quota': {'scope': scope(checkpoint['operation']), 'exhausted': True, 'evidence': evidence},
                'handoff': {'references': references,
                            'files': [reference['path'] for reference in references if reference.get('path')],
                            'composer': checkpoint.get('composer', {})}}
    if identifier and len(outputs) == checkpoint['count'] and all(tile['ready'] for tile in outputs):
        files = []
        for tile in outputs:
            if not tile.get('id'):
                break
            receipt = context.directory / 'downloads' / (tile['id'] + '.json')
            saved = json.loads(receipt.read_text()) if receipt.exists() else {}
            if not saved:
                open_output(ui, tile, checkpoint['prompt'], checkpoint['settings']['mode'])
                ui.click('button[aria-label="Download media"],button[aria-label="Download media asset"]')
                original = ui.read("Array.from(document.querySelectorAll('[role=menuitem]')).filter(e=>e.getClientRects().length)"
                    ".filter(e=>/Ukuran asli|Original size/i.test(e.innerText)).map(e=>e.querySelector('.label')?.textContent.trim())")
                if len(original) != 1 or not original[0]:
                    raise RuntimeError('The native original-size download option is unavailable')
                action = f'flow_click("[role=menuitem]", {original[0]!r})'
            else:
                action = ''  # The collector reconciles the persisted original GUID.
            file = collect(ui, context.directory, tile['id'], action)
            if file.get('pending'):
                return {'status': 'running', 'request': request, 'data': {'download': file}}
            files.append(verify(file))
            if '/edit/' in ui.read('location.pathname'):
                ui.click('button.back-button')
                ui.wait("!location.pathname.includes('/edit/')")
        if len(files) == checkpoint['count']:
            request['state'] = 'completed'
            checkpoint['files'] = files
            context.checkpoint(checkpoint)
            return {'status': 'ok', 'request': request, 'data': {'files': files, 'settings': checkpoint['settings'],
                    'references': checkpoint.get('references', []),
                    'project': checkpoint['project'], 'credits_before': checkpoint['credits_before'],
                    'credits_after': account(ui)['credits']}}
    return {'status': 'running' if identifier else 'needs_inspection', 'request': request,
            'data': {'project': checkpoint['project'], 'outputs': outputs,
                     'settings': checkpoint['settings'], 'notices': state['notices']},
            'message': 'Observe this same job to reconcile its output and download the original media'}


def generate(context, ui, operation, params):
    kind = GENERATIONS[operation]
    prompt = params.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('A non-empty prompt is required')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Install FFmpeg and ffprobe on the Hermes process PATH before generating media')
    settings = selected_settings(configure(ui, params, kind=kind), kind)
    owner = account(ui)
    editor = ("(() => {const es=Array.from(document.querySelectorAll('[contenteditable=true]')).filter(e=>e.getClientRects().length);"
              "if(es.length!==1)throw Error('Flow composer is ambiguous');es[0].setAttribute('data-hermes-flow-editor','active');"
              "return '[data-hermes-flow-editor=active]';})()")
    selector = ui.read(editor)
    if settings['mode'] == 'agent':
        selected = settings['selected']
        model = next(item['value'] for item in settings['models'] if item['selector'] == kind)
        prompt = (f"Create exactly {settings['count']} {kind} output(s) now using {model}. "
                  f"The output aspect ratio must be {selected['aspect']}. " + prompt)
    ui.fill(selector, prompt)
    bindings = []
    for reference in params.get('references', []):
        title = reference.get('title')
        if reference.get('path'):
            title = upload(ui, context.directory, reference['path'])['title']
        if not title:
            raise ValueError('Each reference requires an uploaded title or local path')
        reference_kind = reference.get('kind','image')
        expected = entities.reference(context, reference_kind, title, ui.read('location.href'))
        bindings.append(bind(ui, title, reference_kind, reference.get('slot'), expected))
    selector = ui.read(editor)
    actual = ui.read(f"document.querySelector({json.dumps(selector)}).innerText")
    if ' '.join(actual.split()) != ' '.join(prompt.split()):
        raise RuntimeError('The Flow composer did not preserve the requested prompt')
    state = ui.snapshot()
    if any(not ingredient['ready'] for ingredient in state['ingredients']):
        raise RuntimeError('A composer reference has not finished loading')
    ui.wait("Array.from(document.querySelectorAll('flow-generate-icon-button button')).some(e=>e.getClientRects().length&&!e.disabled)")
    checkpoint = {'job': context.job_id, 'operation': operation, 'project': state['url'], 'kind': kind,
                  'prompt': prompt, 'settings': settings, 'credits_before': owner['credits'],
                  'references': bindings,
                  'reference_ids': [item['id'] for item in state['ingredients'] if item.get('id')],
                  'composer': {'ingredients': state['ingredients'], 'frames': state['frames'],
                               'references': state['references']},
                  'portable_references': params.get('references', []),
                  'notices_before': state['notices'],
                  'count': settings['count'],
                  'baseline': [tile_key(tile) for tile in state['tiles'] if tile_key(tile)],
                  'submit_intent': True}
    context.checkpoint(checkpoint)
    try:
        ui.click('flow-generate-icon-button button')
        # The source checkpoint precedes the single native submit. Recovery only observes it.
        deadline = time.monotonic() + 120
        while True:
            result = observe_generation(context, ui, checkpoint)
            if checkpoint.get('request_id') or time.monotonic() >= deadline:
                return result
            time.sleep(1)
    except Exception as error:
        request = {'state': 'accepted', 'id': checkpoint['request_id']} if checkpoint.get('request_id') else {'state': 'unknown'}
        return {'status': 'needs_inspection', 'request': request,
                'message': str(error), 'data': {'project': checkpoint['project']}}


def run(context, operation, params):
    try:
        if operation not in PARAMETERS or set(params) - PARAMETERS[operation]:
            raise ValueError('Unknown Flow operation or parameter. Read browser_app describe for the current schema.')
        if operation in GENERATIONS and params.get('kind', GENERATIONS[operation]) != GENERATIONS[operation]:
            raise ValueError('kind must match the generate_image or generate_video operation')
        ui = ensure(context, params)
        if operation == 'create_project':
            return not_submitted(create_project(context, ui, params.get('title')))
        if operation == 'inspect':
            if '/project/' not in ui.read('location.pathname'):
                return not_submitted({'url': ui.read('location.href'), 'account': account(ui)})
            return not_submitted(configure(ui, params))
        if operation == 'configure':
            return not_submitted(configure(ui, params, kind=params.get('kind')))
        if operation == 'upload':
            return not_submitted(upload(ui, context.directory, params['path']))
        if operation == 'bind_reference':
            kind = params.get('kind','image')
            expected = entities.reference(context, kind, params['title'], ui.read('location.href'))
            return not_submitted(bind(ui, params['title'], kind, params.get('slot'), expected))
        if operation == 'create_voice':
            return entities.create_voice(context, ui, params)
        if operation == 'create_character':
            return entities.create_character(context, ui, params)
        if operation in GENERATIONS:
            return generate(context, ui, operation, params)
        raise ValueError('Choose an operation listed by browser_app describe')
    except Exception as error:
        return {'status': 'failed', 'message': str(error),
                'request': {'state': 'rejected', 'evidence': 'Operation stopped before a generation submit'}}


def resume(context, job):
    checkpoint = job.get('checkpoint') or {}
    attempt_id = job['attempts'][-1].get('request_id') if job.get('attempts') else None
    owns_checkpoint = checkpoint.get('job') == context.job_id or (
        attempt_id is not None and attempt_id == checkpoint.get('request_id'))
    if owns_checkpoint and checkpoint.get('operation') == 'create_voice':
        return entities.save_voice(context, ensure(context, {'project': checkpoint['project']}), checkpoint)
    if owns_checkpoint and checkpoint.get('operation') == 'create_character':
        return entities.finish_character(context, UI(context), checkpoint)
    if checkpoint.get('submit_intent') and owns_checkpoint:
        checkpoint.setdefault('count', job['params'].get('count', 1))
        ui = ensure(context, {'project': checkpoint['project']})
        return observe_generation(context, ui, checkpoint)
    return {'status': 'needs_inspection', 'data': ensure(context, job['params']).snapshot(),
            'message': 'Inspect the saved operation before starting another operation'}


def handoff(context, packet):
    remaining = packet.get('remaining', {})
    composer = remaining.get('composer', {})
    references = remaining.get('references', [])
    if (composer.get('ingredients') or composer.get('references')
            or any(frame.get('image') for frame in composer.get('frames', []))) and not references:
        return {'status': 'needs_inspection',
                'message': 'The source composer has native references. Supply their local files to continue them on the destination account.'}
    if any(not reference.get('path') for reference in references):
        return {'status': 'needs_inspection',
                'message': 'The source native reference needs its portable local file on the destination account.'}
    params = dict(packet['params'])
    params.pop('project', None)
    ui = ensure(context, {})
    project = create_project(context, ui, 'Continued Flow project')
    params['project'] = project['url']
    return {'status': 'ok', 'params': params}
