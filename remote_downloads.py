"""Collect an owned page's native Chrome download across the SSH connection."""
import json
import re
from pathlib import PureWindowsPath


READ_EVENTS = """
import json, time
from pathlib import Path
record = Path(%r)
state = json.loads(record.read_text())
def save():
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(record)
def frame_ids(node):
    return {node['frame']['id']}.union(*(frame_ids(c) for c in node.get('childFrames', [])))
cdp('Page.enable')
if not state.get('clicked'):
    frames = frame_ids(cdp('Page.getFrameTree')['frameTree'])
    drain_events()
    state.update(clicked=True, frames=list(frames))
    save()
    exec(%r, globals())
deadline = time.monotonic() + %r
while time.monotonic() < deadline:
    for event in drain_events():
        params = event.get('params', {})
        method = event.get('method')
        if method == 'Page.downloadWillBegin' and params.get('frameId') in state['frames']:
            if state.get('guid') and params['guid'] != state['guid']:
                raise RuntimeError('More than one Chrome download began for this action.')
            state.update(guid=params['guid'], name=params['suggestedFilename'])
            save()
        if method == 'Page.downloadProgress' and params.get('guid') == state.get('guid'):
            state['progress'] = params
            save()
    if state.get('progress', {}).get('state') in ('completed', 'canceled'):
        break
    wait(.2)
"""


def collect(context, key, action, execute, save, timeout):
    desktop = context.host.provider.desktop(context.device)
    profile = context.profile
    record = context.directory / 'downloads' / (key + '.json')
    record.parent.mkdir(exist_ok=True)
    if record.exists():
        state = json.loads(record.read_text())
    else:
        state = {'before': {row['name']: row for row in desktop.download_files(profile)}}
        save(record, state)
    if state.get('file'):
        return state['file']
    if state.get('progress', {}).get('state') != 'completed':
        execute(READ_EVENTS % (str(record), action, timeout), timeout + 15)
        state = json.loads(record.read_text())
    progress = state.get('progress', {})
    pending = {'pending': True, 'guid': state.get('guid')}
    if progress.get('state') == 'canceled':
        raise RuntimeError('Chrome reports that the download was cancelled.')
    if progress.get('state') != 'completed':
        return pending
    name = PureWindowsPath(state['name']).name
    original = PureWindowsPath(name)
    duplicate = re.compile(re.escape(original.stem) + r' \(\d+\)' + re.escape(original.suffix), re.I)
    size = progress.get('receivedBytes') or progress.get('totalBytes')
    candidates = [row for row in desktop.download_files(profile)
                  if (row['name'].casefold() == name.casefold() or duplicate.fullmatch(row['name']))
                  and row['bytes'] == size and state['before'].get(row['name']) != row]
    if len(candidates) > 1:
        raise RuntimeError('The Windows Chrome download filename is ambiguous.')
    if not candidates:
        return pending
    folder = context.directory / 'results'
    folder.mkdir(exist_ok=True)
    suffix = PureWindowsPath(candidates[0]['name']).suffix
    target = folder / (key + suffix)
    file = desktop.fetch_download(profile, candidates[0], target, context._choice)
    state['file'] = {**file, 'guid': state['guid']}
    save(record, state)
    return state['file']
