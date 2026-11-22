# Chrome on a Windows device

Keep Hermes on macOS and choose the existing Chrome profile on a Windows PC.
The plugin connects through OpenSSH and uses the same `browser_exec` and site
controls. Windows uses Google Chrome, Windows PowerShell, and OpenSSH Server.
Python and the plugin dependencies run on the Mac. Windows needs neither
Python nor Node.js.

## Prepare Windows once

1. Install Google Chrome 144 or newer and open it under the Windows account that
   Hermes will use for SSH. Sign in to the desktop and keep that session active.
2. In Chrome, open `chrome://inspect/#remote-debugging` and check **Allow remote
   debugging for this browser instance**. The checkbox is the initial setup.
   The plugin handles a subsequent supported connection dialog for its own
   verified connection. The current Windows adapter recognizes English and
   Indonesian dialog text.
3. If needed, run `setup-windows-ssh.ps1` from this repository in an
   administrator PowerShell. This installs the Windows OpenSSH capability and
   starts its service. Authorize the Mac's **public** SSH key under the same
   Windows account that runs Chrome. Windows uses different authorized-key
   files for standard users and administrators.
   [Microsoft OpenSSH setup](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
   · [Microsoft public-key setup](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)

Use a Windows LAN address on the same network. Across networks, use the PC's
Tailscale IP or MagicDNS hostname after connecting both devices to your tailnet.
The destination still runs Windows OpenSSH. Keep SSH reachable only from your
trusted network or devices. Chrome's debugging port stays on Windows loopback.
[Tailscale device connectivity](https://tailscale.com/docs/how-to/connect-to-devices)

## Pair it with Hermes

On the Mac, add an OpenSSH alias to `~/.ssh/config`.

```sshconfig
Host hermes-chrome-pc
    HostName chrome-pc.example.ts.net
    User windows-user
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Use your own Windows address, user, and private-key path. Verify the Windows
host fingerprint when connecting for the first time, then confirm key login
with `ssh -T -o BatchMode=yes hermes-chrome-pc whoami`.
The Windows SSH server must allow local forwarding for this connection. The
Windows OpenSSH default allows it.
[Microsoft OpenSSH server configuration](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration)

Run the setup command on the Mac from the same plugin revision you installed
in Hermes. It installs the companion in the Windows account's
`%LOCALAPPDATA%\HermesOriginalChrome`, adds the device through Hermes's
configuration CLI, and prints available profile IDs.

```sh
cd ~/.hermes/plugins/original-chrome-default
python3 setup_windows.py hermes-chrome-pc --device windows
```

If you use a separate Hermes profile, run it from that profile's installed
plugin directory.

Run it again when an update changes the Windows companion. Windows interactive
operations use temporary tasks in the signed-in SSH user's desktop session.

Use `--profile "Profile 1"` to pin a recognized directory ID, or omit it to use
the last-used Windows Chrome profile. For a separate OpenSSH config, pass
`--ssh-config /path/to/config`. With plugin browser sessions closed,
`--make-default` selects this device for the plugin. The script adds the device under
`plugins.entries.original-chrome-default.settings.windows_devices`. Apply the
Hermes reload or restart that your installation requires after setup.

## Choose one Chrome device

`chrome_profiles` with `list_devices` shows the active device and available
choices. When the plugin's browser sessions have finished, use `set_device`
to apply the choice to all browser sessions in this Hermes profile. Use
`local` to return to the Mac. A failure on the selected device is reported
as a browser error.

```json
{"action":"set_device","device":"windows"}
```

Then use `list` and `select` to pick a Chrome profile on the selected device.
Use the same session alias in your next `browser_exec` call.

```json
{"action":"select","profile":"Profile 1","session":"research"}
```

One selection for a named session also applies when the first `browser_exec`
call uses ordinary browser code after selecting with `app`. If an alias
matches several sessions with a pending selection, use the exact session ID
returned by `chrome_profiles`.

## Downloads

The Windows version of the bundled Gemini and Flow download controls can
collect the original file from an owned Chrome page. The plugin matches the
download event to the page, transfers the completed file over SSH, and verifies
its SHA-256 on the Mac. The local path returned by the control is ready for
Hermes to attach. Chrome must save files to a local Windows download folder.
Existing editable site package copies are preserved by updates. Use the
bundled Windows-compatible versions of Gemini and Flow for these transfers.
Host 0.14.1 and Flow 0.4.6 let Flow resume a pending Windows download from
the original Chrome receipt.
See the [site package update procedure](TUTORIAL.md#use-google-flow)
for existing copies.

## Flow reference uploads

Pass a file on the Mac to the Flow `upload` control or in `references`.
The plugin copies it to a temporary directory on Windows through OpenSSH's
SFTP subsystem and verifies the size and SHA-256 before Chrome's file picker
receives it. The plugin removes the temporary Windows copy when Flow confirms
the upload or when it closes the task's browser session. Use host 0.13.2 and
Flow 0.4.5 or newer. The OpenSSH Server setup normally enables SFTP.
