"""Collect the original Chrome download associated with the owned page's GUID.

The frame/GUID collection follows the user's MIT-licensed google-flow-cdp helper.
Receipts survive interruption so recovery observes the original download action.
"""
import json
import subprocess
from pathlib import Path


def verify(file):
    decode = subprocess.run(['ffmpeg', '-v', 'error', '-i', file['path'], '-f', 'null', '-'],
                            capture_output=True, text=True, timeout=60)
    if decode.returncode:
        raise RuntimeError('The downloaded original did not decode: ' + decode.stderr)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', file['path']],
                           capture_output=True, text=True, check=True, timeout=20)
    metadata = json.loads(probe.stdout)
    return {**file, 'media': {'duration': metadata.get('format', {}).get('duration'),
            'streams': [{key: stream[key] for key in ('codec_type','codec_name','width','height','duration') if key in stream}
                        for stream in metadata['streams']]}}


def audio(ui, directory, source, identifier):
    """Read only the audio selected in this page, including its generated blob."""
    destination = Path(directory) / 'results' / (identifier + '.wav')
    expression = "(async()=>{const r=await fetch(" + json.dumps(source) + ");"
    expression += "if(!r.ok)throw Error('Selected voice audio is unavailable');"
    expression += "globalThis.__hermesFlowAudio=new Uint8Array(await r.arrayBuffer());return globalThis.__hermesFlowAudio.length;})()"
    code = f'''import base64,hashlib,json,tempfile
from pathlib import Path
destination=Path({str(destination)!r})
destination.parent.mkdir(parents=True,exist_ok=True)
temporary=None
try:
    size=js({expression!r})
    with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as output:
        temporary=Path(output.name)
        for offset in range(0,size,48000):
            chunk=js('btoa(String.fromCharCode(...globalThis.__hermesFlowAudio.subarray('+str(offset)+','+str(offset+48000)+')))')
            output.write(base64.b64decode(chunk))
    if temporary.stat().st_size!=size:
        raise RuntimeError('The selected voice audio transfer is incomplete')
    temporary.replace(destination)
    print('FLOW_VALUE='+json.dumps({{'path':str(destination),'bytes':size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}}))
finally:
    js('delete globalThis.__hermesFlowAudio')
    if temporary:
        temporary.unlink(missing_ok=True)
'''
    file = verify(ui.execute(code))
    if not any(stream['codec_type'] == 'audio' for stream in file['media']['streams']):
        raise RuntimeError('The selected voice file contains no audio stream')
    return file


def started(context, directory, media_id):
    if getattr(context, 'device', 'local') != 'local':
        return context.remote_download_started(media_id)
    return (Path(directory) / 'downloads' / (media_id + '.json')).is_file()


def collect(ui, directory, media_id, action, timeout=60):
    if getattr(ui.context, 'device', 'local') != 'local':
        return ui.context.remote_download(media_id, action, ui.execute, timeout=timeout)
    receipt = Path(directory) / 'downloads' / (media_id + '.json')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    code = r'''import hashlib, json, re, shutil, tempfile, time
from pathlib import Path
receipt = Path(%r)
profile = %r
preferences = Path.home() / 'Library/Application Support/Google/Chrome' / profile / 'Preferences'
settings = json.loads(preferences.read_text()) if preferences.exists() else {}
folder = Path(settings.get('download', {}).get('default_directory', str(Path.home() / 'Downloads')))
state = json.loads(receipt.read_text()) if receipt.exists() else {}
def save():
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(receipt)
if not state:
    state = {'before': {p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in folder.iterdir() if p.is_file()},
             'clicked':True}
    save()
    def frame_ids(node):
        return {node['frame']['id']}.union(*(frame_ids(c) for c in node.get('childFrames', [])))
    frames = frame_ids(cdp('Page.getFrameTree')['frameTree'])
    state['frames'] = list(frames)
    save()
    cdp('Page.enable')
    drain_events()
    exec(%r, globals())
deadline = time.monotonic() + %r
while not state.get('file') and time.monotonic() < deadline:
    for event in drain_events():
        p = event.get('params', {})
        if event.get('method') == 'Page.downloadWillBegin' and p.get('frameId') in state['frames']:
            if state.get('guid') and p['guid'] != state['guid']:
                raise RuntimeError('Multiple downloads began for this action')
            state.update(guid=p['guid'], name=Path(p['suggestedFilename']).name)
            save()
        if event.get('method') == 'Page.downloadProgress' and p.get('guid') == state.get('guid'):
            state.update(progress=p)
            save()
    if state.get('progress', {}).get('state') == 'completed':
        name = Path(state['name'])
        total = state['progress'].get('receivedBytes') or state['progress'].get('totalBytes')
        candidates = []
        for p in folder.iterdir():
            if not p.is_file() or not (p.name == name.name or re.fullmatch(re.escape(name.stem)+r' \(\d+\)'+re.escape(name.suffix),p.name)):
                continue
            stat = p.stat()
            if [stat.st_size,stat.st_mtime_ns] != state['before'].get(p.name) and stat.st_size == total:
                candidates.append(p)
        if len(candidates) > 1:
            raise RuntimeError('The completed original download file is ambiguous')
        if candidates:
            source = candidates[0]
            destination = receipt.parent.parent / 'results' / (%r + source.suffix)
            destination.parent.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as stream:
                temporary = Path(stream.name)
            try:
                shutil.copyfile(source,temporary)
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                if digest != hashlib.sha256(source.read_bytes()).hexdigest():
                    raise RuntimeError('The original download changed during collection')
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            state['file'] = {'path':str(destination),'sha256':digest,'bytes':destination.stat().st_size,'guid':state['guid']}
            save()
    if not state.get('file'):
        wait(.2)
print('FLOW_VALUE='+json.dumps(state.get('file') or {'pending':True,'receipt':str(receipt),'guid':state.get('guid')}))
''' % (str(receipt), ui.context.profile, action, timeout, media_id)
    return ui.execute(code, timeout + 15)
