$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$helperText=@'
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$chromeData = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
$chromeExe = @(
    (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe')
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $chromeExe) { throw 'Google Chrome was not found under the SSH account.' }

function ChromeState {
    Get-Content -LiteralPath (Join-Path $chromeData 'Local State') -Raw | ConvertFrom-Json
}

function ChromeProfiles {
    $local = ChromeState
    $items = @()
    foreach ($row in $local.profile.info_cache.PSObject.Properties) {
        if ($row.Name -notmatch '^(Default|Profile [0-9]+)$' -or
            $row.Value.is_ephemeral -or $row.Value.force_signin_profile_locked) { continue }
        $folder = Get-Item -LiteralPath (Join-Path $chromeData $row.Name) -ErrorAction SilentlyContinue
        if (-not $folder -or -not $folder.PSIsContainer -or
            ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        $items += [ordered]@{ id=$row.Name; name=$row.Value.name; created=$folder.CreationTimeUtc.Ticks }
    }
    @{ profiles=$items; last=$local.profile.last_used; root=$chromeData }
}

function ChromeIdentity {
    $local = ChromeState
    if ($local.devtools.remote_debugging.'user-enabled' -ne $true) {
        throw 'Enable Remote Debugging once in Chrome on Windows.'
    }
    $lines = @(Get-Content -LiteralPath (Join-Path $chromeData 'DevToolsActivePort'))
    if ($lines.Count -lt 2 -or $lines[0] -notmatch '^\d{1,5}$' -or
        $lines[1] -notmatch '^/devtools/browser/[A-Za-z0-9_-]+$') {
        throw 'Windows Chrome did not publish a valid debugging endpoint.'
    }
    $port = [int]$lines[0]
    if ($port -le 0 -or $port -gt 65535) { throw 'Invalid Windows Chrome port.' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerIds.Count -ne 1 -or '127.0.0.1' -notin $listeners.LocalAddress -or
        @($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count) {
        throw 'Windows Chrome has no exclusive loopback debugging endpoint.'
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($ownerIds[0])"
    if (-not $process -or $process.ExecutablePath -ine $chromeExe -or $process.SessionId -eq 0 -or
        -not $process.CommandLine -or $process.CommandLine -match '(?:^|\s)--(?:type|user-data-dir)=') {
        throw 'The debugging endpoint does not belong to the original desktop Chrome.'
    }
    if ((Get-Item -LiteralPath (Join-Path $chromeData 'DevToolsActivePort')).LastWriteTimeUtc -lt
        $process.CreationDate.ToUniversalTime()) {
        throw 'Windows Chrome debugging endpoint is stale.'
    }
    [ordered]@{ pid=[int]$process.ProcessId; started=$process.CreationDate.ToUniversalTime().Ticks
                 session=$process.SessionId; port=$port; path=[string]([regex]::Match($lines[1],'^/devtools/browser/[A-Za-z0-9_-]+$').Value) }
}

function Confirm-Chrome($expected) {
    $current = ChromeIdentity
    foreach ($key in @('pid','started','session','port','path')) {
        if ($current[$key] -ne $expected.$key) { throw 'Windows Chrome changed during the operation.' }
    }
    $current
}

function Load-Automation {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class HermesChromeWindows {
    private delegate bool Callback(IntPtr handle, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(Callback callback, IntPtr data);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out int pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder text, int length);
    public static IntPtr[] OfProcess(int processId) {
        var windows = new List<IntPtr>();
        EnumWindows(delegate(IntPtr handle, IntPtr ignored) {
            int pid;
            GetWindowThreadProcessId(handle, out pid);
            if (pid == processId) windows.Add(handle);
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }
    public static string Title(IntPtr handle) {
        var title = new StringBuilder(256);
        GetWindowText(handle, title, title.Capacity);
        return title.ToString();
    }
}
"@
}

function ChromeWindows([int]$chromeProcessId) {
    foreach ($handle in [HermesChromeWindows]::OfProcess($chromeProcessId)) {
        try {[Windows.Automation.AutomationElement]::FromHandle($handle)}
        catch [Windows.Automation.ElementNotAvailableException] {}
    }
}

function Dialogs([int]$chromeProcessId) {
    $matches = @{}
    $titles = @('Allow remote debugging?', 'Izinkan proses debug jarak jauh?')
    foreach ($handle in [HermesChromeWindows]::OfProcess($chromeProcessId)) {
        $title = [HermesChromeWindows]::Title($handle)
        if ($title -notin $titles) { continue }
        $window = [Windows.Automation.AutomationElement]::FromHandle($handle)
        $name = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty, $title)
        foreach ($element in $window.FindAll([Windows.Automation.TreeScope]::Subtree, $name)) {
            if ($element.Current.ControlType -ne [Windows.Automation.ControlType]::Window -or
                $element.Current.ProcessId -ne $chromeProcessId -or $element.Current.IsOffscreen) { continue }
            $matches[($element.GetRuntimeId() -join ',')] = $element
        }
    }
    $matches
}

function ChromePeers($identity) {
    $peers = @()
    foreach ($row in @(Get-NetTCPConnection -State Established -LocalPort $identity.port -ErrorAction SilentlyContinue)) {
        if ($row.OwningProcess -ne $identity.pid -or $row.LocalAddress -ne '127.0.0.1' -or
            $row.RemoteAddress -ne '127.0.0.1') { throw 'Unexpected Windows Chrome debugging socket.' }
        $outgoing = @(Get-NetTCPConnection -State Established -LocalPort $row.RemotePort -RemotePort $identity.port -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.RemoteAddress -eq '127.0.0.1' })
        if ($outgoing.Count -ne 1) { throw 'Windows Chrome debugging peer could not be verified.' }
        $peers += "$($row.RemotePort):$($outgoing[0].OwningProcess)"
    }
    $peers
}

function Claim-ChromePeer($identity, $request) {
    $peers = @(ChromePeers $identity)
    $claims = @($peers | Where-Object {$_.EndsWith(":$($request.bridgePid)") -and $_ -notin $request.accepted})
    if ($claims.Count -ne 1 -or @($peers | Where-Object {$_ -ne $claims[0] -and $_ -notin $request.accepted}).Count) {
        throw 'The Windows Chrome permission dialog does not match the plugin connection.'
    }
    $claims[0]
}

function Assert-CleanAttach($identity, $request) {
    if ((Get-Process -Id $PID).SessionId -ne $identity.session) { throw 'Open the Windows desktop session first.' }
    Load-Automation
    if ((Dialogs $identity.pid).Count) { throw 'A previous Windows Chrome debugging dialog is still open.' }
    if (@(ChromePeers $identity | Where-Object {$_ -notin $request.accepted}).Count) {
        throw 'An unrecognized Windows Chrome debugging client is connected.'
    }
}

function Approve-Chrome($request) {
    $identity = Confirm-Chrome $request.identity
    if ((Get-Process -Id $PID).SessionId -ne $identity.session) { throw 'Open the Windows desktop session first.' }
    Load-Automation
    $until = (Get-Date).AddSeconds(12)
    do {
        $dialogs = Dialogs $identity.pid
        if ($dialogs.Count -gt 1) { throw 'Multiple Windows Chrome debugging dialogs are visible.' }
        if ($dialogs.Count -eq 1) {
            $claim = Claim-ChromePeer $identity $request
            $dialog = @($dialogs.Values)[0]
            $buttons = @($dialog.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) |
                Where-Object {
                    $_.Current.ProcessId -eq $identity.pid -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::Button -and
                    $_.Current.IsEnabled -and -not $_.Current.IsOffscreen -and $_.Current.Name -in @('Allow','Izinkan')
                })
            if ($buttons.Count -ne 1) { throw 'The Windows Chrome permission dialog has no unique Allow button.' }
            $again = Dialogs $identity.pid
            $key = $dialog.GetRuntimeId() -join ','
            if ($again.Count -ne 1 -or -not $again.ContainsKey($key)) { throw 'The permission dialog changed.' }
            $identity = Confirm-Chrome $request.identity
            if ((Claim-ChromePeer $identity $request) -ne $claim) {
                throw 'The Windows Chrome debugging socket changed before approval.'
            }
            $invoke = $null
            if (-not $buttons[0].TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)) {
                throw 'The Windows Chrome Allow button cannot be invoked.'
            }
            $invoke.Invoke()
            return @{ approved=$true; peer=$claim }
        }
        Start-Sleep -Milliseconds 150
    } while ((Get-Date) -lt $until)
    throw 'The Windows Chrome permission dialog did not appear.'
}

function Seed-Window($request) {
    if ($request.profile -notmatch '^(Default|Profile [0-9]+)$' -or
        $request.seed -notmatch '^data:text/plain,Hermes-Chrome-[a-f0-9]{32}$') {
        throw 'Invalid Windows Chrome window request.'
    }
    $available = @( (ChromeProfiles).profiles | Where-Object { $_.id -eq $request.profile })
    if ($available.Count -ne 1 -or $available[0].created -ne $request.created) {
        throw 'The selected Windows Chrome profile was replaced.'
    }
    if ((ChromeState).devtools.remote_debugging.'user-enabled' -ne $true) {
        throw 'Enable Remote Debugging once in Chrome on Windows.'
    }
    $arguments = '--profile-directory="' + $request.profile + '" --new-window ' + $request.seed
    Start-Process -FilePath $chromeExe -ArgumentList $arguments
    $until = (Get-Date).AddSeconds(14)
    do {
        Start-Sleep -Milliseconds 250
        try {
            $identity = ChromeIdentity
            if ($identity.session -eq (Get-Process -Id $PID).SessionId) { return $identity }
        } catch {}
    } while ((Get-Date) -lt $until)
    throw 'Chrome did not open a debugging endpoint in the Windows desktop session.'
}

function Close-Seed($request) {
    $identity = Confirm-Chrome $request.identity
    if ($request.seed -notmatch '^data:text/plain,Hermes-Chrome-[a-f0-9]{32}$' -or
        (Get-Process -Id $PID).SessionId -ne $identity.session) {
        throw 'The Windows Chrome seed window cannot be verified.'
    }
    Load-Automation
    $isEdit = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Edit)
    $isTab = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::TabItem)
    $matches = @()
    foreach ($window in @(ChromeWindows $identity.pid)) {
        foreach ($edit in $window.FindAll([Windows.Automation.TreeScope]::Descendants,$isEdit)) {
            $value = $null
            if ($edit.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$value) -and
                $value.Current.Value -ceq $request.seed) {
                $matches += $window
                break
            }
        }
    }
    if ($matches.Count -ne 1 -or $matches[0].FindAll([Windows.Automation.TreeScope]::Descendants,$isTab).Count -ne 1) {
        return @{closed=$false}
    }
    $pattern = $null
    if (-not $matches[0].TryGetCurrentPattern([Windows.Automation.WindowPattern]::Pattern,[ref]$pattern)) {
        return @{closed=$false}
    }
    $handle = $matches[0].Current.NativeWindowHandle
    $pattern.Close()
    for ($attempt=0; $attempt -lt 15; $attempt++) {
        if (-not @(ChromeWindows $identity.pid | Where-Object {$_.Current.NativeWindowHandle -eq $handle}).Count) {
            return @{closed=$true}
        }
        Start-Sleep -Milliseconds 150
    }
    @{closed=$false}
}

function Download-Folder($request) {
    if ($request.profile -notmatch '^(Default|Profile [0-9]+)$') {throw 'Invalid Windows Chrome profile.'}
    $path = Join-Path $chromeData ($request.profile + '\Preferences')
    $settings = [IO.File]::ReadAllText($path) | ConvertFrom-Json
    $location = $settings.download.default_directory
    if (-not $location) {
        $location = Get-ItemPropertyValue -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' `
            -Name '{374DE290-123F-4565-9164-39C4925E467B}' -ErrorAction SilentlyContinue
    }
    if (-not $location) {$location = Join-Path $env:USERPROFILE 'Downloads'}
    $location = [Environment]::ExpandEnvironmentVariables($location)
    if ($location -notmatch '^[A-Za-z]:[\\/]') {throw 'Chrome needs a local Windows download folder for file transfer.'}
    [IO.Path]::GetFullPath($location)
}

switch ($request.action) {
    'profiles' { ChromeProfiles }
    'identity' { ChromeIdentity }
    'launch' {
        $identity=Seed-Window $request
        if ($request.prepareAttach) { Assert-CleanAttach $identity $request }
        $identity
    }
    'preflight' {
        $identity = Confirm-Chrome $request.identity
        Assert-CleanAttach $identity $request
        @{ ready=$true }
    }
    'approve' { Approve-Chrome $request }
    'peer' { @{peer=(Claim-ChromePeer (Confirm-Chrome $request.identity) $request)} }
    'close_seed' { Close-Seed $request }
    'download_files' {
        $directory = Download-Folder $request
        $files = @(Get-ChildItem -LiteralPath $directory -File -ErrorAction SilentlyContinue |
            Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } |
            ForEach-Object { @{ name=$_.Name; bytes=$_.Length; modified=$_.LastWriteTimeUtc.Ticks } })
        @{ files=$files }
    }
    'download_file' {
        $directory = Download-Folder $request
        $name = [string]$request.name
        if (-not $name -or $name -in @('.','..') -or $name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
            $name -ne [IO.Path]::GetFileName($name)) {throw 'Invalid Windows Chrome download filename.'}
        $file = Get-Item -LiteralPath (Join-Path $directory $name)
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            $file.Length -ne $request.bytes -or $file.LastWriteTimeUtc.Ticks -ne $request.modified) {
            throw 'The completed Windows Chrome download changed.'
        }
        @{ path=$file.FullName; digest=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    'alive' {
        $existing = @(Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$request.identity.pid)" -ErrorAction SilentlyContinue)
        @{ alive=[bool]($existing | Where-Object { $_.ExecutablePath -ieq $chromeExe -and
            $_.CreationDate.ToUniversalTime().Ticks -eq $request.identity.started }) }
    }
    default { throw 'Unknown Windows Chrome operation.' }
}
'@
if (-not $inputData.interactive) {
    try {
        $request=$inputData.request
        $value=& ([scriptblock]::Create($helperText))
        $result=@{ok=$true; value=$value}
    } catch {
        $result=@{ok=$false; error=$_.Exception.Message}
    }
    $result | ConvertTo-Json -Compress -Depth 8
    exit
}
$tag='HermesChrome-'+[Guid]::NewGuid().ToString('N')
$directory=Join-Path (Join-Path $env:LOCALAPPDATA 'Temp') $tag
[void][IO.Directory]::CreateDirectory($directory)
try {
    [IO.File]::WriteAllText((Join-Path $directory 'operation.txt'),$helperText)
    [IO.File]::WriteAllText((Join-Path $directory 'request.json'),($inputData.request | ConvertTo-Json -Compress -Depth 8))
    $runner=@'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$directory='TEMP_DIRECTORY'
try {
    $request=Get-Content -LiteralPath (Join-Path $directory 'request.json') -Raw | ConvertFrom-Json
    $value=& ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $directory 'operation.txt'))))
    $response=@{ok=$true; value=$value}
} catch {
    $response=@{ok=$false; error=$_.Exception.Message}
}
$pending=Join-Path $directory 'pending.json'
[IO.File]::WriteAllText($pending,($response | ConvertTo-Json -Compress -Depth 8))
[IO.File]::Move($pending,(Join-Path $directory 'result.json'))
'@.Replace('TEMP_DIRECTORY',$directory.Replace("'","''"))
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runner))
    $action=New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand '+$encoded)
    $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 26)
    Register-ScheduledTask -TaskName $tag -Action $action -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $tag
    $file=Join-Path $directory 'result.json'
    $until=(Get-Date).AddSeconds(22)
    while (-not (Test-Path -LiteralPath $file) -and (Get-Date) -lt $until) {Start-Sleep -Milliseconds 120}
    if (-not (Test-Path -LiteralPath $file)) {throw 'Windows needs the SSH user logged into their interactive desktop.'}
    [IO.File]::ReadAllText($file)
} finally {
    $task=Get-ScheduledTask -TaskName $tag -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -eq 'Running') {Stop-ScheduledTask -TaskName $tag -ErrorAction SilentlyContinue}
        Unregister-ScheduledTask -TaskName $tag -Confirm:$false
    }
    if ((Split-Path -Leaf $directory) -eq $tag -and $tag -match '^HermesChrome-[a-f0-9]{32}$') {
        [IO.Directory]::Delete($directory,$true)
    }
}
