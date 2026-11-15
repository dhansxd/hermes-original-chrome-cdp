"""Native media picker actions and portable local reference files."""
import hashlib
import json
import shutil
import time
from pathlib import Path


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


def find_asset(ui, title):
    ui.fill('flow-add-menu-popover-content input.search-input', title)
    expression = "(() => {const matches=Array.from(document.querySelectorAll('flow-add-menu-popover-content button.asset-item'))"
    expression += f".filter(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(title)});"
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
    destination = files / (digest + source.suffix.lower())
    if not destination.exists():
        shutil.copyfile(source, destination)
    key = hashlib.sha256((ui.context.profile + ui.read('location.pathname') + digest).encode()).hexdigest()
    receipt = files / (key + '.json')
    value = {'path': str(destination), 'sha256': digest, 'title': destination.name}
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved.get('complete'):
            return value
        if saved.get('version') != 2 or saved.get('assignment_intent'):
            # A previous call may have already uploaded the file. Reconcile its exact unique title.
            picker(ui)
            find_asset(ui, destination.name)
            receipt.write_text(json.dumps({**value, 'complete': True}))
            ui.execute("press_key('Escape')")
            return value
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
    deadline=time.monotonic()+10
    while True:
        chooser=next((e['params'] for e in drain_events() if e.get('method')=='Page.fileChooserOpened'),None)
        if chooser:
            state=json.loads(receipt.read_text())
            state['assignment_intent']=True
            receipt.write_text(json.dumps(state))
            cdp('DOM.setFileInputFiles',backendNodeId=chooser['backendNodeId'],files=[{str(destination)!r}])
            break
        if time.monotonic()>=deadline:
            raise RuntimeError('Flow did not open its native upload chooser')
        wait(.1)
finally:
    cdp('Page.setInterceptFileChooserDialog',enabled=False)
''')
    # Rights acknowledgement belongs to this authorized upload when Flow presents it.
    deadline = time.monotonic() + 60
    picker(ui)
    while True:
        rights = ui.read("Array.from(document.querySelectorAll('[role=dialog]')).some(e=>/Hak untuk menggunakan|Rights to use/.test(e.innerText))")
        if rights:
            buttons = ui.read("Array.from(document.querySelectorAll('[role=dialog] button')).map(e=>e.innerText.trim())")
            agree = next((text for text in buttons if text in {'Saya setuju','I agree'}), None)
            if not agree:
                raise RuntimeError('The upload rights dialog changed')
            ui.click('[role=dialog] button', agree)
        found = ui.read("Array.from(document.querySelectorAll('flow-add-menu-popover-content button.asset-item'))"
            f".some(e=>e.querySelector('.asset-title')?.textContent.trim()==={json.dumps(destination.name)} && !/Mengupload|Uploading/.test(e.innerText))")
        if found:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Observe the original upload before uploading this file again')
        time.sleep(.5)
    ui.execute("press_key('Escape')")
    receipt.write_text(json.dumps({**value, 'complete': True}))
    return value


def bind(ui, title, kind='image', slot=None):
    if kind not in {'image','video','character','voice'}:
        raise ValueError('Reference kind must be image, video, character or voice')
    state = ui.snapshot()
    key = hashlib.sha256(json.dumps([ui.context.profile,state['url'],title,kind,slot]).encode()).hexdigest()
    receipt = ui.context.directory / 'references' / ('binding-' + key + '.json')
    receipt.parent.mkdir(exist_ok=True)
    saved = json.loads(receipt.read_text()) if receipt.exists() else {}
    present = {item['id'] for item in state['ingredients'] if item.get('id') and item['ready']}
    if saved.get('ids') and set(saved['ids']).issubset(present) and not slot:
        return {**saved, 'already_bound': True}
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
            ui.wait("Array.from(document.querySelectorAll('flow-image-ingredient-chip img')).every(e=>e.complete&&e.naturalWidth>0)", 60)
            state = ui.snapshot()
            return {'title': title, 'kind': kind, 'media_id': identifier, 'already_bound': True,
                    'ingredients': state['ingredients'], 'frames': state['frames']}
    if ui.read("!!document.querySelector('flow-add-menu-popover-content')"):
        ui.click('button.detail-add-to-prompt-btn')
    tag = {'image':'image','video':'video','character':'character','voice':'audio'}[kind]
    ui.wait(f"!!document.querySelector('flow-{tag}-ingredient-chip')" if not slot
            else f"Array.from(document.querySelectorAll('.frame-trigger'))[{labels.index(desired)}]?.querySelector('img')?.naturalWidth>0", 60)
    state = ui.snapshot()
    if kind == 'image' and not slot and not all(item['ready'] for item in state['ingredients']):
        ui.wait("Array.from(document.querySelectorAll('flow-image-ingredient-chip img')).every(e=>e.complete&&e.naturalWidth>0)", 60)
        state = ui.snapshot()
    after = ui.read("Array.from(document.querySelectorAll('flow-ingredient-bar > *,flow-ingredient-bar img')).map(e=>e.outerHTML)")
    if before == after and not slot:
        raise RuntimeError('The composer did not gain the selected reference')
    value = {'title': title, 'kind': kind, 'slot': slot, 'ingredients': state['ingredients'], 'frames': state['frames'],
             'ids': [item['id'] for item in state['ingredients'] if item.get('id') and item['id'] not in before_ids]}
    if slot:
        value['frame'] = state['frames'][index]['image']
    receipt.write_text(json.dumps(value))
    return value
