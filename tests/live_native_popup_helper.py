"""Native-dialog candidate on disposable Chrome; never installed/native acceptance.

POPUP_HELPER=1 tests explicit native answers while CDP is pending. Without it,
the read-only monitor preserves the early-popup failure with a longer test budget.
All credentials are synthetic and remain in this process and its browser socket.
"""
import ctypes as c
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home() / '.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
from observer import ScopedObserver
from worker import Wire
from consent import AX, ConsentError
import psutil


class NativeSnapshot(AX):
    """Read only the disposable Chrome PID's native controls, not page content."""
    def __init__(self, pid):
        super().__init__()
        self.pid = pid
        self.cf.CFGetTypeID.restype = c.c_ulong
        self.cf.CFGetTypeID.argtypes = [c.c_void_p]
        self.cf.CFStringGetTypeID.restype = c.c_ulong
        self.cf.CFStringGetTypeID.argtypes = []
        self.ax.AXUIElementSetAttributeValue.restype = c.c_int
        self.ax.AXUIElementSetAttributeValue.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p]
        self.elements = {}

    def text(self, node, name):
        try:
            value = self.attr(node, name)
        except ConsentError as exc:
            if str(exc) == 'consent_ax_read:-25200' and name in {'AXTitle', 'AXDescription', 'AXValue', 'AXIdentifier', 'AXSubrole'}:
                return ''
            raise
        if not value or self.cf.CFGetTypeID(value) != self.cf.CFStringGetTypeID():
            return ''
        buf = c.create_string_buffer(8192)
        return buf.value.decode() if self.cf.CFStringGetCString(value, buf, len(buf), 0x08000100) else ''

    def scan(self):
        self.clear()
        self.elements = {}
        app = self.ax.AXUIElementCreateApplication(self.pid)
        self.refs.append(app)
        self.ax.AXUIElementSetMessagingTimeout(app, .2)
        windows = self.attr(app, 'AXWindows')
        roots = [self.cf.CFArrayGetValueAtIndex(windows, i) for i in range(self.cf.CFArrayGetCount(windows))] if windows else []
        def walk(node, depth):
            role = self.text(node, 'AXRole')
            key = self.cf.CFHash(node)
            self.elements[key] = node
            item = {'role': role, 'key': key}
            for name in ('AXTitle', 'AXDescription', 'AXValue', 'AXIdentifier', 'AXSubrole'):
                value = self.text(node, name)
                if value:
                    item[name] = value
            if depth < 10 and role not in {'AXWebArea', 'AXScrollArea'}:
                item['children'] = [walk(child, depth + 1) for child in self.children(node)]
            return item
        return [walk(window, 0) for window in roots]


def nodes(node):
    yield node
    for child in node.get('children', []):
        yield from nodes(child)


def main():
    case = os.environ.get('POPUP_CASE', 'page_alert')
    integrated = os.environ.get('POPUP_INTEGRATED') == '1'
    use_helper = os.environ.get('POPUP_HELPER') == '1' and not integrated
    assert case in ('page_alert', 'write_alert')
    evidence = Path(os.environ['POPUP_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='native-popup-', dir=Path.home() / '.hermes/cache/scratch'))
    data = work / 'data'
    data.mkdir()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
        def do_GET(self):
            body = (b'<title>Native popup candidate</title><script>window.before=1;window.answer=prompt("popup-load-prompt","initial");window.after=1</script>'
                    if self.path == '/alert' else b'<title>Native popup parent</title><label>Password<input id="pw" type="password" autocomplete="current-password"></label>')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    expected_message = 'popup-load-prompt' if case == 'page_alert' else 'write-prompt'
    answer = 'native-helper-answer'
    suffix = '-integrated.json' if integrated else ('-native-helper.json' if use_helper else '-native-baseline.json')
    p = ChromeProvider(data=data, workspace=work / 'work')
    control = None
    peer_target = comparator = peer_window = comparator_window = None
    peer_before = comparator_before = {}
    baseline = {}
    monitor = None
    stop = threading.Event()
    helper_ready = threading.Event()
    dialog_seen = threading.Event()
    allow_answer = threading.Event()
    ready = threading.Event()
    owned_native = set()
    attachments = []
    original_attached = ScopedObserver._attached
    def attached(observer, params):
        attachments.append(params.get('targetInfo', {}).get('targetId'))
        return original_attached(observer, params)
    attachment_probe = patch.object(ScopedObserver, '_attached', attached)
    attachment_probe.start()
    out = {'case': case, 'mode': 'integrated production helper' if integrated else ('native-helper' if use_helper else 'longer-timeout/read-only-native-monitor'),
           'level': 'SOURCE fixture, explicit native answer; NOT installed/native-chat',
           'work': str(work), 'snapshots': [], 'success': False, 'checks': {}}
    started = time.monotonic()
    secret = None
    def ex(code, task='case'):
        begin = time.monotonic()
        result = json.loads(p.execute({'code': code, 'timeout_s': 60}, task_id=task))
        return dict(result, elapsed=round(time.monotonic() - begin, 3))
    def checked(code, task='case'):
        result = ex(code, task)
        assert result['success'], result.get('error')
        return result
    def inventory():
        assert control is not None
        return {t['targetId']: t for t in control('Target.getTargets')['targetInfos']}
    def save():
        (evidence / (case + suffix)).write_text(json.dumps(out, indent=2))
    try:
        out['setup'] = checked('new_tab(' + repr(base + '/plain?case') + ');wait_for_load()')
        entry = p.states[('case', 'default')]
        parent = entry['state']['current']
        control = Wire(entry['endpoint'])
        out['initial_owned'] = list(entry['state']['owned'])
        baseline = {tid: info for tid, info in inventory().items() if info.get('type') == 'page' and tid not in entry['state']['owned']}
        out['unowned_baseline'] = baseline
        checked('new_tab(' + repr(base + '/plain?peer') + ');wait_for_load();js("window.peerCount=0")', 'peer')
        peer = p.states[('peer', 'default')]
        peer_target = peer['state']['current']
        peer_before = inventory()[peer_target]
        peer_window = control('Browser.getWindowForTarget', {'targetId': peer_target})['windowId']
        comparator = control('Target.createTarget', {'url': base + '/plain?manual', 'newWindow': True, 'browserContextId': entry['state']['context']})['targetId']
        manual_session = control('Target.attachToTarget', {'targetId': comparator, 'flatten': True})['sessionId']
        control('Page.enable', {}, manual_session)
        comparator_window = control('Browser.getWindowForTarget', {'targetId': comparator})['windowId']
        comparator_before = inventory()[comparator]
        # Identical message/origin, but a different native window: must not click it.
        control('Runtime.evaluate', {'expression': 'setTimeout(()=>{window.foreignAnswer=prompt(' + json.dumps(expected_message) + ',"foreign-initial");window.foreignAfter=1},150);true', 'returnByValue': True}, manual_session)
        pid_list = [proc.pid for proc in psutil.process_iter(['name', 'cmdline'])
                    if proc.info['name'] == 'Google Chrome' and '--user-data-dir=' + str(data) in (proc.info['cmdline'] or [])]
        assert len(pid_list) == 1, pid_list
        pid = pid_list[0]
        out['pid'] = pid
        def observe():
            ax = NativeSnapshot(pid)
            previous = None
            stable_key = None
            stable_since = None
            try:
                assert ax.trusted(), 'Accessibility unavailable'
                while not stop.is_set():
                    try:
                        snapshot = ax.scan()
                        if not owned_native:
                            expected_url = base.removeprefix('http://') + '/plain?case'
                            matching = [window for window in snapshot if any(v.get('role') == 'AXTextField' and v.get('AXValue') == expected_url for v in nodes(window))]
                            if len(matching) == 1:
                                owned_native.add(matching[0]['key'])
                        dialogs = {}
                        if helper_ready.is_set() and not out.get('native_answer'):
                            for window in snapshot:
                                if window['key'] not in owned_native:
                                    continue
                                for dialog in nodes(window):
                                    if dialog.get('AXSubrole') != 'AXApplicationDialog':
                                        continue
                                    fields = [v for v in nodes(dialog) if v['role'] == 'AXTextField' and v.get('AXTitle') == expected_message]
                                    buttons = [v for v in nodes(dialog) if v['role'] == 'AXButton' and v.get('AXTitle') in ('Oke', 'OK')]
                                    heading = [v for v in nodes(dialog) if v['role'] == 'AXHeading' and base.removeprefix('http://') in v.get('AXTitle', '')]
                                    if len(fields) == len(buttons) == len(heading) == 1:
                                        dialogs[dialog['key']] = (fields[0], buttons[0])
                        key = next(iter(dialogs)) if len(dialogs) == 1 else None
                        if key != stable_key:
                            stable_key, stable_since = key, time.monotonic() if key is not None else None
                        if key is not None:
                            dialog_seen.set()
                            if use_helper and allow_answer.is_set() and stable_since is not None and time.monotonic() - stable_since >= 1:
                                field, button = dialogs[key]
                                err = ax.ax.AXUIElementSetAttributeValue(ax.elements[field['key']], ax.string('AXValue'), ax.string(answer))
                                assert not err, ('set_value', err)
                                assert ax.text(ax.elements[field['key']], 'AXValue') == answer
                                err = ax.ax.AXUIElementPerformAction(ax.elements[button['key']], ax.string('AXPress'))
                                out['native_answer'] = {'route': 'direct AXPress after stable observation', 'press_status': err, 'at': round(time.monotonic() - started, 3)}
                                assert not err, ('press', err)
                        value = json.dumps(snapshot, sort_keys=True)
                        if value != previous:
                            out['snapshots'].append({'at': round(time.monotonic() - started, 3), 'windows': snapshot})
                            previous = value
                    except Exception as exc:
                        stable_key = stable_since = None
                        out.setdefault('native_errors', []).append(type(exc).__name__ + ': ' + str(exc))
                    ready.set()
                    stop.wait(.1)
            except Exception as exc:
                out['monitor_error'] = type(exc).__name__ + ': ' + str(exc)
                ready.set()
            finally:
                ax.clear()
        monitor = threading.Thread(target=observe, daemon=True)
        monitor.start()
        assert ready.wait(5)
        assert len(owned_native) == 1, 'exact fixture parent native window unavailable'
        out['owned_native_window'] = next(iter(owned_native))
        helper_ready.set()
        expression = ('window.open(' + json.dumps(base + '/alert') + ');true' if case == 'page_alert'
                      else 'let w=window.open("about:blank");w.document.write(' + json.dumps('<script>window.before=1;window.answer=prompt("write-prompt","initial");window.after=1</script>') + ');true')
        expression = 'window.popupCount=(window.popupCount||0)+1;' + expression
        def exercise():
            out['stage'] = 'action'
            out['action'] = ex('print(cdp("Runtime.evaluate",expression=' + repr(expression) + ',userGesture=True))')
            targets = inventory()
            out['children'] = [target for target in targets.values() if target.get('openerId') in out['initial_owned']]
            if (out['action']['success'] or (integrated and 'dialog_pending' in out['action'].get('error', ''))) and len(out['children']) == 1:
                out['stage'] = 'inspect'
                out['inspect'] = ex('switch_tab(' + repr(out['children'][0]['targetId']) + ');print(page_info())')
            out['stage'] = 'done'
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(exercise)
            if use_helper:
                assert dialog_seen.wait(10), 'owned native prompt not observed'
                assert not pending.done(), 'fixture did not exercise pending CDP'
                pending_stage = out['stage']
                out['peer_during_pending'] = checked('print(js("++window.peerCount"))', 'peer')
                assert out['peer_during_pending']['stdout'].strip() == '1'
                assert not pending.done(), 'case unexpectedly completed before explicit native answer'
                out['checks']['peer_read_completed_while_case_pending'] = pending_stage
            allow_answer.set()
            pending.result(timeout=90)
        save()
        assert out['action']['success'] or (integrated and 'dialog_pending' in out['action'].get('error', '')), out['action'].get('error')
        assert len(out['children']) == 1, 'popup target count'
        assert out.get('inspect', {}).get('success'), out.get('inspect', {}).get('error')
        if use_helper or integrated:
            if integrated:
                assert expected_message in out['inspect']['stdout'], 'integrated pending dialog metadata missing'
                out['peer_during_pending'] = checked('print(js("++window.peerCount"))', 'peer')
                assert out['peer_during_pending']['stdout'].strip() == '1'
                out['explicit_answer'] = checked('cdp("Page.handleJavaScriptDialog",accept=True,promptText=' + repr(answer) + ')')
                out['checks']['integrated_pending_then_explicit_answer'] = True
            out['result'] = checked('print(js("JSON.stringify({before:window.before,after:window.after,answer:window.answer,opener:!!window.opener})"))')
            assert json.loads(out['result']['stdout']) == {'before': 1, 'after': 1, 'answer': answer, 'opener': True}
            out['counter'] = checked('switch_tab(' + repr(parent) + ');print(js("window.popupCount"))')
            assert out['counter']['stdout'].strip() == '1'
            if not integrated:
                assert out.get('native_answer', {}).get('press_status') == 0
            out['checks']['answered_once_opener_preserved'] = True
            # This exact callback still exists only if the helper left it alone.
            control('Page.handleJavaScriptDialog', {'accept': False}, manual_session)
            manual_result = control('Runtime.evaluate', {'expression': 'window.foreignAnswer===null && window.foreignAfter===1 && document.getElementById("pw").value===""', 'returnByValue': True}, manual_session)
            assert manual_result['result'].get('value') is True, 'foreign native prompt changed'
            out['checks']['same_message_foreign_prompt_untouched'] = True
            out['checks']['vault_page_actions_supported'] = False
        out['success'] = True
    except Exception as exc:
        # Once a synthetic secret exists, even transport exception text stays local.
        out['error'] = type(exc).__name__ + (': synthetic vault check failed' if secret is not None else ': ' + str(exc))
    finally:
        secret = None
        stop.set()
        allow_answer.set()
        if monitor:
            monitor.join(5)
            out['monitor_stopped'] = not monitor.is_alive()
        try:
            out['cleanup'] = p.close_session('case')
        except Exception as exc:
            out['cleanup_error'] = type(exc).__name__
        if control:
            try:
                live = inventory()
                owned = set(out.get('initial_owned', [])) | {target['targetId'] for target in out.get('children', [])}
                out['remaining_owned'] = sorted(owned & set(live))
                if peer_target is not None:
                    assert peer_target in live and all(live[peer_target].get(k) == peer_before.get(k) for k in ('url', 'browserContextId', 'attached'))
                    assert control('Browser.getWindowForTarget', {'targetId': peer_target})['windowId'] == peer_window
                    assert checked('print(js("window.peerCount"))', 'peer')['stdout'].strip() == ('1' if use_helper or integrated else '0')
                    out['checks']['case_cleanup_preserved_readable_peer'] = True
                out['peer_cleanup'] = p.close_session('peer')
                if comparator is not None:
                    live = inventory()
                    assert comparator in live and all(live[comparator].get(k) == comparator_before.get(k) for k in ('url', 'browserContextId', 'attached'))
                    assert control('Browser.getWindowForTarget', {'targetId': comparator})['windowId'] == comparator_window
                    assert comparator not in attachments, 'provider attached foreign comparator'
                    out['final_independent_inventory'] = live
                    # Browser UI/extension workers appear and retire independently.
                    # Exact page ownership, not a whole-browser equality, is the oracle.
                    page_ids = {tid for tid, info in live.items() if info.get('type') == 'page'}
                    assert page_ids == {comparator} | set(baseline), 'unexpected fixture page residue'
                    assert all(all(live[tid].get(k) == info.get(k) for k in ('url', 'browserContextId', 'attached')) for tid, info in baseline.items()), 'unowned baseline changed'
                    out['checks']['independent_inventory_only_foreign_comparator'] = True
            except Exception as exc:
                out['inventory_error'] = type(exc).__name__ + ': ' + str(exc)
            try:
                control('Browser.close')
            except Exception:
                pass
            control.close()
        try:
            p.unload()
        except Exception:
            out['unload_error'] = True
        attachment_probe.stop()
        server.shutdown()
        server.server_close()
        server_thread.join(3)
        deadline = time.monotonic() + 5
        while True:
            residue = [proc.pid for proc in psutil.process_iter(['cmdline']) if '--user-data-dir=' + str(data) in (proc.info['cmdline'] or [])]
            if not residue or time.monotonic() >= deadline:
                break
            time.sleep(.1)
        out['process_residue'] = residue
        out['success'] = bool(out['success'] and out.get('cleanup') and out.get('peer_cleanup') and not out.get('remaining_owned') and not residue and out.get('monitor_stopped') and not server_thread.is_alive() and not any(out.get(name) for name in ('error', 'inventory_error', 'unload_error', 'monitor_error')))
        save()
        print(json.dumps({'case': case, 'success': out['success'], 'checks': out['checks'], 'error': out.get('error'), 'inventory_error': out.get('inventory_error'), 'receipt': str(evidence / (case + suffix)), 'process_residue': residue}))
    return out


if __name__ == '__main__':
    sys.exit(0 if main()['success'] else 1)
