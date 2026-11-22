"""Download with Gemini's UI and verify Chrome's receipt for the selected conversation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing


BUTTON = r"""(expected => {
    if (location.origin !== 'https://gemini.google.com') return null;
    const chat = location.pathname.match(/^\/(?:u\/\d+\/)?app\/([\w-]+)\/?$/)?.[1];
    const turn = [...document.querySelectorAll('model-response')].at(-1);
    const videos = turn?.querySelectorAll('generated-video') || [];
    if (!chat || videos.length !== 1) return null;
    const buttons = videos[0].querySelectorAll('button[aria-label="Download video" i],button[aria-label="Unduh video" i]');
    const button = buttons.length === 1 ? buttons[0] : null;
    const id = turn.closest('.conversation-container[id]')?.id || turn.querySelector('message-content[id]')?.id;
    if (!id || !button || button.disabled || button.closest('[aria-disabled="true"]')) return null;
    const key = chat + '/' + id;
    if (expected) {
        if (key !== expected) return null;
        button.click();
    }
    const video = videos[0].querySelector('video');
    return {key, url: location.href, width: video?.videoWidth, height: video?.videoHeight,
            duration: Number.isFinite(video?.duration) ? video.duration : null};
})"""


def button(context, key=None):
    expression = BUTTON + '(' + json.dumps(key) + ')'
    response = context.browser_exec('import json\nprint(json.dumps(js(' + repr(expression) + ')))')
    if not response.get('success') or response.get('exit_code', 0):
        raise RuntimeError('Gemini could not confirm the video control in the owned page.')
    return json.loads(response['output'])


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


def receipt(history, state):
    def query(db):
        if state.get('guid'):
            return db.execute("""SELECT guid, target_path, state, received_bytes, total_bytes FROM downloads
                                 WHERE guid = ? AND tab_url = ?""", (state['guid'], state['url'])).fetchone()
        rows = db.execute("""SELECT guid, target_path, state, received_bytes, total_bytes FROM downloads
                             WHERE tab_url = ? AND start_time BETWEEN ? AND ? LIMIT 2""",
                          (state['url'], state['start'], state.get('click_until', time.time_ns() // 1000 + 11644473600000000))).fetchall()
        if len(rows) > 1:
            raise ValueError('Multiple Chrome receipts match this click; the video is ambiguous.')
        return rows[0] if rows else None

    uri = history.as_uri() + '?mode=ro'
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=.1)) as db:
            return query(db)
    except sqlite3.OperationalError as error:
        if getattr(error, 'sqlite_errorcode', None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
    # Chrome can hold an exclusive lock even between commits in rollback-journal mode.
    # Only consult unchanged, committed pages. Never open a WAL database as immutable.
    journal = history.with_name(history.name + '-journal')
    def stamp():
        stat = history.stat()
        with history.open('rb') as f:
            header = f.read(100)
        if header[18:20] != bytes((1, 1)) or history.with_name(history.name + '-wal').exists():
            return None
        journal_stamp = None
        if journal.exists():
            with journal.open('rb') as stream:
                prefix = stream.read(8)
                journal_stat = os.fstat(stream.fileno())
            # PERSIST journals remain allocated after a commit with a zeroed header.
            if any(prefix):
                return None
            journal_stamp = (journal_stat.st_ino, journal_stat.st_size, journal_stat.st_mtime_ns)
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns, header, journal_stamp)
    before = stamp()
    if before is None:
        return None
    with closing(sqlite3.connect(uri + '&immutable=1', uri=True)) as db:
        row = query(db)
    return row if before == stamp() else None


def publish(context, source, size, state):
    directory = context.directory / 'results'
    directory.mkdir(exist_ok=True)
    target = directory / (state['guid'] + '.mp4')
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        temp = Path(stream.name)
    try:
        shutil.copyfile(source, temp)
        if temp.stat().st_size != size:
            raise ValueError('The completed Chrome download changed during collection.')
        media = context.verify_video(temp)
        video = next(s for s in media['streams'] if s['codec_type'] == 'video')
        for key in ('width', 'height'):
            if state.get(key) and state[key] != video[key]:
                raise ValueError('Downloaded dimensions do not match the selected video.')
        if state.get('duration') and abs(float(media['duration']) - state['duration']) > 1:
            raise ValueError('Downloaded duration does not match the selected video.')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return {'path': str(target), 'bytes': size, 'media': media}


def download(context, pending, *, resume=False):
    selected = json.loads(pending.read_text()) if resume else button(context)
    if not resume and selected and pending.exists() and json.loads(pending.read_text())['key'] != selected['key']:
        return {'status': 'needs_inspection', 'message': 'A different video is downloading in this task. Check its receipt before starting another download.'}
    if not selected:
        return {'status': 'needs_inspection', 'message': 'Inspect the download button on the selected video.'}
    key = hashlib.sha256(selected['key'].encode()).hexdigest()
    if getattr(context, 'device', 'local') != 'local':
        return remote_video(context, pending, selected, key)
    record = context.directory / ('video-' + key + '.json')
    shared = context.directory.parent / 'download-locks'
    shared.mkdir(exist_ok=True)
    lock_id = hashlib.sha256((context.profile + '\0' + selected['url']).encode()).hexdigest()
    history = context.chrome_profile_directory / 'History'
    with (shared / lock_id).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if record.exists():
            state = json.loads(record.read_text())
        else:
            # Chrome stores download start times as microseconds since 1601.
            start = time.time_ns() // 1000 + 11644473600000000
            state = {**selected, 'start': start}
            save(record, state)
            save(pending, selected)
            if not button(context, selected['key']):
                state['error'] = 'The selected Gemini result changed before the download click.'
                save(record, state)
        if state.get('error'):
            pending.unlink(missing_ok=True)
            return {'status': 'failed', 'message': state['error']}
        try:
            deadline = time.monotonic() + (4 if state.get('guid') or state.get('click_until') else 25)
            while True:
                context.profile  # Stop invalidates the owner while waiting.
                row = receipt(history, state)
                if row:
                    guid, path, status, received, total = row
                    if not guid or Path(guid).name != guid:
                        raise ValueError('Chrome returned an invalid download receipt.')
                    if not state.get('guid'):
                        state['guid'] = guid
                        save(record, state)
                    if status == 1 and received > 0 and total in (-1, 0, received):
                        source = Path(path)
                        if not source.is_file() or source.stat().st_size != received:
                            raise ValueError('The Chrome receipt and saved file do not match.')
                        file = publish(context, source, received, state)
                        pending.unlink(missing_ok=True)
                        return {'status': 'ok', 'data': {'file': file},
                                'message': 'Attach the verified absolute path for requested delivery.'}
                    if status in (2, 3):
                        raise ValueError('Chrome reports that the download was cancelled or interrupted.')
                if time.monotonic() >= deadline:
                    if not row and 'click_until' not in state:
                        state['click_until'] = time.time_ns() // 1000 + 11644473600000000
                        save(record, state)
                    if not row and resume:
                        return {'status': 'needs_inspection', 'message': 'Chrome has not confirmed the original download. Inspect the current video; read_result can recheck its receipt.'}
                    return {'status': 'running', 'data': {'stage': 'downloading'}}
                time.sleep(.2)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            state['error'] = str(error)
            save(record, state)
            pending.unlink(missing_ok=True)
            return {'status': 'failed', 'message': state['error']}


def remote_video(context, pending, selected, key):
    def execute(code, timeout):
        result = context.browser_exec(code, timeout_s=timeout)
        if not result.get('success') or result.get('exit_code', 0):
            raise RuntimeError('Gemini could not confirm the download in the owned Windows page.')

    save(pending, selected)
    expression = BUTTON + '(' + json.dumps(selected['key']) + ')'
    action = f'if not js({expression!r}):\n    raise RuntimeError("The selected Gemini result changed.")'
    file = context.remote_download('gemini-video-' + key, action, execute)
    if file.get('pending'):
        return {'status': 'running', 'data': {'stage': 'downloading'}}
    media = context.verify_video(file['path'])
    video = next(s for s in media['streams'] if s['codec_type'] == 'video')
    for field in ('width', 'height'):
        if selected.get(field) and selected[field] != video[field]:
            raise ValueError('Downloaded dimensions do not match the selected video.')
    if selected.get('duration') and abs(float(media['duration']) - selected['duration']) > 1:
        raise ValueError('Downloaded duration does not match the selected video.')
    pending.unlink(missing_ok=True)
    return {'status': 'ok', 'data': {'file': {**file, 'media': media}},
            'message': 'Attach the verified absolute path for requested delivery.'}
