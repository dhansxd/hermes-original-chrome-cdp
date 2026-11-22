"""Native media picker actions and portable local reference files."""
import hashlib
import json
import mimetypes
import shutil
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit


def display_title(filename):
    media_type = mimetypes.guess_type(filename)[0] or ''
    return Path(filename).stem if media_type.startswith('video/') else filename


def wait_for_media(ui, kind):
    ui.wait("(() => {const chips=Array.from(document.querySelectorAll('flow-ingredient-bar flow-" + kind
            + "-ingredient-chip')).filter(e=>e.querySelector('button')?.getClientRects().length);"
            "return chips.length>0&&chips.every(e=>{const i=e.querySelector('img');return i?.complete&&i.naturalWidth>0;});})()", 60)


def picker(ui):
    if not ui.read("!!document.querySelector('flow-add-menu-popover-content')?.getClientRects().length"):
        if ui.read("!!document.querySelector('button.add-menu-trigger')?.getClientRects().length"):
            ui.click('button.add-menu-trigger')
        else:
            ui.read("(() => {const e=document.querySelector('.frame-trigger:has(button.empty-chip)');"
                    "if(!e)throw Error('No media picker is available');"
                    "document.querySelectorAll('[data-hermes-flow-picker]').forEach(n=>n.removeAttribute('data-hermes-flow-picker'));"
                    "e.setAttribute('data-hermes-flow-picker','active');return true;})()")
            ui.click('[data-hermes-flow-picker=active]')
    ui.wait("!!document.querySelector('flow-add-menu-popover-content input.search-input')")


def acknowledge_upload(ui):
    rights = ui.read("Array.from(document.querySelectorAll('[role=dialog]')).some(e=>/Hak untuk menggunakan|Rights to use/.test(e.innerText))")
    if rights:
        ui.click('[role=dialog] button', 'Saya setuju' if ui.read(
            "Array.from(document.querySelectorAll('[role=dialog] button')).some(e=>e.innerText.trim()==='Saya setuju')") else 'I agree')
        ui.wait("!Array.from(document.querySelectorAll('[role=dialog]')).some(e=>/Hak untuk menggunakan|Rights to use/.test(e.innerText))")
    return rights


def upload_picker(ui):
    acknowledge_upload(ui)
    try:
        picker(ui)
    except RuntimeError:
        if not acknowledge_upload(ui):
            raise
        picker(ui)
    labels = ui.read("Array.from(document.querySelectorAll('flow-add-menu-side-nav .side-nav-list-item-title')).map(e=>e.textContent.trim())")
    all_label = next((label for label in ('Semua', 'All') if label in labels), None)
    if all_label:
        ui.click('flow-add-menu-side-nav .side-nav-list-item-title', all_label)
        ui.wait("Array.from(document.querySelectorAll('flow-add-menu-side-nav [role=tab]')).some(e=>"
                f"e.querySelector('.side-nav-list-item-title')?.textContent.trim()==={json.dumps(all_label)}&&e.getAttribute('aria-selected')==='true')")


def find_asset(ui, title):
    ui.fill('flow-add-menu-popover-content input.search-input', title)
    expression = "(() => {const es=Array.from(document.querySelectorAll('flow-add-menu-popover-content button.asset-item'));"
    expression += f"const exact=es.filter(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(title)});"
    expression += f"const matches=exact.length?exact:es.filter(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(display_title(title))});"
    expression += "if(matches.length>1)throw Error('The Flow asset title is ambiguous');"
    expression += "if(matches.length!==1)return false;document.querySelectorAll('[data-hermes-flow-asset]').forEach(e=>e.removeAttribute('data-hermes-flow-asset'));"
    expression += "matches[0].setAttribute('data-hermes-flow-asset','selected');return true;})()"
    ui.wait(expression)


def select_asset(ui, title, kind=None):
    picker(ui)
    if kind:
        labels = {'image': ('Semua','All','Gambar','Images'), 'video': ('Semua','All','Video','Videos'),
                  'character': ('Karakter','Characters'), 'voice': ('Suara','Voices')}
        options = ui.read("Array.from(document.querySelectorAll('flow-add-menu-side-nav .side-nav-list-item-title')).map(e=>e.textContent.trim())")
        label = next((value for value in labels[kind] if value in options), None)
        if not label:
            raise ValueError('This Flow picker does not expose ' + kind)
        ui.click('flow-add-menu-side-nav .side-nav-list-item-title', label)
        ui.wait("Array.from(document.querySelectorAll('flow-add-menu-side-nav [role=tab]')).some(e=>"
                f"e.querySelector('.side-nav-list-item-title')?.textContent.trim()==={json.dumps(label)} && e.getAttribute('aria-selected')==='true')")
    find_asset(ui, title)
    ui.click('[data-hermes-flow-asset=selected]')
    ui.wait("!document.querySelector('flow-add-menu-popover-content') || !!document.querySelector('button.detail-add-to-prompt-btn')")


def upload(ui, directory, path):
    source = Path(path).expanduser().resolve(strict=True)
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    files = Path(directory) / 'references'
    files.mkdir(exist_ok=True)
    key = hashlib.sha256((ui.context.profile + ui.read('location.pathname') + digest).encode()).hexdigest()
    receipt = files / (key + '.json')
    saved = json.loads(receipt.read_text()) if receipt.exists() else {}
    owner = hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:12]
    filename = digest + '-' + owner + source.suffix.lower()
    if receipt.exists():
        filename = (saved.get('filename') or Path(saved.get('path', '')).name
                    or saved.get('title', digest + source.suffix.lower()))
    destination = files / filename
    if not destination.exists():
        shutil.copyfile(source, destination)
    value = {'path': str(destination), 'sha256': digest, 'filename': destination.name,
             'title': display_title(destination.name)}
    remote = getattr(ui.context, 'device', 'local') != 'local'
    if receipt.exists():
        if saved.get('complete'):
            if remote:
                ui.context.release_reference(destination, digest)
            return value
        if saved.get('version') != 2 or saved.get('assignment_intent'):
            # A previous call may have already uploaded the file. Reconcile its exact unique title.
            upload_picker(ui)
            find_asset(ui, value['title'])
            receipt.write_text(json.dumps({**value, 'complete': True}))
            if remote:
                ui.context.release_reference(destination, digest)
            ui.execute("press_key('Escape')")
            return value
    browser_path = ui.context.stage_reference(destination, digest) if remote else str(destination)
    receipt.write_text(json.dumps({**value, 'version': 2, 'complete': False, 'assignment_intent': False}))
    ui.execute(f'''import json,time
from pathlib import Path
receipt=Path({str(receipt)!r})
cdp('Page.enable')
drain_events()
cdp('Page.setInterceptFileChooserDialog',enabled=True)
try:
    flow_click('button[aria-label="Menu tambahkan media"],button[aria-label="Add media menu"]')
    flow_click('[role=menuitem]', 'Upload')
    wait(.1)
    chooser=next((e['params'] for e in drain_events() if e.get('method')=='Page.fileChooserOpened'),None)
    if not chooser and js("(() => {{const e=document.activeElement;return e?.getAttribute('role')==='menuitem'&&e.getClientRects().length&&e.querySelector('.label')?.textContent.trim()==='Upload';}})()"):
        press_key('Enter')
    deadline=time.monotonic()+10
    while True:
        chooser=chooser or next((e['params'] for e in drain_events() if e.get('method')=='Page.fileChooserOpened'),None)
        if chooser:
            state=json.loads(receipt.read_text())
            state['assignment_intent']=True
            receipt.write_text(json.dumps(state))
            cdp('DOM.setFileInputFiles',backendNodeId=chooser['backendNodeId'],files=[{browser_path!r}])
            break
        if time.monotonic()>=deadline:
            raise RuntimeError('Flow did not open its native upload chooser')
        wait(.1)
finally:
    cdp('Page.setInterceptFileChooserDialog',enabled=False)
''')
    # Rights acknowledgement belongs to this authorized upload when Flow presents it.
    deadline = time.monotonic() + 60
    upload_picker(ui)
    while True:
        rights = ui.read("Array.from(document.querySelectorAll('[role=dialog]')).some(e=>/Hak untuk menggunakan|Rights to use/.test(e.innerText))")
        if rights:
            buttons = ui.read("Array.from(document.querySelectorAll('[role=dialog] button')).map(e=>e.innerText.trim())")
            agree = next((text for text in buttons if text in {'Saya setuju','I agree'}), None)
            if not agree:
                raise RuntimeError('The upload rights dialog changed')
            ui.click('[role=dialog] button', agree)
        found = ui.read("Array.from(document.querySelectorAll('flow-add-menu-popover-content button.asset-item'))"
            f".some(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(value['title'])} && !/Mengupload|Uploading/.test(e.innerText))")
        if found:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Observe the original upload before uploading this file again')
        time.sleep(.5)
    ui.execute("press_key('Escape')")
    receipt.write_text(json.dumps({**value, 'complete': True}))
    if remote:
        ui.context.release_reference(destination, digest)
    return value


def voice_binding(ui):
    return ui.execute('''import json,time
point=js("(() => {const es=Array.from(document.querySelectorAll('flow-audio-ingredient-chip button')).filter(e=>e.getClientRects().length);if(es.length!==1)throw Error('Voice chip is ambiguous');const e=es[0];e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
cdp('Input.dispatchMouseEvent',type='mouseMoved',x=point[0],y=point[1],_response_timeout=30)
try:
    deadline=time.monotonic()+30
    while True:
        source=js("document.querySelector('flow-audio-ingredient-preview audio')?.src ?? null")
        if source and source.startswith('https://flow-content.google/audio/'):
            text=js("document.querySelector('flow-audio-ingredient-preview')?.innerText ?? ''")
            print('FLOW_VALUE='+json.dumps({'source':source,'text':text}))
            break
        if time.monotonic()>=deadline:
            raise RuntimeError('The native voice chip preview identity is unavailable')
        wait(.2)
finally:
    js("document.querySelector('flow-audio-ingredient-preview audio')?.pause()")
    cdp('Input.dispatchMouseEvent',type='mouseMoved',x=0,y=0,_response_timeout=30)
''', 100)


def verify_binding(ui, value, expected=None):
    kind = value['kind']
    if kind not in {'character','voice'}:
        return value
    state = ui.snapshot()
    chips = [item for item in state['references'] if item['kind'] == kind]
    if kind == 'character' and expected:
        key = lambda source: source.split('?',1)[0].split('=',1)[0]
        chips = [item for item in chips if item['src'] and key(item['src']) == key(expected['portrait'])]
    if len(chips) != 1 or not chips[0]['ready'] or chips[0]['disabled']:
        raise RuntimeError('The selected character/voice chip is unready, incompatible or ambiguous')
    result = {**value, 'ready': True, 'reference': chips[0]}
    if kind == 'voice':
        voice = voice_binding(ui)
        source = voice['source']
        identifier = unquote(urlsplit(source).path.split('/audio/',1)[1])
        if expected and identifier != expected['id']:
            raise RuntimeError('The native voice chip does not match the saved voice audio ID')
        result.update(media_id=identifier,source=source.split('?',1)[0],voice_text=voice['text'])
    elif expected:
        result['character_id'] = expected['id']
    return result


def bind(ui, title, kind='image', slot=None, expected=None):
    if kind not in {'image','video','character','voice'}:
        raise ValueError('Reference kind must be image, video, character or voice')
    state = ui.snapshot()
    key = hashlib.sha256(json.dumps([ui.context.profile,state['url'],title,kind,slot]).encode()).hexdigest()
    receipt = ui.context.directory / 'references' / ('binding-' + key + '.json')
    receipt.parent.mkdir(exist_ok=True)
    saved = json.loads(receipt.read_text()) if receipt.exists() else {}
    if kind == 'character' and saved.get('reference'):
        wanted = expected or {'portrait': saved['reference']['src'], 'id': saved.get('character_id')}
        key = lambda source: source.split('?',1)[0].split('=',1)[0]
        characters = [item for item in state['references'] if item['kind'] == 'character']
        if any(item.get('src') and key(item['src']) == key(wanted['portrait']) for item in characters):
            return verify_binding(ui, {**saved, 'already_bound': True}, wanted)
    if kind == 'voice':
        voices = [item for item in state['references'] if item['kind'] == 'voice']
        if len(voices) == 1 and voices[0]['ready'] and not voices[0]['disabled']:
            candidate = verify_binding(ui, {**saved, 'title': title, 'kind': kind, 'already_bound': True})
            wanted = expected.get('id') if expected else saved.get('media_id')
            if (candidate['media_id'] == wanted if wanted else title in candidate['voice_text'].splitlines()):
                receipt.write_text(json.dumps(candidate))
                return candidate
    present = {item['id'] for item in state['ingredients'] if item.get('id') and item['ready']}
    sources = {item['src'].split('?', 1)[0] for item in state['ingredients'] if item.get('src') and item['ready']}
    saved_sources = {item['src'].split('?', 1)[0] for item in saved.get('ingredients', []) if item.get('src')}
    if kind in {'image','video'} and saved_sources and saved_sources <= sources and not slot:
        return {**saved, 'already_bound': True}
    if saved.get('ids') and set(saved['ids']).issubset(present) and not slot:
        return verify_binding(ui, {**saved, 'already_bound': True}, expected)
    before_ids = present
    before = ui.read("Array.from(document.querySelectorAll('flow-ingredient-bar > *,flow-ingredient-bar img')).map(e=>e.outerHTML)")
    if slot:
        if slot not in {'first','last'} or kind != 'image':
            raise ValueError('First/last frame slots require an image')
        index = 0 if slot == 'first' else 1
        if len(state['frames']) <= index:
            raise ValueError('The selected model does not expose the requested frame slot')
        current = state['frames'][index]['image']
        if saved.get('frame') and current and current.split('?')[0] == saved['frame'].split('?')[0]:
            return {**saved, 'already_bound': True}
        if current:
            ui.read("(() => {document.querySelectorAll('[data-hermes-flow-replace]').forEach(e=>e.removeAttribute('data-hermes-flow-replace'));"
                    f"document.querySelectorAll('.frame-trigger')[{index}].querySelector('button').setAttribute('data-hermes-flow-replace','active');return true;}})()")
            ui.click('[data-hermes-flow-replace=active]')
            ui.wait(f"!document.querySelectorAll('.frame-trigger')[{index}]?.querySelector('img')")
        labels = [frame['text'] for frame in ui.snapshot()['frames']]
        desired = next((text for text in labels if any(word in text for word in (
            ('Awal','Start','First') if slot == 'first' else ('Akhir','End','Last')))), None)
        if desired is None:
            raise ValueError('The selected model does not expose the requested frame slot')
        ui.click('.frame-trigger', desired)
    select_asset(ui, title, kind)
    selected_image = ui.read("document.querySelector('flow-add-menu-popover-content img[src*=\"/image/\"]')?.src ?? null")
    if selected_image and kind == 'image' and not slot:
        identifier = selected_image.split('/image/', 1)[1].split('?', 1)[0]
        present = ui.read("Array.from(document.querySelectorAll('flow-ingredient-bar img')).some(e=>e.src.includes(" + json.dumps('/image/' + identifier) + "))")
        if present:
            ui.execute("press_key('Escape')")
            wait_for_media(ui, 'image')
            state = ui.snapshot()
            return {'title': title, 'kind': kind, 'media_id': identifier, 'already_bound': True,
                    'ingredients': state['ingredients'], 'frames': state['frames']}
    if ui.read("!!document.querySelector('flow-add-menu-popover-content')"):
        ui.wait("(() => {const b=document.querySelector('button.detail-add-to-prompt-btn');if(!b||b.disabled)return false;"
                "const r=b.getBoundingClientRect();return r.width>0&&r.height>0&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()", 60)
        ui.click('button.detail-add-to-prompt-btn')
    tag = {'image':'image','video':'video','character':'character','voice':'audio'}[kind]
    ui.wait(f"!!document.querySelector('flow-{tag}-ingredient-chip')" if not slot
            else f"Array.from(document.querySelectorAll('.frame-trigger'))[{labels.index(desired)}]?.querySelector('img')?.naturalWidth>0", 60)
    state = ui.snapshot()
    if kind in {'image','video','character'} and not slot:
        wait_for_media(ui, tag)
        state = ui.snapshot()
    after = ui.read("Array.from(document.querySelectorAll('flow-ingredient-bar > *,flow-ingredient-bar img')).map(e=>e.outerHTML)")
    if before == after and not slot:
        raise RuntimeError('The composer did not gain the selected reference')
    value = {'title': title, 'kind': kind, 'slot': slot, 'ingredients': state['ingredients'], 'frames': state['frames'],
             'ids': [item['id'] for item in state['ingredients'] if item.get('id') and item['id'] not in before_ids]}
    if slot:
        value['frame'] = state['frames'][index]['image']
    value = verify_binding(ui, value, expected)
    receipt.write_text(json.dumps(value))
    return value
