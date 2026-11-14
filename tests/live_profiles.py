"""Native multi-profile acceptance on local fixture pages in original Chrome."""
import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hermes_bootstrap

sys._hermes_pin_default_home = False
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.session_context import scoped_session_key
from hermes_constants import set_hermes_home_override
from hermes_cli.plugins import get_plugin_manager, _dispatch_pre_tool_call_hooks, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from agent.browser_registry import get_provider
from tools.registry import registry
from tools.browser_session_lifecycle import cleanup_profile_browsers
from profiles import get_profile
from relay import ChromeSession
from startup import PERSONAL


class Fixture(BaseHTTPRequestHandler):
    pending = threading.Event()

    def do_GET(self):
        if self.path == '/pending':
            self.pending.set()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<!doctype html><title>Chrome profile fixture</title><input id=field>')

    def log_message(self, *args):
        pass


def verify():
    source = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    report = {}
    with tempfile.TemporaryDirectory(prefix='hermes-profile-acceptance-') as temporary:
        home = Path(temporary).resolve()
        (home / 'config.yaml').write_text('''browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  allow_private_urls: true
plugins:
  enabled: [original-chrome-default]
''')
        os.environ['HERMES_HOME'] = str(home)
        turns = {task: uuid.uuid4().hex for task in ('A', 'B', 'C', 'D')}
        manual = None
        with set_hermes_home_override(home):
            import tools.browser_use_cli  # Register native browser_exec in the isolated test.
            manager = get_plugin_manager()
            manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
            provider = get_provider('original-chrome-default')

            def call(task, tool='browser_exec', **arguments):
                with set_hermes_home_override(home), scoped_session_key('profile-fixture-' + task):
                    args = {'session': 'work', **arguments}
                    blocked, modified = _dispatch_pre_tool_call_hooks(
                        tool, args, task_id=task, session_id='chat-' + task,
                        turn_id=turns[task], tool_call_id=uuid.uuid4().hex)
                    assert not blocked, blocked
                    result = registry.dispatch(tool, modified or args, scope=str(home),
                                               task_id=task, session_id='chat-' + task)
                    return json.loads(result) if isinstance(result, str) else result

            def control(task, action='list', profile=None):
                result = call(task, 'chrome_profiles', action=action, profile=profile)
                assert result.get('success'), result
                return result

            def browse(task, marker):
                code = (f'goto_url({url!r})\nwait_for_element("#field", timeout=10)\n'
                        f'fill_input("#field", {marker!r})\n'
                        f'print(js("window.profileMarker="+{marker!r}.__repr__()))')
                result = call(task, code=code, timeout_s=90)
                assert result.get('success'), result
                return result

            def check(task, marker):
                result = call(task, code=f'assert js("window.profileMarker")=={marker!r}')
                assert result.get('success'), result

            def session(task):
                return next(item for item in provider.sessions.values()
                            if provider.owners[item.cache_key.removeprefix('bu-named-').split('@', 1)[0]][0] == task)

            def windows(item):
                return {item.wire.call('Browser.getWindowForTarget', {'targetId': row['targetId']})['windowId']
                        for row in item._inventory() if row.get('type') == 'page'}

            def pages():
                return {row['targetId'] for row in manual.wire.call('Target.getTargets')['targetInfos']
                        if row.get('type') == 'page'}

            try:
                inventory = control('A')['profiles']
                assert len(inventory) >= 2, 'This native test needs two existing Chrome profiles.'
                first, second = inventory[0]['id'], inventory[1]['id']
                control('A', 'set_default', first)
                selected = get_profile(first, PERSONAL)
                manual = ChromeSession(PERSONAL, first, profile_identity=selected.identity)
                manual._start()
                manual_target = next(iter(manual.owned))
                print('FIXTURE_MANUAL_TARGET=' + manual_target, flush=True)
                sid = manual.wire.call('Target.attachToTarget', {
                    'targetId': manual_target, 'flatten': True})['sessionId']
                original_pages = pages() - manual.owned
                manual.wire.call('Page.navigate', {'url': url}, sid)
                deadline = time.monotonic() + 10
                while True:
                    ready = manual.wire.call('Runtime.evaluate', {
                        'expression': "document.querySelector('#field') ? (window.manualProfileMarker='KEEP') : null",
                        'returnByValue': True}, sid).get('result', {}).get('value')
                    if ready == 'KEEP':
                        break
                    assert time.monotonic() < deadline, 'Manual fixture did not mount.'
                    time.sleep(.05)

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    list(pool.map(lambda task: browse(task, task), ('A', 'B')))
                assert session('A').profile == session('B').profile == first
                a_windows, b_windows = windows(session('A')), windows(session('B'))
                assert a_windows and b_windows and a_windows.isdisjoint(b_windows)
                report['same_profile_distinct_agent_windows'] = True

                control('C', 'select', second)
                control('D', 'set_default', second)
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    list(pool.map(lambda task: browse(task, task), ('C', 'D')))
                assert session('C').profile == session('D').profile == second
                assert session('A').profile == session('B').profile == first
                agent_windows = [windows(session(task)) for task in ('A', 'B', 'C', 'D')]
                assert all(agent_windows)
                assert all(left.isdisjoint(right) for index, left in enumerate(agent_windows)
                           for right in agent_windows[index + 1:])
                report['mixed_profiles_four_disjoint_agent_windows'] = True
                report['default_change_preserves_active_agent_profiles'] = True

                original = session('A')
                original_name = original.cache_key
                original_targets = {row['targetId'] for row in original._inventory()}
                control('A', 'select', second)
                assert original.cleanup_complete and original_targets.isdisjoint(pages())
                browse('A', 'A-second')
                middle = session('A')
                assert middle.profile == second and middle.cache_key != original_name
                middle_targets = {row['targetId'] for row in middle._inventory()}
                control('A', 'select', second)
                check('A', 'A-second')
                assert session('A') is middle
                control('A', 'select', first)
                assert middle.cleanup_complete and middle_targets.isdisjoint(pages())
                browse('A', 'A-returned')
                assert session('A').profile == first
                assert len({original_name, middle.cache_key, session('A').cache_key}) == 3
                assert provider.create_session(original_name)['bb_session_id'] == 'unloaded'
                report['round_trip_uses_fresh_connections_and_cleans_previous_windows'] = True
                report['repeated_selection_reuses_current_connection'] = True
                for task in ('B', 'C', 'D'):
                    check(task, task)

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    code = f'print(js("fetch({(url + "/pending")!r}); new Promise(r=>setTimeout(()=>r(true),15000))"))'
                    in_flight = pool.submit(call, 'A', code=code, timeout_s=30)
                    assert Fixture.pending.wait(10)
                    invoke_hook('agent_loop_stopped', session_key='profile-fixture-A',
                                platform='cli', reason='user_stop', invalidation_reason='session_interrupt')
                    assert not in_flight.result(timeout=30).get('success')
                for task in ('B', 'C', 'D'):
                    check(task, task)
                report['stop_during_command_preserves_other_profiles'] = True
                assert provider.unload()
                assert not provider.sessions and not provider.owners
                assert not provider.profile_choices and not provider.profile_routes
                assert original_pages <= pages()
                assert manual.wire.call('Runtime.evaluate', {
                    'expression': 'window.manualProfileMarker', 'returnByValue': True}, sid)['result']['value'] == 'KEEP'
                report['independent_manual_fixture_and_existing_pages_preserved'] = True
                report['all_provider_resources_released'] = True
                cleanup_profile_browsers(str(home))
                manager.unload('original-chrome-default')
                assert registry.get_entry('chrome_profiles', scope=manager.scope_key) is None
                report['profile_control_unregistered_on_unload'] = True
                manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
                provider = get_provider('original-chrome-default')
                assert control('D')['default_profile'] == second
                browse('D', 'D-reloaded')
                assert session('D').profile == second
                report['saved_default_and_native_browsing_survive_reload'] = True
            finally:
                try:
                    cleanup_profile_browsers(str(home))
                finally:
                    try:
                        provider.unload()
                        manager.unload('original-chrome-default')
                    finally:
                        try:
                            if manual is not None:
                                assert manual.close(), 'Independent manual fixture cleanup failed.'
                        finally:
                            server.shutdown()
    return report


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
