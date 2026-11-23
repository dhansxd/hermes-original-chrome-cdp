"""SSH transport and interactive desktop operations for an original Windows Chrome."""
import base64
import concurrent.futures
import hashlib
import json
import ntpath
import re
import select
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

if __package__:
    from .profiles import ChromeProfile
else:
    from profiles import ChromeProfile


HELPER = Path(__file__).with_name('windows_chrome.ps1')
HOST_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
PROFILE_ID = re.compile(r'Default|Profile [0-9]+')
CHROME_PATH = re.compile(r'/devtools/browser/[A-Za-z0-9_-]+')

RUN_OPERATION = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$inputData=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('REQUEST_JSON')) | ConvertFrom-Json
$source=Join-Path (Join-Path $env:LOCALAPPDATA 'HermesOriginalChrome') 'windows_chrome.ps1'
if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or
    (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ine 'HELPER_HASH') {
    @{ok=$false;error='Run the Windows Chrome companion setup for this plugin version.'} | ConvertTo-Json -Compress
    exit
}
& ([scriptblock]::Create([IO.File]::ReadAllText($source)))
'''

SSH_PEER = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$ancestor=$PID
for ($level=0; $level -lt 8 -and $ancestor; $level++) {
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$ancestor"
    if ($process.Name -in @('sshd.exe','sshd-session.exe')) {
        [Console]::Out.WriteLine($process.ProcessId)
        [Console]::Out.Flush()
        [void][Console]::In.ReadLine()
        exit
    }
    $ancestor=$process.ParentProcessId
}
throw 'Windows OpenSSH connection process could not be verified.'
'''

UPLOAD_REQUEST = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('REQUEST_JSON')) | ConvertFrom-Json
$name=[string]$request.name
if ($request.id -cnotmatch '^[a-f0-9]{32}$' -or -not $name -or $name.EndsWith('.') -or
    $name.EndsWith(' ') -or $name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
    throw 'Invalid Windows Chrome upload path.'
}
$directory=Join-Path (Join-Path $env:LOCALAPPDATA 'Temp') ('HermesChromeUpload-' + $request.id)
$target=Join-Path $directory $name

function Remove-Upload {
    if ([IO.Directory]::Exists($directory)) {
        [IO.File]::Delete($target)
        [IO.Directory]::Delete($directory)
    }
}
'''

PREPARE_UPLOAD = r'''
[void][IO.Directory]::CreateDirectory($directory)
@{path=$target} | ConvertTo-Json -Compress
'''

VERIFY_UPLOAD = r'''
$file=Get-Item -LiteralPath $target
$digest=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
if ($file.Length -ne $request.bytes -or $digest -ne $request.sha256) {
    throw 'The Windows Chrome upload did not verify after transfer.'
}
'''


def encoded_command(script):
    return ('powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode('ascii'))


class WindowsUpload:
    """A verified reference file staged for one owned Windows browser session."""

    def __init__(self, command, source, digest, check_owner):
        self.command = command
        self.request = {'id': uuid.uuid4().hex, 'name': source.name,
                        'bytes': source.stat().st_size, 'sha256': digest}
        try:
            check_owner()
            prepared = subprocess.run(self._command(PREPARE_UPLOAD), stdin=subprocess.DEVNULL,
                                      capture_output=True, timeout=15)
            if prepared.returncode:
                raise RuntimeError('Could not prepare a temporary file on Windows.')
            path = json.loads(prepared.stdout).get('path', '')
            if (not ntpath.isabs(path) or ntpath.basename(path) != source.name
                    or ntpath.basename(ntpath.dirname(path)) != 'HermesChromeUpload-' + self.request['id']):
                raise RuntimeError('Windows returned an invalid temporary upload path.')
            target = self.command[-1] + ':/' + path.replace('\\', '/')
            self._run(['scp', '-B', *self.command[2:-1], '--', str(source), target], check_owner,
                      'Windows Chrome upload transfer failed over SSH.')
            self._run(self._command(VERIFY_UPLOAD), check_owner,
                      'The Windows Chrome upload did not verify after transfer.')
            check_owner()
            self.path = path
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _run(command, check_owner, error):
        check_owner()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while process.poll() is None:
                check_owner()
                time.sleep(.2)
            if process.returncode:
                raise RuntimeError(error)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    def _command(self, script):
        payload = base64.b64encode(json.dumps(self.request).encode()).decode()
        return [*self.command, *encoded_command(UPLOAD_REQUEST.replace('REQUEST_JSON', payload) + script)]

    def close(self):
        try:
            result = subprocess.run(self._command('Remove-Upload'), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


class Bridge:
    """Tie the loopback forward to the authenticated Windows SSH connection process."""

    def __init__(self, command, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(('127.0.0.1', 0))
            local_port = reserved.getsockname()[1]
        options = command[:-1]
        options[options.index('ClearAllForwardings=yes')] = 'ClearAllForwardings=no'
        forward = f'127.0.0.1:{local_port}:127.0.0.1:{port}'
        self.peer = None
        self.socket = None
        self._closing = threading.Lock()
        self.process = subprocess.Popen(
            [*options, '-o', 'GatewayPorts=no', '-o', 'ExitOnForwardFailure=yes',
             '-L', forward, command[-1], *encoded_command(SSH_PEER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        try:
            ready = select.select([self.process.stdout], [], [], 10)[0]
            line = self.process.stdout.readline(32).strip() if ready else b''
            if not re.fullmatch(rb'[1-9]\d{0,9}', line) or self.process.poll() is not None:
                raise RuntimeError('Windows SSH local forwarding is unavailable or could not be verified.')
            self.pid = int(line)
            self.socket = socket.create_connection(('127.0.0.1', local_port), timeout=3)
            self.socket.settimeout(None)
        except BaseException:
            self.close()
            raise

    def close(self):
        with self._closing:
            if self.socket is not None:
                self.socket.close()
                self.socket = None
            self.process.stdin.close()
            if self.process.poll() is None:
                try:
                    self.process.wait(2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
            self.process.stdout.close()


class BridgedConnection:
    def __init__(self, websocket, bridge, accepted):
        self.websocket, self.bridge, self.accepted = websocket, bridge, accepted

    def send(self, *args, **kwargs):
        return self.websocket.send(*args, **kwargs)

    def recv(self, *args, **kwargs):
        try:
            return self.websocket.recv(*args, **kwargs)
        except TimeoutError:
            raise
        except Exception:
            self.accepted.discard(self.bridge.peer)
            self.bridge.close()
            raise

    def close(self):
        try:
            self.websocket.close()
        finally:
            self.accepted.discard(self.bridge.peer)
            self.bridge.close()


class WindowsChrome:
    def __init__(self, device, settings):
        host = settings.get('ssh_host')
        if not isinstance(host, str) or not HOST_NAME.fullmatch(host):
            raise ValueError('Set a trusted OpenSSH Host alias for the Windows device.')
        config = settings.get('ssh_config')
        if config and (not isinstance(config, str) or not Path(config).expanduser().is_file()):
            raise ValueError('The Windows device SSH configuration file does not exist.')
        self.device = device
        self.command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes',
                        '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                        '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15',
                        '-o', 'ServerAliveCountMax=3', '-o', 'LogLevel=ERROR']
        if config:
            self.command.extend(['-F', str(Path(config).expanduser())])
        self.command.append(host)
        self.guard_key = Path.home() / '.cache' / 'original-chrome-default' / (
            'windows-' + hashlib.sha256('\0'.join(self.command).encode()).hexdigest()[:24])
        self.accepted = set()
        self._profiles = None
        self._profile_deadline = 0
        self._lock = threading.Lock()

    def _run(self, action, *, interactive=False, **arguments):
        request = json.dumps({'interactive': interactive, 'request': {'action': action, **arguments}})
        parameters = base64.b64encode(request.encode('utf-8')).decode('ascii')
        script = RUN_OPERATION.replace('REQUEST_JSON', parameters).replace('HELPER_HASH', hashlib.sha256(HELPER.read_bytes()).hexdigest())
        try:
            result = subprocess.run([*self.command, *encoded_command(script)], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, encoding='utf-8', timeout=38 if interactive else 22)
        except subprocess.TimeoutExpired:
            raise RuntimeError('The Windows Chrome operation did not respond over SSH.') from None
        if result.returncode:
            raise RuntimeError('The Windows Chrome operation failed over SSH. Check the trusted host and Chrome setup.')
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            raise RuntimeError('The Windows Chrome helper sent an invalid reply.') from None
        if payload.get('ok') is not True:
            raise RuntimeError(str(payload.get('error', 'Windows Chrome desktop operation failed.')))
        return payload['value']

    def inventory(self, *, refresh=False):
        with self._lock:
            if refresh or time.monotonic() >= self._profile_deadline:
                self._profiles = self._run('profiles')
                self._profile_deadline = time.monotonic() + 3
            return self._profiles

    def profiles(self, *, refresh=False):
        return [ChromeProfile(row['id'], row['name'] or row['id'], (row['created'], None, None))
                for row in self.inventory(refresh=refresh)['profiles']
                if PROFILE_ID.fullmatch(row['id'])]

    def profile(self, identifier, *, refresh=False):
        wanted = identifier or self.inventory()['last']
        result = next((item for item in self.profiles(refresh=refresh) if item.id == wanted), None)
        if result is None:
            raise ValueError('The Windows Chrome profile is unavailable. Refresh chrome_profiles.')
        return result

    def profile_matches(self, actual, profile):
        expected = ntpath.join(self.inventory()['root'], profile)
        return ntpath.normcase(ntpath.normpath(actual)) == ntpath.normcase(ntpath.normpath(expected))

    @staticmethod
    def seed():
        return 'data:text/plain,Hermes-Chrome-' + uuid.uuid4().hex

    def identity(self):
        return dict(self._run('identity'), device=self.device, connection=str(self.guard_key))

    def launch(self, profile, seed, identity=None, *, prepare_attach=False):
        created = (identity or self.profile(profile, refresh=True).identity)[0]
        accepted = sorted(self.accepted.copy()) if prepare_attach else []
        return dict(self._run('launch', interactive=True, profile=profile, seed=seed, created=created,
                              prepareAttach=prepare_attach, accepted=accepted),
                    device=self.device, connection=str(self.guard_key))

    def connect(self, identity, **options):
        from websockets.sync.client import connect

        if (identity.get('connection') != str(self.guard_key) or not CHROME_PATH.fullmatch(identity.get('path', ''))
                or type(identity.get('port')) is not int or not 0 < identity['port'] < 65536):
            raise RuntimeError('The Windows Chrome endpoint identity is invalid.')
        accepted = sorted(self.accepted.copy())
        bridge = Bridge(self.command, identity['port'])
        endpoint = f"ws://127.0.0.1:{identity['port']}{identity['path']}"
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                handshake = pool.submit(connect, endpoint, sock=bridge.socket, proxy=None,
                                        open_timeout=34, close_timeout=2, **options)
                try:
                    try:
                        websocket = handshake.result(timeout=.4)
                    except concurrent.futures.TimeoutError:
                        result = self._run('approve', interactive=True, identity=identity,
                                           accepted=accepted, bridgePid=bridge.pid)
                        if result.get('approved') is not True:
                            raise RuntimeError('Windows Chrome approval was not confirmed.')
                        websocket = handshake.result()
                    else:
                        result = self._run('peer', identity=identity, accepted=accepted, bridgePid=bridge.pid)
                    bridge.peer = result['peer']
                    if not re.fullmatch(r'[1-9]\d{0,4}:' + str(bridge.pid), bridge.peer):
                        raise RuntimeError('The Windows Chrome permission socket was not verified.')
                except BaseException:
                    bridge.close()
                    raise
            self.accepted.add(bridge.peer)
            return BridgedConnection(websocket, bridge, self.accepted)
        except Exception:
            bridge.close()
            raise

    def process_alive(self, identity):
        return self._run('alive', identity=identity)['alive']

    def close_seed(self, identity, seed):
        if identity is None:
            return False
        return self._run('close_seed', interactive=True, identity=identity, seed=seed)['closed']

    def download_files(self, profile):
        return self._run('download_files', profile=profile)['files']

    def download_receipts(self, profile, page, after=-1):
        request = json.dumps({'profile': profile, 'page': page, 'after': after})
        encoded = base64.b64encode(request.encode()).decode('ascii')
        loader = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; "
                  "& ([ScriptBlock]::Create([Console]::In.ReadToEnd())) '" + encoded + "'")
        script = Path(__file__).with_name('windows_download_history.ps1').read_text(encoding='utf-8')
        try:
            result = subprocess.run([*self.command, *encoded_command(loader)], input=script,
                                    capture_output=True, text=True, encoding='utf-8', timeout=28)
        except subprocess.TimeoutExpired:
            return None
        if result.returncode:
            return None
        return json.loads(result.stdout)['rows']

    def stage_upload(self, source, digest, check_owner):
        return WindowsUpload(self.command, source, digest, check_owner)

    def fetch_download(self, profile, receipt, destination, check_owner, *, expected_path=None):
        source = self._run('download_file', profile=profile, **receipt)
        if (expected_path is not None
                and ntpath.normcase(ntpath.normpath(source['path'])) != ntpath.normcase(ntpath.normpath(expected_path))):
            raise RuntimeError('The Windows Chrome download path does not match its history receipt.')
        path = "'" + source['path'].replace("'", "''") + "'"
        script = (f"$ErrorActionPreference='Stop'; $file=[IO.File]::OpenRead({path}); "
                  "try { $file.CopyTo([Console]::OpenStandardOutput()) } finally { $file.Dispose() }")
        temporary = destination.with_name('.' + uuid.uuid4().hex + '.part')
        try:
            with temporary.open('xb') as output:
                process = subprocess.Popen([*self.command, *encoded_command(script)], stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.DEVNULL)
                try:
                    while process.poll() is None:
                        check_owner()
                        time.sleep(.2)
                    if process.returncode:
                        raise RuntimeError('Windows Chrome download transfer failed over SSH.')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
            with temporary.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if temporary.stat().st_size != receipt['bytes'] or digest != source['digest']:
                raise RuntimeError('The Windows Chrome download did not verify after transfer.')
            check_owner()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {'path': str(destination), 'bytes': receipt['bytes'], 'sha256': digest}

    def install_companion(self):
        source = HELPER.read_bytes()
        checksum = hashlib.sha256(source).hexdigest()
        setup = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$folder=Join-Path $env:LOCALAPPDATA 'HermesOriginalChrome'
[void][IO.Directory]::CreateDirectory($folder)
$target=Join-Path $folder 'windows_chrome.ps1'
$current=(Test-Path -LiteralPath $target -PathType Leaf) -and
    (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ieq 'CHECKSUM'
@{ directory=$folder; current=$current } | ConvertTo-Json -Compress
"""
        result = subprocess.run([*self.command, *encoded_command(setup.replace('CHECKSUM', checksum))],
                                stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                                capture_output=True, timeout=20, check=True)
        location = json.loads(result.stdout)
        if location['current']:
            return self.profiles(refresh=True)
        staged = ntpath.join(location['directory'], 'companion-' + uuid.uuid4().hex + '.ps1')
        path = "'" + staged.replace("'", "''") + "'"
        publish = rf"""
$ErrorActionPreference='Stop'
$stage={path}
try {{
    if ((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash -ine '{checksum}') {{
        throw 'Windows Chrome companion integrity check failed.'
    }}
    $destination=Join-Path (Split-Path -Parent $stage) 'windows_chrome.ps1'
    if ([IO.File]::Exists($destination)) {{[IO.File]::Replace($stage,$destination,[NullString]::Value)}}
    else {{[IO.File]::Move($stage,$destination)}}
}} finally {{
    if ([IO.File]::Exists($stage)) {{[IO.File]::Delete($stage)}}
}}
"""
        def remote(script):
            return subprocess.run([*self.command, *encoded_command(script)], stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=20, check=True)

        try:
            for offset in range(0, len(source), 1400):
                data = base64.b64encode(source[offset:offset + 1400]).decode('ascii')
                remote(f"$ErrorActionPreference='Stop'; $file=[IO.File]::Open({path},'Append'); "
                       f"try {{ $bytes=[Convert]::FromBase64String('{data}'); "
                       "$file.Write($bytes,0,$bytes.Length) } finally { $file.Dispose() }")
            remote(publish)
        except BaseException as error:
            try:
                remote(f'Remove-Item -LiteralPath {path} -ErrorAction SilentlyContinue')
            except (OSError, subprocess.SubprocessError):
                pass
            if isinstance(error, subprocess.CalledProcessError):
                raise RuntimeError('Could not publish the Windows Chrome companion over SSH.') from None
            raise
        return self.profiles(refresh=True)
