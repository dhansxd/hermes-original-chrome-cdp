"""Select explicit files in the Chrome document already owned by the task."""
import json
from pathlib import Path
from textwrap import indent


def upload_parameters(params):
    if not isinstance(params, dict) or set(params) - {'path', 'paths', 'target'}:
        raise ValueError('Pass path or paths and an optional named file-picker target.')
    paths = [params['path']] if 'path' in params and 'paths' not in params else params.get('paths')
    if ('path' in params and 'paths' in params or not isinstance(paths, list) or not paths
            or not all(isinstance(path, str) and path.strip() and '\x00' not in path for path in paths)):
        raise ValueError('Pass one absolute file path or a list of absolute file paths.')
    target = params.get('target')
    if 'target' in params and (not isinstance(target, str) or not 0 < len(target.strip()) <= 100
                               or not target.strip().isprintable()):
        raise ValueError('Pass the visible name of the file-picker control.')
    try:
        files = tuple(Path(path).expanduser() for path in paths)
        if not all(path.is_absolute() and path.is_file() for path in files):
            raise ValueError('Every upload path must identify an existing absolute file.')
    except (OSError, RuntimeError) as error:
        raise ValueError('Could not open the selected upload file.') from error
    return files, target.strip() if target else None


_SELECT_FILES = '''import json as _file_json
def _file_result(status, dispatched):
    print('CHROME_FILE_SELECTION=' + _file_json.dumps({
        'success': status == 'file_selected', 'status': status, 'dispatched': dispatched,
    }))

def _input_state(remote):
    value = cdp('Runtime.callFunctionOn', objectId=remote, returnByValue=True,
        functionDeclaration="function() { return this.type === 'file' && !this.matches(':disabled') ? {multiple:this.multiple, files:[...this.files].map(f=>[f.name,f.size])} : null; }")
    return value.get('result', {}).get('value')

def _select_files(node, backend, files, expected, *, selector=None):
    remote = None
    dispatched = backend
    try:
        remote = cdp('DOM.resolveNode', **node)['object']['objectId']
        state = _input_state(remote)
        if not state or (len(files) > 1 and not state['multiple']):
            _file_result('file_input_unavailable', backend)
            return
        dispatched = True
        if selector is None:
            cdp('DOM.setFileInputFiles', files=files, **node)
        else:
            upload_file(selector, files)
        selected = _input_state(remote)
        _file_result('file_selected' if selected and selected['files'] == expected
                     else 'file_selection_unconfirmed', True)
    except Exception:
        _file_result('file_selection_unconfirmed' if dispatched else 'file_input_unavailable', dispatched)
    finally:
        if remote:
            try:
                cdp('Runtime.releaseObject', objectId=remote)
            except Exception:
                pass
'''


def direct_upload_code(paths, expected):
    selector = 'input[type=file]:not(:disabled)'
    return _SELECT_FILES + f'''
_selector = {selector!r}
_document = cdp('DOM.getDocument')['root']['nodeId']
_nodes = cdp('DOM.querySelectorAll', nodeId=_document, selector=_selector)['nodeIds']
if len(_nodes) != 1:
    _file_result('choose_file_target', False)
else:
    _select_files({{'nodeId':_nodes[0]}}, False, {paths!r}, {expected!r}, selector=_selector)
'''


def chooser_upload_code(code, paths, expected, *, dispatched='True'):
    return _SELECT_FILES + f'''
from time import monotonic as _file_clock
def _frame_ids(tree):
    frames = {{tree['frame']['id']}}
    for child in tree.get('childFrames', []):
        frames.update(_frame_ids(child))
    return frames

_frame = cdp('Page.getFrameTree')['frameTree']['frame']
cdp('Page.enable')
drain_events()
cdp('Page.setInterceptFileChooserDialog', enabled=True)
try:
{indent(code, '    ')}
    if {dispatched}:
        _deadline = _file_clock() + 10
        while True:
            _events = [event['params'] for event in drain_events()
                       if event.get('method') == 'Page.fileChooserOpened']
            if _events or _file_clock() >= _deadline:
                break
            wait(.1)
        _tree = cdp('Page.getFrameTree')['frameTree']
        _current = _tree['frame']
        _chooser = _events[0] if len(_events) == 1 else {{}}
        if (_chooser.get('backendNodeId') and _chooser.get('frameId') in _frame_ids(_tree)
                and _current['id'] == _frame['id'] and _current.get('loaderId') == _frame.get('loaderId')):
            _select_files({{'backendNodeId':_chooser['backendNodeId']}}, True, {paths!r}, {expected!r})
        else:
            _file_result('file_chooser_unconfirmed' if _events else 'file_chooser_not_opened', True)
finally:
    cdp('Page.setInterceptFileChooserDialog', enabled=False)
'''


def upload_result(native_result):
    if not isinstance(native_result, dict):
        return None
    for line in (native_result.get('output') or '').splitlines():
        if line.startswith('CHROME_FILE_SELECTION='):
            result = json.loads(line.split('=', 1)[1])
            if result['status'] == 'choose_file_target':
                result['next'] = 'Pass the visible file-picker target with the same file path.'
            elif result['dispatched'] and not result['success']:
                result['next'] = 'Inspect the current page before trying to select the file again.'
            return result
    return None
