"""Google Flow UI extension for the Original Chrome provider."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from .ui import PROJECT_LOCATION, UI
from .downloads import collect, verify
from .references import upload, bind, acknowledge_upload
from . import entities, preparation


ORIGIN = 'https://flow.google.com'
PROJECT_URL = re.compile(r'https://flow\.google\.com/project/[a-zA-Z0-9-]+')
ACCOUNT_READY = """!!document.querySelector('[aria-label="Detail akun"],[aria-label="Account details"]')"""
PROJECT_READY = """Array.from(document.querySelectorAll(
    'button.agent-mode-chip, button.settings-trigger-button, flow-agent-panel, flow-generate-icon-button button'
)).some(node => node.getClientRects().length && getComputedStyle(node).visibility === 'visible')"""
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
    if isinstance(value, str):
        if re.fullmatch(r'[a-zA-Z0-9-]+', value):
            return ORIGIN + '/project/' + value
        if PROJECT_URL.fullmatch(value):
            return value
    raise ValueError('project must be a Flow project ID or its canonical project URL')


def observed_project(url):
    if not isinstance(url, str):
        return None
    route = re.split(r'[?#]', url, maxsplit=1)[0].removesuffix('/')
    return route if PROJECT_URL.fullmatch(route) else None


def recorded_project(checkpoint):
    value = checkpoint.get('project')
    return observed_project(value) or project_url(value)


def project_matches(project):
    return f'{PROJECT_LOCATION} === {json.dumps(project)}'


def wait_for_project(ui, project):
    ui.wait(f"{project_matches(project)} && ({ACCOUNT_READY}) && ({PROJECT_READY})", 30)


def ensure(context, params, *, inspect_only=False):
    if inspect_only:
        if (set(params) - PARAMETERS['inspect']
                or params.get('mode', 'classic') not in ('classic', 'agent')
                or params.get('kind', 'video') not in ('image', 'video')):
            raise ValueError('Use the inspection parameters listed by browser_app describe.')

    ui = UI(context)
    current = ui.read('location.href')
    saved = local_state(context)
    selected = params.get('project')
    opened = current
    if inspect_only:
        if 'project' in params:
            selected = project_url(selected)
        opened = observed_project(current)
    target = selected or (opened if inspect_only else None) or saved.get('projects', {}).get(context.profile)
    if target:
        target = project_url(target)
        if target != opened:
            ui.execute(f'goto_url({target!r})')
    elif not current.startswith(ORIGIN + '/'):
        ui.execute(f'goto_url({ORIGIN + "/"!r})')
    if inspect_only and target:
        wait_for_project(ui, target)
    else:
        ui.wait(ACCOUNT_READY, 30)
    if selected and not inspect_only:
        saved.setdefault('projects', {})[context.profile] = target
        save_state(context, saved)
    return ui


def generation_project(context, ui, params):
    opened = observed_project(ui.read('location.href'))
    saved = local_state(context)
    if 'project' in params:
        project = project_url(params['project'])
    else:
        previous = saved.get('projects', {}).get(context.profile)
        project = project_url(previous) if previous else opened
    if project is None:
        raise ValueError('Select an existing Flow project before generating.')
    if project != opened:
        ui.execute(f'goto_url({project!r})')
    wait_for_project(ui, project)
    if 'project' in params:
        saved.setdefault('projects', {})[context.profile] = project
        save_state(context, saved)
    return project


def account(ui, *, credits=True, inspect_only=False):
    if not credits:
        label = ui.read("document.querySelector('a[href*=\"accounts.google.com/SignOutOptions\"]')?.getAttribute('aria-label') ?? ''")
        email = re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', label)
        if email:
            identity = hashlib.sha256(email.group().lower().encode()).hexdigest()
            return {'id': identity, 'evidence': 'Flow account avatar email hash ' + identity, 'credits': None}
    if not inspect_only:
        acknowledge_upload(ui)
        if ui.read("!!document.querySelector('flow-add-menu-popover-content')"):
            ui.execute("press_key('Escape')")
    panel_open = inspect_only and ui.read("!!document.querySelector('flow-account-panel')?.getClientRects().length")
    if not panel_open:
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
        if not panel_open:
            ui.click('flow-account-panel button.close-btn')


def identify(context, operation, params):
    if operation == 'inspect':
        ui = ensure(context, params, inspect_only=True)
        return {'status': 'ok', 'account': account(ui, credits=False, inspect_only=True),
                'quota': {'scope': scope(operation)}}
    # Probe the destination account before opening account-local project IDs.
    capture_destination(context, UI(context))
    if operation == 'create_character':
        entities.capture_character(context, UI(context))
    preparing = preparation.resume_before_probe(context)
    ui = UI(context) if preparing else ensure(context, {})
    owner = account(ui, credits=operation in GENERATIONS and not preparing)
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


def inspect(context, params):
    ui = ensure(context, params, inspect_only=True)
    state = ui.snapshot()
    project = observed_project(state['url'])
    if 'project' in params:
        if project != project_url(params['project']):
            raise RuntimeError('The requested Flow project could not be confirmed in the selected Chrome profile.')
        saved = local_state(context)
        saved.setdefault('projects', {})[context.profile] = project
        save_state(context, saved)
    if project is None:
        return {'url': state['url'], 'project_id': None, 'account': account(ui, inspect_only=True)}

    state['project_id'] = project.rsplit('/', 1)[1]
    if 'mode' in params and params['mode'] != state['mode']:
        state['requested_mode'] = params['mode']
    if 'kind' in params:
        state['models'] = [model for model in state['models']
                           if model['selector'] in ('model', params['kind'])]
    return state


def create_project(context, ui, title, checkpoint=None):
    if ui.read('location.pathname') != '/':
        ui.click('button[aria-label="Beranda"],button[aria-label="Home"]')
    ui.click('button.new-project-button')
    ui.wait("/^\\/project\\/[^/]+$/.test(location.pathname)")
    url = ui.read('location.href')
    if checkpoint is not None:
        checkpoint['params']['project'] = url
        checkpoint['stage'] = 'prepared'
        context.checkpoint(checkpoint)
    saved = local_state(context)
    saved.setdefault('projects', {})[context.profile] = url
    save_state(context, saved)
    if title:
        ui.wait("!!document.querySelector('input.editable-text-input')")
        ui.fill('input.editable-text-input', title)
        ui.execute("press_key('Enter')")
    result = ui.snapshot()
    return result


def capture_destination(context, ui):
    path = context.directory / 'checkpoint.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    if (saved.get('job') != context.job_id or saved.get('operation') != 'handoff'
            or saved.get('profile') != context.profile or saved.get('stage') != 'create_intent'):
        return
    current = ui.read('location.href')
    marker = ui.read('globalThis.__hermesFlowProjectJob ?? null')
    if (marker != context.job_id or current == saved['before']
            or not re.fullmatch(r'https://flow\.google\.com/project/[a-zA-Z0-9-]+', current)):
        raise RuntimeError('Inspect the original destination project creation before creating another project.')
    saved['params']['project'] = current
    saved['stage'] = 'prepared'
    context.checkpoint(saved)
    state = local_state(context)
    state.setdefault('projects', {})[context.profile] = current
    save_state(context, state)


def tile_key(tile):
    return tile.get('key') or tile.get('id') or tile.get('src')


def open_output(ui, tile, prompt, mode, project):
    if tile['kind'] == 'image' and tile.get('id'):
        selector = f'flow-{tile["kind"]}-tile:has([data-media-id="{tile["id"]}"]) > .container'
    else:
        selector = f'flow-video-tile img[src={json.dumps(tile["src"])}]'
    if ui.click(selector, project=project) is False:
        raise RuntimeError('Flow left the original project before opening the result.')
    ui.wait("/\\/edit\\//.test(location.pathname)")
    url = ui.read('location.href')
    path = re.split(r'[?#]', url, maxsplit=1)[0].removesuffix('/')
    source, _, asset = path.partition('/edit/')
    if not asset or observed_project(source) != project:
        raise RuntimeError('The Flow result opened outside the original project.')
    prompts = ui.read("Array.from(document.querySelectorAll('.prompt-text')).map(e=>e.innerText)")
    if mode == 'classic' and not any(' '.join(text.split()) == ' '.join(prompt.split()) for text in prompts):
        raise RuntimeError('The native result prompt does not match this job')
    tile['edit_url'] = url
    tile['id'] = tile.get('id') or path.rsplit('/', 1)[-1]
    return path


def quota_rejection(context, checkpoint, evidence):
    checkpoint['quota_evidence'] = evidence
    context.checkpoint(checkpoint)
    references = checkpoint.get('portable_references', [])
    completed = checkpoint.get('continued_files', []) + checkpoint.get('files', [])
    return {'status': 'quota_exhausted',
            'request': {'state': 'rejected', 'id': checkpoint.get('request_id'), 'terminal': True, 'evidence': evidence},
            'quota': {'scope': scope(checkpoint['operation']), 'exhausted': True, 'evidence': evidence},
            'handoff': {'references': references,
                        'files': [reference['path'] for reference in references if reference.get('path')]
                                 + [file['path'] for file in completed],
                        'completed': completed, 'remaining_count': checkpoint['count'] - len(checkpoint.get('files', [])),
                        'composer': checkpoint.get('composer', {})}}


def observation_pending(checkpoint, message):
    identifier = checkpoint.get('request_id')
    request = {'state': 'accepted', 'id': identifier} if identifier else {'state': 'unknown'}
    return {'status': 'needs_inspection', 'request': request, 'message': message}


def source_retry_blocked(context, position, message):
    if position.get('blocked') != message:
        context.checkpoint({**position, 'blocked': message})
    return {'status': 'needs_inspection', 'message': message,
            'request': {'state': 'not_submitted', 'evidence': 'Flow stopped before clicking Generate.'}}


def composer_identity(state):
    def asset(url):
        return (url or '').split('?', 1)[0]

    return ([item.get('id') or asset(item.get('src')) for item in state.get('ingredients', [])],
            [(item['kind'], item.get('id') or asset(item.get('src')), item.get('name'))
             for item in state.get('references', [])],
            [asset(frame.get('image')) for frame in state.get('frames', [])])


def saved_position(context):
    path = context.directory / 'checkpoint.json'
    position = json.loads(path.read_text()) if path.exists() else {}
    if position.get('job') == context.job_id and position.get('profile') == context.profile:
        return position
    return {}


def observe_generation(context, ui, checkpoint):
    project = recorded_project(checkpoint)
    state = ui.snapshot()
    if observed_project(state['url']) != project:
        return observation_pending(checkpoint, 'Flow is outside the original project.')
    baseline = set(checkpoint['baseline'])
    prior = {key for tile in checkpoint.get('prior_source_outputs', [])
             for key in (tile_key(tile), tile.get('id'), tile.get('src')) if key}
    outputs = [tile for tile in state['tiles'] if tile['kind'] == checkpoint['kind']
               and tile_key(tile) and tile_key(tile) not in baseline
               and not prior.intersection((tile_key(tile), tile.get('id'), tile.get('src')))
               and tile.get('id') not in checkpoint.get('reference_ids', [])]
    previous = {tile_key(tile): tile for tile in checkpoint.get('outputs', [])}
    by_id = {tile['id']: key for key, tile in previous.items() if tile.get('id')}
    current = {}
    for tile in outputs:
        key = by_id.get(tile.get('id')) or tile_key(tile)
        source = tile.get('src')
        # A tile can acquire its native ID after it first appears with only a poster URL.
        if key not in previous and source in previous and not previous[source].get('id'):
            key = source
        known = previous.get(key, {})
        if key in current or (known.get('id') and tile.get('id') and known['id'] != tile['id']):
            return observation_pending(checkpoint, 'Flow displayed conflicting identities for a source result.')
        tile.update({name: known[name] for name in ('id', 'edit_url') if known.get(name)}, key=key)
        current[key] = tile
    observed = {**previous, **current}
    if len(observed) > checkpoint['count']:
        return observation_pending(checkpoint,
            'More new native outputs exist than this job requested. Inspect their attribution before continuing.')
    if previous.keys() - current.keys():
        checkpoint['outputs'] = list(observed.values())
        context.checkpoint(checkpoint)
        return observation_pending(checkpoint, 'Previously observed Flow outputs are missing from the source project.')
    for tile in outputs:
        if tile['kind'] == 'video' and tile['ready'] and not tile.get('id'):
            open_output(ui, tile, checkpoint['prompt'], checkpoint['settings']['mode'], project)
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
    evidence = evidence or checkpoint.get('quota_evidence')
    if evidence and not outputs:
        if identifier:
            return observation_pending(checkpoint, 'Flow displayed a quota notice without a terminal source result.')
        return quota_rejection(context, checkpoint, evidence)
    if evidence:
        checkpoint['quota_evidence'] = evidence
        context.checkpoint(checkpoint)
    if identifier and (len(outputs) == checkpoint['count'] or evidence) and all(tile['ready'] for tile in outputs):
        files = []
        for tile in outputs:
            if not tile.get('id'):
                break
            receipt = context.directory / 'downloads' / (tile['id'] + '.json')
            saved = json.loads(receipt.read_text()) if receipt.exists() else {}
            if not saved:
                asset = open_output(ui, tile, checkpoint['prompt'], checkpoint['settings']['mode'], project)
                if ui.click('button[aria-label="Download media"],button[aria-label="Download media asset"]',
                            project=asset) is False:
                    return observation_pending(checkpoint, 'Flow left the original result before download.')
                original = ui.read("Array.from(document.querySelectorAll('[role=menuitem]')).filter(e=>e.getClientRects().length)"
                    ".filter(e=>/Ukuran asli|Original size/i.test(e.innerText)).map(e=>e.querySelector('.label')?.textContent.trim())")
                if len(original) != 1 or not original[0]:
                    raise RuntimeError('The native original-size download option is unavailable')
                action = (f'if not flow_click("[role=menuitem]", {original[0]!r}, project={asset!r}):\n'
                          "    raise RuntimeError('Flow left the original result before download.')")
            else:
                action = ''  # The collector reconciles the persisted original GUID.
            file = collect(ui, context.directory, tile['id'], action)
            if file.get('pending'):
                return {'status': 'running', 'request': request, 'data': {'download': file}}
            files.append(verify(file))
            if '/edit/' in ui.read('location.pathname'):
                ui.click('button.back-button')
                ui.wait("!location.pathname.includes('/edit/')")
        checkpoint['files'] = files
        context.checkpoint(checkpoint)
        if len(files) == checkpoint['count']:
            request['state'] = 'completed'
            return {'status': 'ok', 'request': request, 'data': {'files': checkpoint.get('continued_files', []) + files, 'settings': checkpoint['settings'],
                    'references': checkpoint.get('references', []),
                    'transfers': checkpoint.get('transfers', []),
                    'project': checkpoint['project'], 'credits_before': checkpoint['credits_before'],
                    'credits_after': account(ui)['credits']}}
        if evidence:
            return quota_rejection(context, checkpoint, evidence)
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
    project = generation_project(context, ui, params)
    position = saved_position(context)
    if position.get('operation') not in {'handoff', 'source_retry'}:
        position = {}
    retry = position.get('operation') == 'source_retry'
    settings = selected_settings(configure(ui, params, kind=kind), kind)
    owner = account(ui)
    if retry:
        category = 'model' if params['mode'] == 'classic' else kind
        models = [model['value'] for model in settings['models'] if model['selector'] == category]
        if (owner.get('id') != position['account'] or settings['count'] != params['count']
                or settings['mode'] != params['mode'] or models != [params['model']]):
            return source_retry_blocked(context, position,
                'Flow could not verify the original account, model, and remaining output count.')
    quota_quote = settings.get('quote')
    quota_quote_source = 'selected composer'
    if not retry and settings['mode'] == 'agent' and owner['credits'] == 0:
        model = next(item['value'] for item in settings['models'] if item['selector'] == kind)
        try:
            native = configure(ui, {'mode': 'classic', 'model': model}, kind=kind)
            quota_quote = native.get('quote')
            quota_quote_source = 'native classic composer for the selected Agent model'
        finally:
            configure(ui, params, kind=kind)
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
    portable = []
    for reference in params.get('references', []):
        reference = dict(reference)
        title = reference.get('title')
        if reference.get('path'):
            uploaded = upload(ui, context.directory, reference['path'])
            title = uploaded['title']
            reference['path'] = uploaded['path']
        if not title:
            raise ValueError('Each reference requires an uploaded title or local path')
        reference_kind = reference.get('kind','image')
        expected = entities.reference(context, reference_kind, title, ui.read('location.href'))
        if reference_kind in {'character', 'voice'} and not reference.get('definition'):
            reference['definition'] = entities.definition(context, expected)
        bindings.append(bind(ui, title, reference_kind, reference.get('slot'), expected))
        portable.append(reference)
    selector = ui.read(editor)
    actual = ui.read(f"document.querySelector({json.dumps(selector)}).innerText")
    if ' '.join(actual.split()) != ' '.join(prompt.split()):
        raise RuntimeError('The Flow composer did not preserve the requested prompt')
    if retry or (bindings and settings['mode'] == 'classic'):
        ui.settings(settings['mode'])
        try:
            settings['quote'] = ui.snapshot().get('quote')
            quota_quote = settings['quote']
        finally:
            ui.close_settings(settings['mode'])
    if retry:
        owner = account(ui)
        if owner.get('id') != position['account']:
            return source_retry_blocked(context, position, 'Flow could not verify the original account before Generate.')
    state = ui.snapshot()
    if observed_project(state['url']) != project:
        raise RuntimeError('The requested Flow project changed before Generate.')
    if any(not ingredient['ready'] for ingredient in state['ingredients']):
        raise RuntimeError('A composer reference has not finished loading')
    if retry:
        if composer_identity(state) != composer_identity(position['composer']):
            return source_retry_blocked(context, position, 'Flow could not confirm the original composer references.')
        visible = {key for tile in state['tiles'] for key in (tile_key(tile), tile.get('id')) if key}
        if any((tile_key(tile) not in visible and tile.get('id') not in visible)
               for tile in position['outputs']):
            return source_retry_blocked(context, position, 'Flow could not confirm previously observed outputs in the source project.')
    checkpoint = {'job': context.job_id, 'operation': operation, 'project': project, 'kind': kind,
                  'prompt': prompt, 'settings': settings, 'credits_before': owner['credits'],
                  'references': bindings,
                  'reference_ids': [item['id'] for item in state['ingredients'] if item.get('id')],
                  'composer': {'ingredients': state['ingredients'], 'frames': state['frames'],
                               'references': state['references']},
                  'portable_references': portable,
                  'continued_files': position.get('completed', []), 'transfers': position.get('transfers', []),
                  'quota_quote': quota_quote,
                  'quota_quote_source': quota_quote_source,
                  'notices_before': state['notices'],
                  'count': settings['count'],
                  'baseline': [tile_key(tile) for tile in state['tiles'] if tile_key(tile)],
                  'submit_intent': False}
    if retry:
        checkpoint['prior_source_outputs'] = position['outputs']
    costs = re.findall(r'(?<![\d.,])(\d+(?:[.,]\d{3})*)\s+(?:kredit|credits)\b', quota_quote or '', re.I)
    if retry and (len(costs) != 1 or owner['credits'] is None):
        return source_retry_blocked(context, position, 'Flow could not verify the current credit balance and generation price.')
    if costs and owner['credits'] is not None:
        required = int(re.sub(r'\D', '', costs[0]))
        if owner['credits'] < required:
            return quota_rejection(context, checkpoint,
                f"Flow account panel shows {owner['credits']} credits and its {quota_quote_source} quotes {required} credits")
    ready = "Array.from(document.querySelectorAll('flow-generate-icon-button button')).some(e=>e.getClientRects().length&&!e.disabled)"
    ui.wait(f'{project_matches(project)} && {ready}')
    checkpoint['submit_intent'] = True
    context.checkpoint(checkpoint)
    try:
        if ui.click('flow-generate-icon-button button', project=project) is not False:
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
    checkpoint['submit_intent'] = False
    context.checkpoint(checkpoint)
    raise RuntimeError('The requested Flow project changed before Generate.')


def run(context, operation, params):
    preparing_generation = False
    try:
        if operation not in PARAMETERS or set(params) - PARAMETERS[operation]:
            raise ValueError('Unknown Flow operation or parameter. Read browser_app describe for the current schema.')
        if operation in GENERATIONS and params.get('kind', GENERATIONS[operation]) != GENERATIONS[operation]:
            raise ValueError('kind must match the generate_image or generate_video operation')
        if operation == 'inspect':
            return not_submitted(inspect(context, params))
        if operation in GENERATIONS:
            preparing_generation = True
            return generate(context, UI(context), operation, params)
        ui = ensure(context, params)
        if operation == 'create_project':
            return not_submitted(create_project(context, ui, params.get('title')))
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
        raise ValueError('Choose an operation listed by browser_app describe')
    except Exception as error:
        if preparing_generation:
            position = saved_position(context)
            if position.get('operation') == 'source_retry':
                return source_retry_blocked(context, position, str(error) or type(error).__name__)
        return {'status': 'failed', 'message': str(error) or type(error).__name__,
                'error': {'type': type(error).__name__, 'message': str(error)},
                'request': {'state': 'rejected', 'evidence': 'Operation stopped before a generation submit'}}


def resume(context, job):
    if job.get('phase') == 'handoff':
        return handoff(context, job['handoff'])
    checkpoint = job.get('checkpoint') or {}
    attempt_id = job['attempts'][-1].get('request_id') if job.get('attempts') else None
    owns_checkpoint = checkpoint.get('job') == context.job_id or (
        attempt_id is not None and attempt_id == checkpoint.get('request_id'))
    if (owns_checkpoint and checkpoint.get('operation') == 'source_retry'
            and checkpoint.get('profile') == context.profile and checkpoint.get('blocked')):
        return source_retry_blocked(context, checkpoint, checkpoint['blocked'])
    if owns_checkpoint and checkpoint.get('operation') == 'create_voice':
        return entities.save_voice(context, ensure(context, {'project': checkpoint['project']}), checkpoint)
    if owns_checkpoint and checkpoint.get('operation') == 'create_character':
        return entities.finish_character(context, UI(context), checkpoint)
    if checkpoint.get('submit_intent') and owns_checkpoint:
        checkpoint.setdefault('count', job['params'].get('count', 1))
        try:
            ui = ensure(context, {'project': recorded_project(checkpoint)}, inspect_only=True)
        except (RuntimeError, ValueError) as error:
            return observation_pending(checkpoint, str(error))
        return observe_generation(context, ui, checkpoint)
    return {'status': 'needs_inspection', 'data': ensure(context, job['params']).snapshot(),
            'message': 'Inspect the saved operation before starting another operation'}


def prepare_source_retry(context, packet):
    checkpoint, source, remaining = packet['checkpoint'], packet['source'], packet['remaining']
    operation = packet['operation']
    count = remaining.get('remaining_count')
    if (operation not in GENERATIONS or checkpoint.get('operation') != operation
            or checkpoint.get('job') != context.job_id or source['profile'] != context.profile
            or not checkpoint.get('quota_evidence')
            or type(count) is not int or not 0 < count == checkpoint['count'] - len(checkpoint.get('files', []))):
        return {'status': 'needs_inspection', 'message': 'Flow needs a verified terminal quota checkpoint with remaining outputs.'}
    settings, kind = checkpoint['settings'], GENERATIONS[operation]
    category = 'model' if settings['mode'] == 'classic' else kind
    models = [item['value'] for item in settings['models'] if item['selector'] == category and item['value']]
    if len(models) != 1:
        return {'status': 'needs_inspection', 'message': 'Flow could not confirm the model from the source checkpoint.'}
    params = {**packet['params'], 'project': recorded_project(checkpoint), 'count': count,
              'mode': settings['mode'], 'model': models[0],
              'references': checkpoint.get('portable_references', [])}
    for key in ('aspect', 'input_type', 'resolution', 'duration'):
        value = settings['selected'].get('aspect') if key == 'aspect' else None
        value = next((settings['selected'][label] for label in GROUPS[key] if settings['selected'].get(label)), value)
        if key == 'duration':
            value = (settings.get('duration') or {}).get('text') or value
            value = re.match(r'\d+', str(value))
            value = int(value[0]) if value else None
        if value is not None:
            params[key] = value
    context.checkpoint({'job': context.job_id, 'profile': context.profile, 'operation': 'source_retry',
                        'account': source['account']['id'], 'composer': checkpoint.get('composer', {}),
                        'outputs': checkpoint.get('prior_source_outputs', []) + checkpoint.get('outputs', []),
                        'completed': remaining.get('completed', []),
                        'transfers': checkpoint.get('transfers', [])})
    return {'status': 'ok', 'params': params}


def handoff(context, packet):
    remaining = packet.get('remaining', {})
    composer = remaining.get('composer', {})
    references = remaining.get('references', packet['params'].get('references', []))
    if (composer.get('ingredients') or composer.get('references')
            or any(frame.get('image') for frame in composer.get('frames', []))) and not references:
        return {'status': 'needs_inspection',
                'message': 'The source composer has native references. Supply their local files to continue them on the destination account.'}
    if any(not reference.get('path') for reference in references if reference.get('kind', 'image') in {'image', 'video'}):
        return {'status': 'needs_inspection',
                'message': 'The source native reference needs its portable local file on the destination account.'}
    for reference in references:
        kind = reference.get('kind', 'image')
        if kind not in {'character', 'voice'}:
            continue
        if not reference.get('definition') and packet.get('source', {}).get('profile'):
            source_profile = packet['source']['profile']
            source_project = packet['params'].get('project') or local_state(context).get('projects', {}).get(source_profile)
            if source_project:
                source = entities.reference(context, kind, reference['title'], project_url(source_project), source_profile)
                reference['definition'] = entities.definition(context, source)
        definition = reference.get('definition') or {}
        required = ('base', 'dialogue', 'performance') if kind == 'voice' else ('path',)
        if any(not definition.get(key) for key in required):
            return {'status': 'needs_inspection',
                    'message': 'The source ' + kind + ' needs its original portable creation definition on the destination account.'}
        if kind == 'character':
            definition['path'] = str(Path(definition['path']).expanduser().resolve(strict=True))
    capture_destination(context, UI(context))
    preparing = preparation.resume_before_probe(context)
    ui = UI(context) if preparing else ensure(context, {})
    path = context.directory / 'checkpoint.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    if (saved.get('job') != context.job_id or saved.get('operation') != 'handoff'
            or saved.get('profile') != context.profile):
        params = {**packet['params'], 'references': references}
        params.pop('project', None)
        if 'remaining_count' in remaining:
            params['count'] = remaining['remaining_count']
        saved = {'job': context.job_id, 'operation': 'handoff', 'profile': context.profile,
                 'stage': 'create_intent', 'before': ui.read('location.href'), 'params': params,
                 'completed': remaining.get('completed', [])}
        context.checkpoint(saved)
        ui.read('globalThis.__hermesFlowProjectJob=' + json.dumps(context.job_id))
        project = create_project(context, ui, 'Continued Flow project', saved)
        saved['params']['project'] = project['url']
    if any(reference.get('kind') in {'character', 'voice'} for reference in references):
        if not saved.get('active_entity') and not saved.get('entities_prepared'):
            compatible = {'mode': 'classic', 'input_type': 'ingredients'}
            if saved['params'].get('model'):
                compatible['model'] = saved['params']['model']
            configure(ui, compatible, kind='video')
        saved['transfers'] = preparation.references(context, saved)
        saved['entities_prepared'] = True
    saved['stage'] = 'prepared'
    context.checkpoint(saved)
    return {'status': 'ok', 'params': saved['params'],
            'request': {'state': 'not_submitted', 'evidence': 'The destination project and parameters are prepared'}}
