"""Two identical early popup prompts; disposable GUI, source acceptance only."""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home() / '.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from worker import Wire


def main():
    out = Path(tempfile.mkdtemp(prefix='parallel-prompts-', dir=Path.home() / '.hermes/cache/scratch'))
    data = out / 'chrome'
    data.mkdir()
    report = {'success': False, 'level': 'source provider; disposable root; not native chat', 'results': [], 'scans': {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            body = b'<title>Parallel prompt fixture</title><p>fixture</p><input id="pw" type="password"><script>window.count=0;</script>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    provider = ChromeProvider(data=data, workspace=out / 'workspaces')
    control = None
    owned = {}
    baseline = set()

    def save():
        (out / 'result.json').write_text(json.dumps(report, indent=2))

    def execute(task, code):
        result = json.loads(provider.execute({'code': code, 'timeout_s': 25}, task_id=task))
        report['results'].append({'task': task, 'code': code, 'result': result})
        save()
        return result

    def checked(task, code):
        result = execute(task, code)
        assert result.get('success'), result.get('error')
        return result

    def inventory():
        assert control is not None
        return {row['targetId']: row for row in control('Target.getTargets')['targetInfos'] if row.get('type') == 'page'}

    try:
        parents = {}
        for name in ('a', 'b'):
            checked(name, 'new_tab(' + repr(base + '/?name=' + name) + ');wait_for_load()')
            entry = provider.states[(name, 'default')]
            parents[name] = entry['state']['current']
            if control is None:
                control = Wire(entry['endpoint'])
            original_scan = entry['observer'].native.scan
            def scan(state, wire, original_scan=original_scan, name=name):
                result = original_scan(state, wire)
                report['scans'].setdefault(name, []).append({'at': time.monotonic(), 'found': result})
                return result
            entry['observer'].native.scan = scan
        baseline = set(inventory()) - set.union(*(set(entry['state']['owned']) for entry in provider.states.values()))
        expression = 'window.popupCount=(window.popupCount||0)+1;let w=window.open("about:blank");w.document.write(' + json.dumps('<script>window.before=1;window.answer=prompt("parallel-identical-prompt","initial");window.after=1</script>') + ');true'
        for name in ('a', 'b'):
            action = execute(name, 'print(cdp("Runtime.evaluate",expression=' + repr(expression) + ',userGesture=True))')
            assert action.get('success') or ('dialog_pending' in action.get('error', '') and action.get('uncertain') is False), action
            children = [row for row in inventory().values() if row.get('openerId') == parents[name]]
            assert len(children) == 1, children
            parents[name + '-child'] = children[0]['targetId']
            owned[name] = set(provider.states[(name, 'default')]['state']['owned'])
        # Both prompts remain live before the first explicit answer.
        for name in ('a', 'b'):
            info = checked(name, 'switch_tab(' + repr(parents[name + '-child']) + ');print(page_info())')
            assert 'parallel-identical-prompt' in info['stdout'] and "'native': True" in info['stdout'], info
        report['simultaneous_native_prompts_observed'] = True
        time.sleep(float(os.environ.get('DIALOG_IDLE_SECONDS', '25')))
        for name in ('a', 'b'):
            observer = provider.states[(name, 'default')]['observer']
            report.setdefault('expected_answers', {})[name] = dict(observer.native_pending)
            with observer._lock:
                fresh = observer.native.scan(provider.states[(name, 'default')]['state'], observer.wire)
                report.setdefault('fresh_before_answers', {})[name] = fresh
                assert fresh == observer.native_pending, 'native observation was stale before explicit answer'
                if name == 'a':
                    snapshot = observer.native.ax.scan()
                    keys = {dialog['key'] for window in snapshot for dialog in window['dialogs']}
                    expected_keys = {pending['dialog']['key'] for entry in provider.states.values() for pending in entry['observer'].native_pending.values()}
                    assert len(expected_keys) == 2 and expected_keys <= keys, 'both native prompts must really coexist'
                    report['two_native_dialogs_confirmed'] = True
            save()
            checked(name, 'cdp("Page.handleJavaScriptDialog",accept=True,promptText=' + repr('answer-' + name) + ')')
            value = checked(name, 'import json;print(json.dumps(js("({before:window.before,after:window.after,answer:window.answer,opener:!!window.opener})")))')
            assert json.loads(value['stdout']) == {'before': 1, 'after': 1, 'answer': 'answer-' + name, 'opener': True}
            counter = checked(name, 'switch_tab(' + repr(parents[name]) + ');print(js("window.popupCount"))')
            assert counter['stdout'].strip() == '1', counter
            if name == 'a':
                info = checked('b', 'print(page_info())')
                assert 'parallel-identical-prompt' in info['stdout'] and "'defaultPrompt': 'initial'" in info['stdout'], info
        report['success'] = True
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error=str(exc))
    finally:
        report['cleanup'] = {}
        for name in ('a', 'b'):
            entry = provider.states.get((name, 'default'))
            if entry:
                owned.setdefault(name, set()).update(entry.get('state', {}).get('owned', {}))
            try:
                report['cleanup'][name] = provider.close_session(name)
            except Exception as exc:
                report['cleanup'][name] = str(exc)
        if control:
            try:
                live = set(inventory())
                report['remaining_owned'] = sorted(set.union(set(), *owned.values()) & live)
                report['baseline_preserved'] = baseline <= live
                if report['remaining_owned'] or not report['baseline_preserved']:
                    report['success'] = False
            except Exception as exc:
                report['inventory_error'] = str(exc)
                report['success'] = False
            try:
                control('Browser.close')
            except Exception:
                pass
            control.close()
        provider.unload()
        server.shutdown()
        server.server_close()
        serving.join(3)
        def processes():
            found = []
            for proc in psutil.process_iter():
                try:
                    if '--user-data-dir=' + str(data) in proc.cmdline():
                        found.append(proc)
                except psutil.Error:
                    pass
            return found
        deadline = time.monotonic() + 5
        while processes() and time.monotonic() < deadline:
            time.sleep(.1)
        residue = processes()
        report['residue_before_hygiene'] = [proc.pid for proc in residue]
        if residue:
            report['success'] = False
        for proc in residue:
            try:
                proc.terminate()
            except psutil.Error:
                pass
        psutil.wait_procs(residue, timeout=3)
        save()
        print(json.dumps({'success': report['success'], 'error': report.get('error'), 'evidence': str(out / 'result.json')}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
