"""Saved Flow characters and voices through the native UI."""
import json
import re
import shutil

from .downloads import audio
from .references import picker, upload, find_asset


VOICE_FIELDS = {'name': 'voice-name-input', 'dialogue': 'sample-dialogue-input',
                'performance': 'performance-input'}


def remember(context, data):
    folder = context.directory / 'entities'
    folder.mkdir(exist_ok=True)
    path = folder / (data['kind'] + '-' + data['id'] + '.json')
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous.get('profile') != context.profile:
        previous = {}
    value = {**previous, **data, 'profile': context.profile}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)
    return value


def reference(context, kind, title, project, profile=None):
    if kind not in {'character','voice'}:
        return None
    matches = [json.loads(path.read_text()) for path in (context.directory / 'entities').glob(kind + '-*.json')]
    matches = [item for item in matches if item['name'] == title and item['profile'] == (profile or context.profile)
               and item['project'] == project]
    return matches[0] if len(matches) == 1 else None


def definition(context, entity):
    if not entity:
        return None
    if entity['kind'] == 'voice':
        keys = ('base', *VOICE_FIELDS)
        return {key: entity[key] for key in keys} if all(entity.get(key) for key in keys) else None
    path = entity.get('reference', {}).get('path')
    if entity['kind'] != 'character' or not path:
        return None
    value = {'name': entity['name'], 'path': path, 'description': entity.get('description', '')}
    voice = entity.get('voice')
    if voice:
        value['voice'] = voice['name']
        if voice.get('id'):
            saved = context.directory / 'entities' / ('voice-' + voice['id'] + '.json')
            if saved.exists():
                value['voice_definition'] = definition(context, json.loads(saved.read_text()))
    return value


def character_state(ui):
    return ui.read("(() => {const name=document.querySelector('input[aria-label=\"Nama karakter\"],input[aria-label=\"Character name\"]');"
        "if(!name)return null;const img=document.querySelector('img[alt=\"Gambar karakter yang dibuat\"],img[alt=\"Generated character image\"]');"
        "const voice=document.querySelector('flow-character-voice-button,flow-character-voice');return {"
        "id:location.pathname.split('/').pop(),name:name.value,"
        "description:document.querySelector('textarea[aria-label=\"Kepribadian karakter\"],textarea[aria-label=\"Character personality\"]')?.value,"
        "portrait:img?.currentSrc ?? img?.src,ready:!!(img?.complete&&img?.naturalWidth),"
        "voice_text:voice?.innerText ?? '',voice_audio:voice?.querySelector('audio')?.src ?? null};})()")


def capture_character(context, ui):
    path = context.directory / 'checkpoint.json'
    checkpoint = json.loads(path.read_text()) if path.exists() else {}
    if checkpoint.get('job') != context.job_id or checkpoint.get('operation') != 'create_character':
        return
    if checkpoint.get('native_id'):
        return
    location = ui.read('location.href')
    if location.startswith(checkpoint['project'] + '/character/') and ui.read(
            'globalThis.__hermesFlowEntityJob ?? null') == context.job_id:
        checkpoint.update(native_id=location.rsplit('/', 1)[1], character_url=location, stage='created')
        context.checkpoint(checkpoint)
    elif location.startswith(checkpoint['project'] + '/character'):
        raise RuntimeError('The original character draft is still awaiting its native ID. Resume this same job after it appears.')


def character_field(ui, selector, text):
    expression = "(() => {const e=document.querySelector(" + json.dumps(selector) + ");"
    expression += "if(!e||e.disabled||e.readOnly)throw Error('Character field is unavailable');e.focus();e.select();return document.activeElement===e;})()"
    ui.execute(f'''cdp('Network.enable')
drain_events()
if not js({expression!r}):
    raise RuntimeError('Character field did not receive focus')
type_text({text!r})
js('document.activeElement.blur()')
if not wait_for_network_idle(timeout=30,idle_ms=1000):
    raise RuntimeError('The character field save is still in flight')
''', 40)


def finish_character(context, ui, checkpoint):
    params = checkpoint['params']
    if not checkpoint.get('native_id'):
        capture_character(context, ui)
        checkpoint = json.loads((context.directory / 'checkpoint.json').read_text())
    if not checkpoint.get('native_id'):
        return outcome(checkpoint, 'needs_inspection', message='The original character creation has no confirmed native ID')
    context.accepted(checkpoint['native_id'], {'kind': 'character', 'project': checkpoint['project']})
    if ui.read('location.href') != checkpoint['character_url']:
        ui.execute(f"goto_url({checkpoint['character_url']!r})")
    ui.wait("!!document.querySelector('input[aria-label=\"Nama karakter\"],input[aria-label=\"Character name\"]')")
    ready = "Array.from(document.querySelectorAll('img')).some(e=>/Gambar karakter yang dibuat|Generated character image/.test(e.alt)&&e.complete&&e.naturalWidth>0)"
    ui.wait(ready, 60)
    voice_ready = ("document.querySelector('flow-character-voice-button,flow-character-voice')?.innerText.split('\\n').includes("
                   + json.dumps(params.get('voice')) + ")")
    if params.get('voice') and checkpoint['stage'] in {'verifying','finish_intent'}:
        ui.wait(voice_ready + " || /Pilih suara|Choose voice|Select voice/.test(document.querySelector('flow-character-voice-button,flow-character-voice')?.innerText ?? '')", 60)
    current = character_state(ui)
    if (current['name'] != params['name'] or current['description'] != params.get('description','')
            or (params.get('voice') and params['voice'] not in current['voice_text'].splitlines())):
        checkpoint['stage'] = 'created'
    if checkpoint['stage'] == 'created':
        character_field(ui, 'input[aria-label="Nama karakter"],input[aria-label="Character name"]', params['name'])
        character_field(ui, 'textarea[aria-label="Kepribadian karakter"],textarea[aria-label="Character personality"]', params.get('description', ''))
        if params.get('voice') and params['voice'] not in character_state(ui)['voice_text'].splitlines():
            ui.read("(() => {const es=Array.from(document.querySelectorAll('flow-character-voice-button button,flow-character-voice button')).filter(e=>e.querySelector('mat-icon')?.textContent.trim()==='voice_selection');"
                    "if(es.length!==1)throw Error('Character voice selector is unavailable');es[0].setAttribute('data-hermes-character-voice','selected');return true;})()")
            ui.click('[data-hermes-character-voice=selected]')
            open_voice(ui, params['voice'])
            selected = voice_state(ui)
            checkpoint['voice'] = {'name': params['voice'], 'source': selected['src'].split('?',1)[0]}
            if selected['src'].startswith('https://flow-content.google/audio/'):
                identifier = selected['src'].split('/audio/',1)[1].split('?',1)[0]
                checkpoint['voice']['id'] = identifier
                remember(context, {'kind': 'voice', 'id': identifier, 'project': checkpoint['project'],
                                   **{key: selected[key] for key in VOICE_FIELDS}})
            ui.execute('''import time
cdp('Network.enable')
drain_events()
flow_click('button.detail-add-to-prompt-btn', js("document.querySelector('button.detail-add-to-prompt-btn')?.textContent.trim()"))
pending=set()
observed=False
deadline=time.monotonic()+30
idle=time.monotonic()
while time.monotonic()<deadline:
    for event in drain_events():
        p=event.get('params',{})
        if event.get('method')=='Network.requestWillBeSent' and p.get('request',{}).get('method')=='POST' and p['request'].get('url','').startswith('https://flow.google.com/'):
            pending.add(p['requestId'])
            observed=True
            idle=time.monotonic()
        elif event.get('method') in {'Network.loadingFinished','Network.loadingFailed'} and p.get('requestId') in pending:
            pending.remove(p['requestId'])
            idle=time.monotonic()
    if observed and not pending and time.monotonic()-idle>=2:
        break
    wait(.1)
else:
    raise RuntimeError('The native character voice save has not settled')
''', 40)
            ui.wait("!document.querySelector('flow-add-menu-popover-content')")
            ui.wait("document.querySelector('flow-character-voice-button,flow-character-voice')?.innerText.includes(" + json.dumps(params['voice']) + ")")
        checkpoint['stage'] = 'finish_intent'
        context.checkpoint(checkpoint)
        labels = ui.read("Array.from(document.querySelectorAll('button')).map(e=>e.innerText.trim())")
        ui.click('button', next(text for text in ('Selesai','Done') if text in labels))
        ui.wait("!location.pathname.includes('/character')")
        ui.execute(f"goto_url({checkpoint['character_url']!r})")
        ui.wait("!!document.querySelector('input[aria-label=\"Nama karakter\"],input[aria-label=\"Character name\"]')")
        ui.wait(ready, 60)
        checkpoint['stage'] = 'verifying'
        context.checkpoint(checkpoint)
    elif checkpoint['stage'] == 'finish_intent':
        ui.execute(f"goto_url({checkpoint['character_url']!r})")
        ui.wait("!!document.querySelector('input[aria-label=\"Nama karakter\"],input[aria-label=\"Character name\"]')")
    if params.get('voice'):
        ui.wait(voice_ready, 60)
        source = checkpoint.get('voice', {}).get('source')
        if source:
            ui.wait("document.querySelector('flow-character-voice-button audio,flow-character-voice audio')?.src.split('?')[0] === "
                    + json.dumps(source), 60)
    value = character_state(ui)
    if not value or value['id'] != checkpoint['native_id'] or value['name'] != params['name'] or value['description'] != params.get('description',''):
        raise RuntimeError('The saved character fields do not match this creation')
    ui.wait("Array.from(document.querySelectorAll('img')).some(e=>/Gambar karakter yang dibuat|Generated character image/.test(e.alt)&&e.complete&&e.naturalWidth>0)", 60)
    value = character_state(ui)
    if params.get('voice') and params['voice'] not in value['voice_text'].splitlines():
        raise RuntimeError('The saved character voice does not match the selected voice')
    value.update(kind='character',project=checkpoint['project'],voice=checkpoint.get('voice'),reference=checkpoint['reference'])
    value['portrait'] = value['portrait'].split('?',1)[0]
    if value.get('voice'):
        value['voice']['source'] = value['voice']['source'].split('?',1)[0]
    remember(context, value)
    ui.click('button.back-button')
    ui.wait("!location.pathname.includes('/character')")
    return outcome(checkpoint, 'ok', value)


def create_character(context, ui, params):
    if not isinstance(params.get('name'), str) or not params['name'].strip() or not isinstance(params.get('path'), str):
        raise ValueError('Character creation requires a name and a local image path')
    if not isinstance(params.get('description',''), str) or (params.get('voice') is not None and not isinstance(params['voice'], str)):
        raise ValueError('Character description and optional voice name must be strings')
    image = upload(ui, context.directory, params['path'])
    project = ui.read('location.href')
    ui.click('button[aria-label="Menu tambahkan media"],button[aria-label="Add media menu"]')
    labels = ui.read("Array.from(document.querySelectorAll('[role=menuitem] .label')).map(e=>e.textContent.trim())")
    label = next((text for text in ('Buat karakter','Create character') if text in labels), None)
    if label is None:
        raise RuntimeError('The native Create character action is unavailable')
    ui.click('[role=menuitem]', label)
    if not ui.read("location.pathname.endsWith('/character')"):
        if ui.read("document.activeElement?.getAttribute('role') === 'menuitem'"):
            ui.execute("press_key('Enter')")
    ui.wait("location.pathname.endsWith('/character')")
    labels = ui.read("Array.from(document.querySelectorAll('button.create-character-footer-mode-button')).map(e=>e.innerText)")
    label = next((text for text in labels if 'Tambahkan dari project' in text or 'Add from project' in text), None)
    if label is None:
        raise RuntimeError('The native character image picker is unavailable')
    ui.click('button.create-character-footer-mode-button', label.replace('add\n','').strip())
    ui.wait("!!document.querySelector('flow-add-menu-popover-content input.search-input')")
    find_asset(ui, image['title'])
    checkpoint = {'job': context.job_id, 'operation': 'create_character', 'stage': 'choose_intent',
                  'params': params, 'project': project, 'reference': image}
    context.checkpoint(checkpoint)
    try:
        ui.read(f"globalThis.__hermesFlowEntityJob={json.dumps(context.job_id)}")
        ui.click('[data-hermes-flow-asset=selected]')
        ui.wait("/\\/character\\/[^/]+$/.test(location.pathname)", 60)
        capture_character(context, ui)
        checkpoint = json.loads((context.directory / 'checkpoint.json').read_text())
        return finish_character(context, ui, checkpoint)
    except Exception as error:
        return outcome(checkpoint, 'needs_inspection', message=str(error))


def voice_state(ui):
    return ui.read("(() => {const e=document.querySelector('flow-voice-preview-pane');return e?{"
        "name:e.querySelector('.voice-name-input')?.value ?? null,"
        "dialogue:e.querySelector('.sample-dialogue-input')?.value ?? '',"
        "performance:e.querySelector('.performance-input')?.value ?? '',"
        "src:e.querySelector('audio')?.src ?? null}:null;})()")


def open_voice(ui, title):
    picker(ui)
    labels = ui.read("Array.from(document.querySelectorAll('flow-add-menu-side-nav .side-nav-list-item-title')).map(e=>e.textContent.trim())")
    label = next((item for item in ('Suara','Voices') if item in labels), None)
    dedicated = not labels and ui.read("!!document.querySelector('flow-voice-preview-pane')")
    if label is None and not dedicated:
        raise ValueError('The selected Flow composer does not expose Voices')
    if label is not None:
        ui.click('flow-add-menu-side-nav .side-nav-list-item-title', label)
    ui.fill('flow-add-menu-popover-content input.search-input', '')
    expression = "(() => {const es=Array.from(document.querySelectorAll('flow-add-menu-asset-list button.asset-item'));"
    expression += f"const matches=es.filter(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(title)});"
    expression += "if(matches.length>1)throw Error('The Flow voice name is ambiguous');"
    expression += "if(matches.length===1){document.querySelectorAll('[data-hermes-flow-voice]').forEach(e=>e.removeAttribute('data-hermes-flow-voice'));"
    expression += "matches[0].setAttribute('data-hermes-flow-voice','selected');return true;}"
    expression += "const v=document.querySelector('flow-add-menu-asset-list cdk-virtual-scroll-viewport');"
    expression += "if(v)v.scrollTop+=Math.max(200,v.clientHeight*.8);return false;})()"
    ui.wait(expression)
    active = ui.read("document.querySelector('[data-hermes-flow-voice=selected]')?.classList.contains('asset-item-active')")
    if not active:
        ui.click('[data-hermes-flow-voice=selected]')
    ui.wait("!!document.querySelector('flow-voice-preview-pane audio')?.src")


def outcome(checkpoint, status, data=None, message=None):
    identifier = checkpoint.get('native_id')
    request = {'state': 'completed' if status == 'ok' else 'accepted', 'id': identifier} if identifier else {'state': 'unknown'}
    return {'status': status, 'request': request, 'data': data or {}, 'message': message}


def save_voice(context, ui, checkpoint):
    params = checkpoint['params']
    state = voice_state(ui)
    if checkpoint['stage'] == 'preview_intent':
        if not state or any(state.get(key) != params[key] for key in VOICE_FIELDS):
            return outcome(checkpoint, 'needs_inspection', message='Preserve the original voice preview draft. Its fields are unavailable.')
        ui.wait("document.querySelector('flow-voice-preview-pane audio')?.src?.startsWith('blob:')", 60)
        state = voice_state(ui)
        checkpoint['preview'] = audio(ui, context.directory, state['src'], 'voice-preview-' + context.job_id)
        checkpoint['stage'] = 'preview_ready'
        context.checkpoint(checkpoint)
    if checkpoint['stage'] == 'preview_ready':
        state = voice_state(ui)
        if not state or not state.get('src', '').startswith('blob:'):
            return outcome(checkpoint, 'needs_inspection', data={'preview': checkpoint['preview']},
                           message='The original generated voice preview exists locally. Its native save draft needs inspection.')
        checkpoint['stage'] = 'save_intent'
        context.checkpoint(checkpoint)
        ui.click('flow-voice-preview-pane button.voice-save-button')
    if checkpoint['stage'] == 'save_intent':
        # Resolve this same saved name after the one Save gesture.
        state = voice_state(ui)
        if not state or state.get('name') != params['name']:
            open_voice(ui, params['name'])
        ui.wait("document.querySelector('flow-voice-preview-pane audio')?.src?.startsWith('https://flow-content.google/audio/')", 60)
        state = voice_state(ui)
        if any(state.get(key) != params[key] for key in VOICE_FIELDS):
            raise RuntimeError('Saved voice fields do not match the requested voice')
        identifier = state['src'].split('/audio/', 1)[1].split('?', 1)[0]
        if not re.fullmatch(r'[a-f0-9-]+', identifier):
            raise RuntimeError('Saved voice audio identity is unavailable')
        checkpoint.update(native_id=identifier, stage='saved', source=state['src'])
        context.checkpoint(checkpoint)
        context.accepted(identifier, {'kind': 'voice', 'name': params['name']})
    if checkpoint['stage'] == 'saved':
        state = voice_state(ui)
        if not state or state.get('name') != params['name']:
            open_voice(ui, params['name'])
            ui.wait("document.querySelector('flow-voice-preview-pane audio')?.src?.startsWith('https://flow-content.google/audio/')")
            state = voice_state(ui)
        if state['src'].split('/audio/', 1)[-1].split('?', 1)[0] != checkpoint['native_id']:
            raise RuntimeError('The saved voice audio identity changed')
        checkpoint['source'] = state['src']
        file = audio(ui, context.directory, checkpoint['source'], checkpoint['native_id'])
        result = {'kind': 'voice', 'id': checkpoint['native_id'], **{key: params[key] for key in VOICE_FIELDS},
                  'base': params['base'], 'file': file, 'preview': checkpoint['preview'],
                  'project': checkpoint['project']}
        remember(context, result)
        ui.execute("js(\"document.querySelector('flow-voice-preview-pane audio')?.pause()\")\npress_key('Escape')")
        return outcome(checkpoint, 'ok', result)
    return outcome(checkpoint, 'needs_inspection', message='Inspect the original voice creation stage')


def create_voice(context, ui, params):
    for field in ('base', *VOICE_FIELDS):
        if not isinstance(params.get(field), str) or not params[field].strip():
            raise ValueError('Voice creation requires base, name, dialogue and performance')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Install FFmpeg and ffprobe before synthesizing a voice preview')
    open_voice(ui, params['base'])
    ui.wait("document.querySelector('flow-voice-preview-pane audio')?.src === "
            + json.dumps('https://www.gstatic.com/aitestkitchen/voices/samples/' + params['base'] + '.wav'))
    for field in ('dialogue','performance','name'):
        ui.fill('flow-voice-preview-pane .' + VOICE_FIELDS[field], params[field])
    state = voice_state(ui)
    if any(state.get(key) != params[key] for key in VOICE_FIELDS):
        raise RuntimeError('Voice draft fields did not preserve the requested values')
    checkpoint = {'job': context.job_id, 'operation': 'create_voice', 'stage': 'preview_intent',
                  'params': params, 'project': ui.read('location.href')}
    context.checkpoint(checkpoint)
    try:
        ui.click('flow-voice-preview-pane button.voice-audio-card')
        return save_voice(context, ui, checkpoint)
    except Exception as error:
        return outcome(checkpoint, 'needs_inspection', message=str(error))
