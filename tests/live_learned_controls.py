"""Original Chrome learns DOM and screenshot clicks through native Hermes browser_exec."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.browser_registry import get_provider
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_cli.plugins import get_plugin_manager, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from hermes_constants import set_hermes_home_override
from model_tools import handle_function_call
from native_windows import native_fixture_call, verify_cleanup, window_keys
from tools.browser_session_lifecycle import cleanup_profile_browsers


class Fixture(BaseHTTPRequestHandler):
    version = 1

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = f"""<!doctype html><title>Learned controls fixture</title>
<style>
body {{ margin: 0; }}
button {{ margin: 42px 0 0 85px; padding: 10px 18px; background: rgb(17,203,101); border: 0; }}
#banner {{ position: fixed; inset: 0; z-index: 100; background: #ddd; }}
</style>
<button id="details-{self.version}" aria-expanded="false" type="button">Show details</button>
<div id="banner" hidden>Fixture banner</div>
<script>
window.addEventListener('click', event => {{
  document.body.dataset.event = JSON.stringify([event.target.id, event.clientX, event.clientY]);
}});
document.querySelector('button').onclick = event => {{
  event.currentTarget.setAttribute('aria-expanded', 'true');
  document.body.dataset.clicked = event.currentTarget.id;
}};
</script>""".encode()
        if self.path.startswith('/new-controls'):
            body = b"""<!doctype html><title>Site controls</title>
<button aria-controls="options" id="open-panel" style="background:rgb(17,203,101);margin:42px">
Open options</button>
<div id="options" role="menu" hidden>Site options</div>
<a id="page-link" href="/page-do-not-persist-route"><svg width="24" height="16">
<title>Open page</title><rect width="24" height="16" /></svg><span hidden>Open page</span></a>
<a id="spa-link" href="/spa">Open settings</a>
<a id="cancel-link" href="/canceled">Canceled link</a>
<script>
document.querySelector('#open-panel').onclick = () => {
    document.querySelector('#options').hidden = false;
};
document.querySelector('#spa-link').onclick = event => {
    event.preventDefault();
    history.pushState({}, '', '/spa');
};
document.querySelector('#cancel-link').onclick = event => event.preventDefault();
</script>"""
        elif self.path == '/basic-actions':
            body = '''<!doctype html><meta charset=utf-8><title>Basic browser actions</title>
<section id="summary">
  <h1>Browser fixture</h1>
  <p class="detail">Halo dari Chrome.</p>
  <p class="detail">مرحبا</p>
  <p class="detail" hidden>Hidden fixture text</p>
</section>
<textarea id="note">start: </textarea>
<div id="inputs">
  <input class="ambiguous" value="first">
  <input class="ambiguous" value="second">
</div>
<script>
const note = document.getElementById('note');
note.addEventListener('change', () => document.body.dataset.changed = 'yes');
</script>'''.encode()
        elif self.path == '/basic-next':
            body = b'<!doctype html><title>Next browser page</title><main id="next"></main>'
        elif self.path == '/':
            body = b"""<!doctype html><title>Flow project list</title>
<flow-project-card style="display:block">
  <a class="project-thumbnail-container" aria-label="Open project" href="/project/other">Other thumbnail</a>
  <span class="project-title-text">Other project</span>
</flow-project-card>
<flow-project-card style="display:block">
  <a class="project-thumbnail-container" aria-label="Open project" href="/project/existing">Project thumbnail</a>
  <span class="project-title-text">Existing project</span>
  <button onclick="document.body.dataset.edited='yes'">Edit</button>
</flow-project-card>
<flow-project-card style="display:block">
  <a class="project-thumbnail-container" aria-label="Open project" href="/project/duplicate">Duplicate thumbnail</a>
  <span class="project-title-text">Other project</span>
</flow-project-card>
<flow-project-card style="display:block">
  <a class="project-thumbnail-container" aria-label="Open project" href="/not-a-project">Invalid thumbnail</a>
  <span class="project-title-text">Invalid project</span>
</flow-project-card>
<flow-project-card style="display:block">
  <a class="project-thumbnail-container" aria-label="Open project" href="/project/canceled"
     onclick="event.preventDefault(); document.body.dataset.canceled=String(1+Number(document.body.dataset.canceled||0))">Canceled thumbnail</a>
  <span class="project-title-text">Canceled project</span>
</flow-project-card>"""
        elif self.path.startswith('/mapped-controls') or self.path.split('?', 1)[0] in (
                '/project/existing', '/app/speech-synthesis/text-to-speech'):
            body = b"""<!doctype html><title>Packaged controls</title>
<button aria-label="Tools" onclick="document.querySelector('#tools').hidden=false">Tools</button>
<div id="tools" role="menu" hidden><span aria-label="Create image">Create image</span></div>
<button class="settings-trigger-button"
        onclick="document.querySelector('flow-prompt-box-settings').hidden=false">Settings</button>
<flow-prompt-box-settings hidden>
  <button aria-haspopup="menu" onclick="document.querySelector('#flow-models').hidden=false">Veo</button>
</flow-prompt-box-settings>
<div id="flow-models" role="menu" hidden>
  <button role="menuitem">Veo Fast</button><button role="menuitem">Veo Quality</button>
</div>
<button data-test-id="bard-mode-menu-button" aria-label="Pilih model Gemini"
        onclick="openGeminiModels()">Pro</button>
<div id="gemini-models" role="listbox" hidden>
  <div role="option" style="min-height:18px">Fast</div><div role="option" style="min-height:18px">Pro</div>
</div>
<flow-agent-panel>
  <button aria-label="Setelan agen" onclick="document.querySelector('flow-unified-settings-view').hidden=false">
    Agent settings
  </button>
</flow-agent-panel>
<flow-unified-settings-view hidden>
  <button id="image-defaults" class="image-defaults-row" onclick="document.querySelector('flow-generation-defaults-view').hidden=false">
    Image defaults
  </button>
  <button class="video-defaults-row" onclick="document.querySelector('flow-generation-defaults-view').hidden=false">
    Video defaults
  </button>
</flow-unified-settings-view>
<flow-generation-defaults-view hidden style="display:block">Agent defaults</flow-generation-defaults-view>
<style>[hidden] { display:none !important }</style>
<script>
function openGeminiModels() {
    const count = Number(document.body.dataset.modelClicks || 0);
    document.body.dataset.modelClicks = String(count + 1);
    setTimeout(() => document.querySelector('#gemini-models').hidden=false, 280);
}
</script>
<button onclick="document.body.dataset.submits=String(Number(document.body.dataset.submits || 0) + 1)">Submit</button>
"""
        if self.path.startswith('/dynamic-clicks'):
            body = b'''<!doctype html><meta charset="utf-8"><title>Unmapped effects</title>
<button id="create" onclick="openActions()">Buat</button>
<div id="welcome" role="dialog"><button onclick="dismiss(this)">Lanjutkan</button></div>
<button id="check" onclick="count('checked')">Cek saja</button>
<script>
function count(key) { document.body.dataset[key] = String(1 + Number(document.body.dataset[key] || 0)); }
function dismiss(button) { count('dismissed'); setTimeout(() => button.closest('[role=dialog]').remove(), 160); }
function openActions() {
    count('opened');
    setTimeout(() => {
        const panel = document.createElement('section');
        if (location.search) panel.id = 'changed-menu';
        panel.setAttribute('role', location.search ? 'listbox' : 'menu');
        const choice = document.createElement('button');
        choice.setAttribute('role', location.search ? 'option' : 'menuitem');
        choice.textContent = 'Upload video';
        panel.append(choice);
        document.body.append(panel);
    }, 190);
}
</script>'''
        if self.path == '/harness-actions':
            body = b'''<!doctype html><title>Harness actions</title>
<input id="edit" value="awal">
<button id="menu" aria-expanded="false" onclick="openMenu()">Open menu</button>
<output id="click-count">0</output>
<iframe id="fixture-frame" src="/fixture-frame"></iframe>
<iframe id="cross" src="http://localhost:PORT/fixture-frame"></iframe>
<div style="height:2400px">Below</div>
<script>
function openMenu() {
  document.querySelector('#menu').setAttribute('aria-expanded', 'true');
  document.querySelector('#click-count').textContent = Number(document.querySelector('#click-count').textContent)+1;
}
</script>'''.replace(b'PORT', str(self.server.server_port).encode())
        elif self.path == '/fixture-frame':
            body = b'<!doctype html><title>Frame title</title><label id="inside">Text in the owned iframe</label>'
        if self.path.startswith('/file-actions'):
            body = b'''<!doctype html><title>File input fixture</title>
<input id="direct" type="file" onchange="report(this)">
<button id="chooser" onclick="choose()" style="background:rgb(17,203,101)">Pick a file</button>
<output id="result"></output>
<script>
function choose() {
  document.body.dataset.clicks = String(1 + Number(document.body.dataset.clicks || 0));
  const input = document.createElement('input');
  input.type = 'file';
  input.hidden = true;
  input.onchange = () => report(input);
  document.body.append(input);
  input.click();
}
async function report(input) {
  const file = input.files[0];
  document.querySelector('#result').textContent = file.name + ':' + await file.text();
}
</script>'''
        if self.path == '/project/existing?late-popup':
            body += f'<script>setTimeout(() => {{ {FLOW_POPUP} }}, 160)</script>'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)


def click_from_screenshot(script, *, zoom, banner=False):
    script(f"""
from PIL import Image
cdp('Emulation.setPageScaleFactor', pageScaleFactor={zoom})
for _ in range(4):
    frame = capture_screenshot(max_dim=900)
    with Image.open(frame) as screenshot:
        width, height = screenshot.size
        pixels = screenshot.convert('RGB').get_flattened_data()
        colored = [(i % width, i // width) for i, (r, g, b) in enumerate(pixels)
                   if r < 80 and g > 155 and 65 < b < 155 and g - b > 50]
    if colored:
        break
    wait(.2)
assert colored, 'The fixture button was not visible in the screenshot.'
xs, ys = zip(*colored)
viewport = cdp('Page.getLayoutMetrics')['cssVisualViewport']
x = (min(xs) + max(xs)) / 2 * viewport['clientWidth'] / width
y = (min(ys) + max(ys)) / 2 * viewport['clientHeight'] / height
if {banner!r}:
    js("document.getElementById('banner').hidden=false")
click_at_xy(x, y)
""")


def exercise_extended(stage, extension, script, learned, url, replay):
    if extension == 'panel':
        script(f'goto_url({url!r}); wait_for_element("#open-panel", timeout=8)')
        if stage == 'learn':
            click_from_screenshot(script, zoom=1.2)
        else:
            result = learned('click', target='Open options')
            assert result.get('success'), result
        script('assert js("!document.querySelector(\'#options\').hidden")')
        if stage == 'learn':
            result = learned('list_learned_controls', label='Open options')
            assert len(result['controls']) == 1, result
            replay['Open options'] = result['controls'][0]['id']
    else:
        for selector, label, pathname in (
            ('#page-link', 'Open page', '/page-do-not-persist-route'),
            ('#spa-link', 'Open settings', '/spa'),
        ):
            script(f'goto_url({url!r}); wait_for_element({selector!r}, timeout=8)')
            if stage == 'learn':
                script(f"""js("document.querySelector({selector!r}).click()")
for _ in range(30):
    if js("location.pathname") == {pathname!r}:
        break
    wait(.1)
assert js("location.pathname") == {pathname!r}
""")
                script(f'goto_url({url!r}); wait_for_element({selector!r}, timeout=8)')
                result = learned('list_learned_controls', label=label)
                assert len(result['controls']) == 1, result
                assert result['controls'][0]['label'] == label, result
                assert result['controls'][0]['destination'] == pathname, result
                replay[label] = result['controls'][0]['id']
            else:
                result = learned('click', target=label)
                assert result.get('success'), result
                script(f'assert js("location.pathname") == {pathname!r}')
        script(f'goto_url({url!r}); wait_for_element("#cancel-link", timeout=8)')
        result = learned('list_learned_controls', label='Destination page')
        assert not result['controls'], result
        assert any(x['id'] == replay['Open page'] and x['destination'] == '/page-do-not-persist-route'
                   for x in result['suggestions']), result
        script('js("document.querySelector(\'#cancel-link\').click()")')
        destination = url.rsplit('/', 1)[0] + '/canceled'
        script(f'goto_url({destination!r}); wait_for_element("body", timeout=8)')
        script(f'goto_url({url!r}); wait_for_element("#cancel-link", timeout=8)')
        assert not learned('list_learned_controls', label='Canceled link')['controls']
        if stage == 'reuse':
            script('js("document.querySelector(\'#page-link\').href = \'/wrong-destination\'")')
            result = learned('list_learned_controls', label='Destination page')
            assert all(x['id'] != replay['Open page'] for x in result.get('suggestions', [])), result
            result = learned('click', target='Open page')
            assert result['status'] == 'needs_inspection' and not result['dispatched'], result
            script('assert js("location.pathname") == "/new-controls"')
    print('NATIVE_EXTENDED_CONTROLS_PASS', extension, stage, flush=True)


def exercise_automatic_click(stage, script, learned, url, catalog):
    from site_learning import page_key

    origin = url.split('/settings', 1)[0]
    _, page = page_key([origin, '/settings'])
    if stage == 'refresh':
        Fixture.version = 2
    script(f'goto_url({url!r}); wait_for_element("button", timeout=8)')
    payload = {'target': 'Show details'}
    result = learned('click', **payload)
    expected = {'learn': 'package', 'refresh': 'dom'}.get(stage, 'catalog')
    assert result.get('success') and result.get('dispatched') and result.get('source') == expected, result
    assert result.get('repaired', False) == (stage == 'refresh'), result
    script(f'assert js("document.body.dataset.clicked")=={("details-" + str(Fixture.version))!r}')
    control, = catalog.list(origin, page, 'Show details')
    assert control['element_id'] == 'details-' + str(Fixture.version), control
    if stage == 'reuse-after-refresh':
        missing = learned('click', target='Missing button')
        assert missing.get('source') == 'screenshot' and not missing.get('dispatched'), missing
        assert Path(missing['screenshot_path']).is_file(), missing
        mapped = origin + '/mapped-controls'
        script(f'goto_url({mapped!r}); wait_for_element("button", timeout=8)')
        for target, panel in (('Tools', '#tools'), ('Settings', 'flow-prompt-box-settings')):
            picked = learned('click', target=target)
            assert picked.get('success') and picked.get('dispatched') and picked.get('source') == 'package', picked
            script(f'assert js("!document.querySelector({panel!r}).hidden")')
            print('NATIVE_PACKAGE_ACTION_PASS', target, flush=True)
        for target, panel in (
            ('Model picker', '#gemini-models'), ('Classic model picker', '#flow-models'),
            ('Agent settings', 'flow-unified-settings-view'),
            ('Image defaults', 'flow-generation-defaults-view'),
            ('Video defaults', 'flow-generation-defaults-view'),
        ):
            picked = learned('click', target=target)
            assert picked.get('success') and picked.get('source') == 'package', picked
            script(f'assert js("!document.querySelector({panel!r}).hidden")')
            if target == 'Image defaults':
                close_defaults = "document.querySelector('flow-generation-defaults-view').hidden=true"
                script(f"js({close_defaults!r})")
            print('NATIVE_PACKAGE_ACTION_PASS', target, flush=True)
        repeat = learned('click', target='Model picker')
        assert not repeat.get('dispatched'), repeat
        script('assert js("document.body.dataset.modelClicks") == "1"')
        acted = learned('click', target='Submit')
        assert acted['dispatched'] and acted['status'] == 'needs_inspection', acted
        script('assert js("document.body.dataset.submits") == "1"')
        print('NATIVE_NO_BLIND_REPEAT_PASS', flush=True)
    print('NATIVE_AUTOMATIC_CLICK_PASS', stage, expected, flush=True)


def exercise_flow_project_title(script, learned, origin, provider):
    assert learned('navigate', url=origin + '/')['success']
    script('assert wait_for_element("flow-project-card", timeout=8)')
    owned, = provider.sessions.values()
    loading = """(() => {
      const veil = document.createElement('flow-loading-page');
      veil.style.cssText = 'position:fixed;inset:0;z-index:10';
      document.body.append(veil);
      setTimeout(() => veil.remove(), 950);
    })()"""
    script(f'js({loading!r})')
    result = learned('click', target='Existing project')
    assert result.get('success') and result.get('source') == 'package' and result.get('dispatched'), result
    script('assert js("location.pathname") == "/project/existing"')
    settings = learned('click', target='Settings')
    assert settings.get('success') and settings.get('source') == 'package', settings
    script('assert js("!document.querySelector(\'flow-prompt-box-settings\').hidden")')
    assert learned('navigate', url=origin + '/')['success']
    for title in ('Other project', 'Invalid project'):
        rejected = learned('click', target=title)
        assert not rejected.get('success') and not rejected.get('dispatched'), rejected
        script('assert js(\'location.pathname === "/" && !document.body.dataset.edited\')')
    pending = learned('click', target='Canceled project')
    assert pending.get('dispatched') and not pending.get('success') and not pending.get('screenshot_id'), pending
    script('assert js("document.body.dataset.canceled") == "1"')
    assert list(provider.sessions.values()) == [owned]
    print('NATIVE_FLOW_PROJECT_TITLE_PASS', flush=True)


FLOW_POPUP = """document.body.insertAdjacentHTML('beforeend', `
      <mat-dialog-container role="dialog"><h2>Yang baru</h2>
        <a href="/changelogs/example">Lihat semua log perubahan</a>
        <button onclick="document.body.dataset.dismissed='flow';this.closest('mat-dialog-container').remove()">Mulai</button>
      </mat-dialog-container>`)"""


def exercise_site_popups(script, learned, origin):
    assert learned('navigate', url=origin + '/project/existing?late-popup')['success']
    script('assert js("document.body.dataset.dismissed") == "flow", "navigation left the changelog popup open"')
    assert learned('navigate', url=origin + '/project/existing')['success']
    script('assert wait_for_element(".settings-trigger-button", timeout=8)')
    script(f'js({FLOW_POPUP!r})')
    script('js("document.querySelector(\'mat-dialog-container\').append(document.querySelector(\'mat-dialog-container button\').cloneNode(true))")')
    blocked = learned('click', target='Settings')
    assert blocked['status'] == 'needs_inspection' and blocked['source'] == 'popup' and not blocked['dispatched'], blocked
    script('assert js("!document.body.dataset.dismissed && document.querySelector(\'flow-prompt-box-settings\').hidden")')
    script('js("document.querySelector(\'mat-dialog-container button:last-child\').remove()")')
    assert learned('click', target='Settings')['success']
    script('assert js("document.body.dataset.dismissed") == "flow"')
    script('assert js("!document.querySelector(\'flow-prompt-box-settings\').hidden")')

    eleven = """document.body.insertAdjacentHTML('beforeend', `
      <section><h2>Introducing Eleven v4</h2>
        <button onclick="document.body.dataset.order='intro';this.parentElement.remove()">Got it</button></section>
      <aside><button>Try Studio</button>
        <button aria-label="Close popup" onclick="document.body.dataset.order+=',studio';this.parentElement.remove()">×</button></aside>
      <div id="first-promo">Black Friday <a href="/offer">Get the offer</a>
        <button aria-label="Dismiss" onclick="document.body.dataset.order+=',black-friday';document.querySelector('#next-promo').hidden=false;this.parentElement.remove()">×</button></div>
      <div id="next-promo" hidden>Eleven v4 is here <a href="/intro">Try it out</a>
        <button aria-label="Dismiss" onclick="document.body.dataset.order+=',v4';this.parentElement.remove()">×</button></div>`)"""
    assert learned('navigate', url=origin + '/app/speech-synthesis/text-to-speech')['success']
    script('assert wait_for_element(".settings-trigger-button", timeout=8)')
    script(f'js({eleven!r})')
    assert learned('click', target='Settings')['success']
    script('assert js("document.body.dataset.order") == "intro,studio,black-friday,v4"')
    script('assert js("!document.querySelector(\'flow-prompt-box-settings\').hidden")')
    print('NATIVE_SITE_POPUP_ORDER_PASS', flush=True)


def exercise_dynamic_clicks(script, learned, origin):
    url = origin + '/dynamic-clicks'
    assert learned('navigate', url=url)['success']
    script('assert wait_for_element("#welcome button", timeout=8)')
    dismissed = learned('click', target='Lanjutkan')
    assert dismissed.get('success') and dismissed.get('source') == 'dom', dismissed
    opened = learned('click', target='Buat')
    assert opened.get('success') and opened.get('source') == 'dom', opened
    script('assert js("document.body.dataset.dismissed") == "1"')
    script('assert js("document.body.dataset.opened") == "1"')

    assert learned('navigate', url=url)['success']
    script('assert wait_for_element("#welcome button", timeout=8)')
    for target, previous in [('Lanjutkan', dismissed), ('Buat', opened)]:
        result = learned('click', target=target)
        assert result.get('success') and result.get('source') == 'catalog', result
        assert result['control'] == previous['control'], result
    untouched = learned('click', target='Cek saja')
    assert untouched.get('reason') == 'unconfirmed' and untouched.get('dispatched'), untouched
    assert not learned('list_learned_controls', label='Cek saja')['controls']
    script('assert js("document.body.dataset.checked") == "1"')

    assert learned('navigate', url=url + '?changed')['success']
    script('assert wait_for_element("#create", timeout=8)')
    repaired = learned('click', target='Buat')
    assert repaired.get('success') and repaired.get('repaired'), repaired
    assert repaired['control'] == opened['control'], repaired
    script('assert js("document.body.dataset.opened") == "1"')

    assert learned('navigate', url=url + '-visual')['success']
    script('assert wait_for_element("#create", timeout=8)')
    script("""x,y=js("(() => {const r=document.querySelector('#create').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
click_at_xy(x, y)""")
    assert learned('list_learned_controls', label='Buat')['controls']
    script('assert js("document.body.dataset.opened") == "1"')
    print('NATIVE_DYNAMIC_MENU_AND_DISMISS_PASS', flush=True)


def exercise_upload(script, learned, origin, home):
    from PIL import Image
    url = origin + '/file-actions'
    sample = home / 'sample.txt'
    sample.write_text('fixture file')
    assert learned('navigate', url=url)['success']
    script('assert wait_for_element("#direct", timeout=8)')
    result = learned('upload', path=str(sample))
    assert result.get('success') and result.get('status') == 'file_selected', result
    script('assert js("document.querySelector(\'#result\').textContent") == "sample.txt:fixture file"')

    assert learned('navigate', url=url)['success']
    script('assert wait_for_element("#chooser", timeout=8)')
    result = learned('upload', path=str(sample), target='Pick a file')
    assert result.get('success') and result.get('status') == 'file_selected', result
    script('assert js("document.body.dataset.clicks") == "1"')
    script('assert js("document.querySelector(\'#result\').textContent") == "sample.txt:fixture file"')
    ambiguous = learned('upload', path=str(sample))
    assert ambiguous['status'] == 'choose_file_target' and not ambiguous['dispatched'], ambiguous

    assert learned('navigate', url=url)['success']
    script('assert wait_for_element("#chooser", timeout=8)')
    upload = learned('upload', path=str(sample), target='Select the asset')
    if upload.get('_multimodal'):
        upload = json.loads(upload['text_summary'])
    assert upload.get('source') == 'screenshot' and not upload.get('dispatched'), upload
    with Image.open(upload['screenshot_path']) as screenshot:
        width, height = screenshot.size
        points = [(i % width, i // width) for i, (r, g, b) in enumerate(screenshot.convert('RGB').get_flattened_data())
                  if r < 80 and g > 155 and 65 < b < 155 and g - b > 50]
    xs, ys = zip(*points)
    point = [(min(xs) + max(xs)) / (2 * width), (min(ys) + max(ys)) / (2 * height)]
    args = dict(target='Select the asset', screenshot_id=upload['screenshot_id'], point=point)
    result = learned('click', **args)
    assert result.get('success') and result.get('status') == 'file_selected', result
    assert not learned('click', **args).get('dispatched')
    script('assert js("document.body.dataset.clicks") == "1"')
    print('NATIVE_GENERIC_FILE_CHOOSER_PASS', flush=True)


def exercise_harness_actions(script, learned, origin, home):
    def action(name, **params):
        result = learned(name, **params)
        assert result.get('success'), result
        return json.loads(result.get('output') or '{}')

    url = origin + '/harness-actions'
    assert learned('navigate', url=url)['success']
    assert action('wait', mode='element', selector='#edit', visible=True)['ready']
    assert action('page_info')['url'] == url
    assert action('inspect', selector='#edit')['elements'][0]['attributes']['id'] == 'edit'
    assert action('read', frame='#fixture-frame', selector='#inside')['text'] == 'Text in the owned iframe'
    assert action('read', frame='#cross', selector='#inside')['text'] == 'Text in the owned iframe'
    assert isinstance(action('events')['events'], list)

    assert learned('type', selector='#edit', text='A')['success']
    assert learned('press_key', key='End')['success']
    assert learned('press_key', key='b')['success']
    script('assert js("document.querySelector(\'#edit\').value") == "Ab"')
    script('js("document.querySelector(\'#menu\').focus()")')
    key_click = learned('press_key', key='Enter')
    assert key_click.get('success') and key_click.get('source') == 'dom', key_click
    script('assert js("document.querySelector(\'#click-count\').textContent") == "1"')
    assert learned('list_learned_controls', label='Open menu')['controls']

    assert learned('scroll', dy=420)['success']
    script('wait(.3); assert js("window.scrollY") > 0')
    output = home / 'full-page.png'
    shot = learned('screenshot', full=True, max_dim=900, path=str(output))
    if shot.get('_multimodal'):
        shot = json.loads(shot['text_summary'])
    assert shot.get('success') and output.is_file(), shot

    first = action('tabs', mode='current')['target_id']
    second = action('tabs', mode='open', url=origin + '/fixture-frame')['target_id']
    assert second != first
    tabs = action('tabs', mode='list')['tabs']
    assert {tab['target_id'] for tab in tabs} == {first, second}
    script(f'''a=cdp("Browser.getWindowForTarget", targetId={first!r})['windowId']
b=cdp("Browser.getWindowForTarget", targetId={second!r})['windowId']
assert a == b''')
    action('tabs', mode='switch', target_id=first)
    action('tabs', mode='close', target_id=second)
    assert len(action('tabs', mode='list')['tabs']) == 1
    print('NATIVE_HARNESS_ACTIONS_PASS', flush=True)


def exercise_basic_actions(mode, script, learned, origin, provider):
    url = origin + '/basic-actions'
    next_url = origin + '/basic-next'
    first = 'Note: "halo"'
    appended = " / صباح الخير"

    def navigate(address):
        if mode == 'structured':
            result = learned('navigate', url=address)
            assert result.get('success'), result
        else:
            script(f"navigation = goto_url({address!r}); assert not navigation.get('errorText')")

    def type_note(text, clear_first=True):
        if mode == 'structured':
            result = learned('type', selector='#note', text=text, clear_first=clear_first)
            assert result.get('success'), result
        else:
            script(f"fill_input('#note', {text!r}, clear_first={clear_first!r})")

    navigate(url)
    script('assert wait_for_element("#note", timeout=8); assert js("document.title").endswith("Basic browser actions")')
    owned, = provider.sessions.values()

    def read_page(**params):
        result = learned('read', **params)
        assert result.get('success'), result
        return json.loads(result['output'])

    full = json.loads(script('import json; print(json.dumps(js("document.body.innerText").strip()))')['output'])
    assert 'Halo dari Chrome.' in full and 'Hidden fixture text' not in full
    if mode == 'structured':
        result = read_page()
        assert result['title'].endswith('Basic browser actions') and result['text'] == full, result
        assert result['found'] and not result['truncated'], result

    details_expression = "Array.from(document.querySelectorAll('.detail:not([hidden])'), e => e.innerText)"
    details = json.loads(script(f'import json; print(json.dumps(js({details_expression!r})))')['output'])
    assert details == ['Halo dari Chrome.', 'مرحبا']
    if mode == 'structured':
        scoped = read_page(selector='.detail')
        assert scoped['text'] == '\n'.join(details) and scoped['found'], scoped
        hidden = read_page(selector='p[hidden]')
        assert hidden['text'] == '' and not hidden['found'], hidden
        script("""js("document.querySelector('#summary').textContent = 'abc'.repeat(1700)")""")
        long_page = read_page(selector='#summary')
        assert len(long_page['text']) == 4000 and long_page['truncated'], long_page['truncated']

    value = "document.getElementById('note').value"
    type_note(first)
    script(f'assert js({value!r}) == {first!r}')
    type_note(appended, clear_first=False)
    script('assert js("document.body.dataset.changed") == "yes"')
    script(f'assert js({value!r}) == {(first + appended)!r}')
    if mode == 'structured':
        result = learned('type', selector='.ambiguous', text='wrong field')
        assert not result.get('success'), result
        values = "Array.from(document.querySelectorAll('.ambiguous'), e => e.value)"
        script(f'assert js({values!r}) == ["first", "second"]')
    navigate(next_url)
    script('assert wait_for_element("#next", timeout=8); assert js("document.title").endswith("Next browser page")')
    assert list(provider.sessions.values()) == [owned]
    print('NATIVE_BASIC_ACTIONS_PASS', mode, flush=True)


def exercise_visual_continuation(script, learned, url, provider):
    target = 'Open the details panel'
    script(f'goto_url({url!r}); assert wait_for_element("button", timeout=8)')
    script("cdp('Emulation.setPageScaleFactor', pageScaleFactor=1.25)")
    owned, = provider.sessions.values()

    def frame():
        result = learned('click', target=target)
        if result.get('_multimodal'):
            result = json.loads(result['text_summary'])
        assert result.get('source') == 'screenshot' and not result.get('dispatched'), result
        assert result.get('screenshot_id'), result
        from PIL import Image
        with Image.open(result['screenshot_path']) as shot:
            width, height = shot.size
            pixels = shot.convert('RGB').get_flattened_data()
            green = [(idx % width, idx // width) for idx, (r, g, b) in enumerate(pixels)
                     if r < 80 and g > 155 and 65 < b < 155 and g - b > 50]
        assert green
        xs, ys = zip(*green)
        return dict(target=target, screenshot_id=result['screenshot_id'],
                    point=[(min(xs) + max(xs)) / (2 * width), (min(ys) + max(ys)) / (2 * height)])

    intent = frame()
    script("""js("document.getElementById('banner').hidden=false")""")
    stale = learned('click', **intent)
    assert not stale.get('dispatched') and stale.get('reason') == 'stale_screenshot', stale
    script('assert not js("document.body.dataset.clicked")')
    assert not learned('list_learned_controls')['controls']
    script("""js("document.getElementById('banner').hidden=true")""")

    fresh = frame()
    incorrect = learned('click', **{**fresh, 'target': 'A different action'})
    assert not incorrect.get('dispatched'), incorrect
    result = learned('click', **fresh)
    assert result.get('source') == 'screenshot' and result.get('dispatched'), result
    script('assert js("document.body.dataset.clicked") == "details-1"')
    row, = learned('list_learned_controls', label='Show details')['controls']
    duplicate = learned('click', **fresh)
    assert not duplicate.get('dispatched'), duplicate
    script(f'goto_url({url!r}); assert wait_for_element("button", timeout=8)')
    replayed = learned('click', target='Show details')
    assert replayed.get('success') and replayed.get('source') == 'catalog' and replayed.get('control') == row['id'], replayed
    assert list(provider.sessions.values()) == [owned]
    print('NATIVE_VISUAL_CONTINUATION_PASS', flush=True)


def exercise(*, visual=False, extension=None, automatic=False, basic=None, visual_continuation=False):
    Fixture.version = 1
    source = Path(__file__).resolve().parents[1]
    before = window_keys()
    with ThreadingHTTPServer(('127.0.0.1', 0), Fixture) as server, tempfile.TemporaryDirectory() as temp:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        url = origin + ('/new-controls' if extension else '/settings?private=must-not-be-persisted')
        home = Path(temp).resolve()
        if automatic or basic in ('flow-project-title', 'site-popups'):
            package = home / 'browser-apps' / 'fixture'
            package.mkdir(parents=True)
            (package / 'app.json').write_text(json.dumps({
                'api_version': 1, 'id': 'fixture', 'name': 'Fixture', 'operations': {},
                'click_targets': {'origin': origin,
                                  'controls': {'Show details': {'selector': '#details-1'}}},
            }))
            (package / 'app.py').write_text('def run(context, operation, params):\n    raise RuntimeError("Unexpected package operation")\n')
            for app in ('gemini', 'flow'):
                bundled = json.loads((source / 'site_apps' / app / 'app.json').read_text())
                bundled['click_targets']['origin'] = origin
                fixture = package.parent / app
                fixture.mkdir()
                (fixture / 'app.json').write_text(json.dumps(bundled))
                (fixture / 'app.py').write_text('def run(context, operation, params):\n    raise RuntimeError("Unexpected package operation")\n')
        (home / 'config.yaml').write_text('''browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  allow_private_urls: true
  inactivity_timeout: 600
plugins:
  enabled: [original-chrome-default]
  entries:
    original-chrome-default:
      granted_capabilities: [tools.override]
''')
        provider = None
        try:
            with set_hermes_home_override(home):
                manager = get_plugin_manager()
                manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
                provider = get_provider('original-chrome-default')
                control = None
                replay = {}
                stages = ('basic',) if basic or visual_continuation else (
                    ('learn', 'reuse') if extension else ('learn', 'reuse', 'refresh', 'reuse-after-refresh')
                )
                for stage in stages:
                    owner = uuid.uuid4().hex
                    turn = uuid.uuid4().hex
                    tokens = set_session_vars(platform='cli', session_key=owner, session_id=owner)

                    def call(**args):
                        result = handle_function_call(
                            'browser_exec', {'session': 'settings', **args}, task_id=owner,
                            session_id=owner, turn_id=turn, tool_call_id=uuid.uuid4().hex,
                        )
                        return json.loads(result) if isinstance(result, str) else result

                    def script(code):
                        # The fixture arranges and inspects the page with the original native handler.
                        result = native_fixture_call(provider, owner, owner, turn,
                                                     {'session': 'settings', 'code': code})
                        result = json.loads(result) if isinstance(result, str) else result
                        assert result.get('success'), result
                        return result

                    def learned(action, **params):
                        return call(site_control=json.dumps({'action': action, 'params': params}))

                    try:
                        if visual_continuation:
                            exercise_visual_continuation(script, learned, url, provider)
                            continue
                        if basic:
                            if basic == 'flow-project-title':
                                exercise_flow_project_title(script, learned, origin, provider)
                                continue
                            if basic == 'dynamic-clicks':
                                exercise_dynamic_clicks(script, learned, origin)
                                continue
                            if basic == 'file-actions':
                                exercise_upload(script, learned, origin, home)
                                continue
                            if basic == 'harness-actions':
                                exercise_harness_actions(script, learned, origin, home)
                                continue
                            if basic == 'site-popups':
                                module = sys.modules.get(type(provider).__module__.rsplit('.', 1)[0] + '.site_popups')
                                if module:
                                    with patch.dict(module.SITE_ORIGINS, flow=origin, elevenlabs=origin):
                                        exercise_site_popups(script, learned, origin)
                                else:
                                    exercise_site_popups(script, learned, origin)
                                continue
                            if basic == 'structured':
                                direct = call(code='click_at_xy(10, 10)')
                                assert not direct.get('success'), direct
                                old_click = learned('click_learned_control', control='1' * 24)
                                assert not old_click.get('success'), old_click
                            exercise_basic_actions(basic, script, learned, origin, provider)
                            continue
                        if automatic:
                            exercise_automatic_click(stage, script, learned, url, provider.learning_catalog())
                            continue
                        if extension:
                            exercise_extended(stage, extension, script, learned, url, replay)
                            continue
                        script(f'goto_url({url!r}); wait_for_element("button", timeout=8)')
                        if stage == 'learn':
                            first = learned('list_learned_controls')
                            assert first.get('success') and not first['controls'], first
                            if visual:
                                click_from_screenshot(script, zoom=1.25, banner=True)
                                script('assert not js("document.body.dataset.clicked")')
                                assert not learned('list_learned_controls')['controls']
                                script('js("document.getElementById(\'banner\').hidden=true")')
                        if stage in ('reuse', 'reuse-after-refresh'):
                            if stage == 'reuse':
                                script(f'goto_url({(origin + "/other")!r}); wait_for_element("button", timeout=8)')
                                other = learned('list_learned_controls', label='Show details')
                                assert not other['controls'], other
                                script('assert not js("document.body.dataset.clicked")')
                                script(f'goto_url({url!r}); wait_for_element("button", timeout=8)')
                            if visual:
                                script("cdp('Emulation.setPageScaleFactor', pageScaleFactor=1.1)")
                                script('js("document.getElementById(\'banner\').hidden=false")')
                                obscured = learned('click', target='Show details')
                                assert obscured.get('reason') == 'obscured' and not obscured['dispatched'], obscured
                                script('assert not js("document.body.dataset.clicked")')
                                script('js("document.getElementById(\'banner\').hidden=true")')
                            result = learned('click', target='Show details')
                            assert result.get('success') and result['status'] == 'ok', result
                        else:
                            if visual:
                                click_from_screenshot(script, zoom=1.4 if stage == 'learn' else 1.2)
                                script(f'assert js("document.body.dataset.clicked")=={("details-" + str(Fixture.version))!r}, js("document.body.dataset.event")')
                            else:
                                script('js("document.querySelector(\'button\').click()")')
                            listing = learned('list_learned_controls')
                            if visual:
                                deadline = time.monotonic() + 5
                                while listing.get('success') and not listing['controls'] and time.monotonic() < deadline:
                                    time.sleep(.1)
                                    listing = learned('list_learned_controls')
                            assert listing.get('success'), listing
                            assert listing['site'] == origin and listing['site_name'] == '127.0.0.1', listing
                            assert len(listing['controls']) == 1, listing
                            row, = listing['controls']
                            assert row['label'] == 'Show details', listing
                            assert control is None or row['id'] == control
                            control = row['id']
                        script(f'assert js("document.body.dataset.clicked")=={("details-" + str(Fixture.version))!r}')
                        print('NATIVE_LEARNED_CONTROL_PASS', 'visual' if visual else 'dom', stage, flush=True)
                    finally:
                        invoke_hook('on_session_end', task_id=owner, session_id=owner, turn_id=turn,
                                    completed=True, failed=False, interrupted=False)
                        clear_session_vars(tokens)
                    assert not provider.sessions
                    if stage == 'reuse':
                        Fixture.version = 2
                if not basic:
                    path, = list(home.rglob('learned-controls.sqlite3'))
                    assert b'must-not-be-persisted' not in path.read_bytes()
                    assert b'page-do-not-persist-route' not in path.read_bytes()
                    with sqlite3.connect(path) as db:
                        assert db.execute('SELECT origin, name FROM sites').fetchall() == [(origin, '127.0.0.1')]
        finally:
            try:
                if provider is not None:
                    with set_hermes_home_override(home):
                        assert provider.unload()
                        cleanup_profile_browsers(str(home))
                        manager.unload('original-chrome-default')
            finally:
                server.shutdown()
        verify_cleanup(before)


if __name__ == '__main__':
    exercise()


class NativeLearnedControls(unittest.TestCase):
    def test_supported_native_helpers_share_the_task_window(self):
        exercise(basic='harness-actions')

    def test_native_upload_existing_input_and_one_named_chooser(self):
        exercise(basic='file-actions')

    def test_browser_learns_delayed_menu_and_dialog_dismissal_without_package(self):
        exercise(basic='dynamic-clicks')

    def test_browser_handles_site_popups_before_page_controls(self):
        exercise(basic='site-popups')

    def test_browser_opens_a_flow_project_by_title(self):
        exercise(basic='flow-project-title')

    def test_named_click_continues_from_a_fresh_screenshot(self):
        exercise(visual_continuation=True)

    def test_native_navigation_reading_and_typing(self):
        exercise(basic='legacy')

    def test_browser_navigates_reads_and_types_through_structured_actions(self):
        exercise(basic='structured')

    def test_browser_picks_repairs_and_reuses_a_control_in_one_action(self):
        exercise(automatic=True)

    def test_browser_learns_extended_navigation(self):
        exercise(extension='navigation')

    def test_browser_learns_extended_panel(self):
        exercise(extension='panel')

    def test_browser_learns_reuses_and_refreshes_site_control(self):
        exercise()

    def test_browser_learns_from_screenshot_click_at_zoom(self):
        exercise(visual=True)
