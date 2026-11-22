# Run once in an administrator PowerShell if this PC has no OpenSSH Server.
$ErrorActionPreference = 'Stop'
$capability = 'OpenSSH.Server~~~~0.0.1.0'
if ((Get-WindowsCapability -Online -Name $capability).State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $capability | Out-Null
}
Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd
Write-Output 'Windows OpenSSH Server is running. Authorize the Hermes host public key for the Chrome user.'
