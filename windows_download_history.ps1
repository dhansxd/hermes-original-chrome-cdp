param([string]$EncodedRequest)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($EncodedRequest)) | ConvertFrom-Json

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class ChromeDownloadHistory {
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_open_v2([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out IntPtr db, int flags, IntPtr vfs);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_close(IntPtr db);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_prepare_v2(IntPtr db, string sql, int bytes, out IntPtr stmt, IntPtr tail);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_bind_text(IntPtr stmt, int slot, [MarshalAs(UnmanagedType.LPUTF8Str)] string text, int length, IntPtr copy);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_bind_int64(IntPtr stmt, int slot, long value);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_step(IntPtr stmt);
    [DllImport("winsqlite3.dll")]
    static extern int sqlite3_finalize(IntPtr stmt);
    [DllImport("winsqlite3.dll")]
    static extern long sqlite3_column_int64(IntPtr stmt, int slot);
    [DllImport("winsqlite3.dll")]
    static extern IntPtr sqlite3_column_text16(IntPtr stmt, int slot);

    public static int Read(string uri, string url, long after, List<object> rows) {
        IntPtr db = IntPtr.Zero, stmt = IntPtr.Zero;
        try {
            int status = sqlite3_open_v2(uri, out db, 65, IntPtr.Zero); // READONLY | URI
            if (status != 0) return status;
            string sql = after < 0
                ? "SELECT id FROM downloads WHERE tab_url=?1 ORDER BY id DESC LIMIT 1"
                : "SELECT id,guid,target_path,state,received_bytes FROM downloads WHERE tab_url=?1 AND id>?2 ORDER BY id LIMIT 2";
            status = sqlite3_prepare_v2(db, sql, -1, out stmt, IntPtr.Zero);
            if (status != 0) return status;
            status = sqlite3_bind_text(stmt, 1, url, -1, new IntPtr(-1));
            if (status != 0) return status;
            if (after >= 0 && (status = sqlite3_bind_int64(stmt, 2, after)) != 0) return status;
            while ((status = sqlite3_step(stmt)) == 100) { // SQLITE_ROW
                long id = sqlite3_column_int64(stmt, 0);
                if (after < 0) rows.Add(new { id = id });
                else rows.Add(new {
                    id = id,
                    guid = Marshal.PtrToStringUni(sqlite3_column_text16(stmt, 1)),
                    path = Marshal.PtrToStringUni(sqlite3_column_text16(stmt, 2)),
                    state = sqlite3_column_int64(stmt, 3),
                    bytes = sqlite3_column_int64(stmt, 4)
                });
            }
            return status == 101 ? 0 : status; // SQLITE_DONE
        } finally {
            if (stmt != IntPtr.Zero) sqlite3_finalize(stmt);
            if (db != IntPtr.Zero) sqlite3_close(db);
        }
    }
}
'@

function File-Prefix($path, $count) {
    $sharing = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $file = [IO.File]::Open($path, 'Open', 'Read', $sharing)
    try {
        $prefix = [byte[]]::new($count)
        [void]$file.Read($prefix, 0, $prefix.Length)
        ,$prefix
    } finally { $file.Dispose() }
}

function Committed-Stamp($path) {
    # Chrome may hold an exclusive SQLite lock between writes. An immutable
    # read is safe to consider only with stable rollback-mode files and no
    # active journal. Never bypass locking on a WAL database.
    $header = File-Prefix $path 100
    if ($header[18] -ne 1 -or $header[19] -ne 1 -or (Test-Path -LiteralPath ($path+'-wal'))) { return }
    $main = Get-Item -LiteralPath $path
    $journal = Get-Item -LiteralPath ($path+'-journal') -ErrorAction SilentlyContinue
    if ($journal -and @(File-Prefix $journal.FullName 8 | Where-Object { $_ -ne 0 }).Count) { return }
    "$($main.Length):$($main.LastWriteTimeUtc.Ticks):$([Convert]::ToBase64String($header)):$($journal.Length):$($journal.LastWriteTimeUtc.Ticks)"
}

if ($request.profile -notmatch '^(Default|Profile [0-9]+)$') { throw 'Invalid Chrome download profile.' }
$folder = Get-Item -LiteralPath (Join-Path $env:LOCALAPPDATA ('Google\Chrome\User Data\' + $request.profile))
$file = Get-Item -LiteralPath (Join-Path $folder.FullName 'History') -ErrorAction SilentlyContinue
$rows = $null
if ($file -and -not ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
    -not ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    $uri = ([Uri]::new($file.FullName)).AbsoluteUri + '?mode=ro'
    $items = [Collections.Generic.List[object]]::new()
    $status = [ChromeDownloadHistory]::Read($uri, $request.page, $request.after, $items)
    if ($status -eq 0) { $rows = $items.ToArray() }
    elseif ($status -in 5,6) {
        try {
            $stamp = Committed-Stamp $file.FullName
            if ($stamp) {
                $items.Clear()
                $status = [ChromeDownloadHistory]::Read($uri+'&immutable=1', $request.page, $request.after, $items)
                if ($status -eq 0 -and $stamp -ceq (Committed-Stamp $file.FullName)) { $rows = $items.ToArray() }
            }
        } catch [IO.IOException] {
            # The Chrome database or journal changed while being observed.
        }
    }
}
@{ rows = $rows } | ConvertTo-Json -Compress -Depth 4
