"""Original Chrome learns DOM and screenshot clicks through native Hermes browser_exec."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.browser_registry import get_provider
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_cli.plugins import get_plugin_manager, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from hermes_constants import set_hermes_home_override
from model_tools import handle_function_call
from native_windows import verify_cleanup, window_keys
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


def exercise(*, visual=False):
    Fixture.version = 1
    source = Path(__file__).resolve().parents[1]
    before = window_keys()
    with ThreadingHTTPServer(('127.0.0.1', 0), Fixture) as server, tempfile.TemporaryDirectory() as temp:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        url = origin + '/settings?private=must-not-be-persisted'
        home = Path(temp).resolve()
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
                for stage in ('learn', 'reuse', 'refresh', 'reuse-after-refresh'):
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
                        result = call(code=code)
                        assert result.get('success'), result
                        return result

                    def learned(action, **params):
                        return call(site_control=json.dumps({'action': action, 'params': params}))

                    try:
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
                                other = learned('click_learned_control', control=control)
                                assert other['status'] == 'needs_inspection' and not other['dispatched'], other
                                script('assert not js("document.body.dataset.clicked")')
                                script(f'goto_url({url!r}); wait_for_element("button", timeout=8)')
                            if visual:
                                script("cdp('Emulation.setPageScaleFactor', pageScaleFactor=1.1)")
                                script('js("document.getElementById(\'banner\').hidden=false")')
                                obscured = learned('click_learned_control', control=control)
                                assert obscured.get('reason') == 'obscured' and not obscured['dispatched'], obscured
                                script('assert not js("document.body.dataset.clicked")')
                                script('js("document.getElementById(\'banner\').hidden=true")')
                            result = learned('click_learned_control', control=control)
                            assert result.get('success') and result['status'] == 'ok', result
                        else:
                            if stage == 'refresh':
                                missed = learned('click_learned_control', control=control)
                                assert missed['status'] == 'needs_inspection' and not missed['dispatched'], missed
                                assert not learned('list_learned_controls')['controls']
                                script('assert not js("document.body.dataset.clicked")')
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
                path, = list(home.rglob('learned-controls.sqlite3'))
                assert b'must-not-be-persisted' not in path.read_bytes()
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
    def test_browser_learns_reuses_and_refreshes_site_control(self):
        exercise()

    def test_browser_learns_from_screenshot_click_at_zoom(self):
        exercise(visual=True)
