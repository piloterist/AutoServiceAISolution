# Setup-AlphaExportShortcut.ps1 - run ONCE on the remote desktop (as the Windows user who will click the shortcut).
# Saves the 1C password encrypted for this Windows user only, and puts a shortcut on the desktop.
# ASCII only: texts are \u escapes.
param(
    [string]$Launcher = (Join-Path $PSScriptRoot 'Run-AlphaExport.ps1'),
    [string]$OneCExe = 'C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe'
)

$ErrorActionPreference = 'Stop'
function T([string]$s) { [regex]::Unescape($s) }

if (-not (Test-Path $Launcher)) {
    throw ('Run-AlphaExport.ps1 not found next to this script: ' + $Launcher)
}

$dir = Join-Path $env:APPDATA 'AlphaExport'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$defaultUser = T '\u041f\u0430\u043d \u0421\u0442\u0430\u043d\u0438\u0441\u043b\u0430\u0432 \u0412\u044f\u0447\u0435\u0441\u043b\u0430\u0432\u043e\u0432\u0438\u0447'
$user1c = Read-Host ((T '\u0418\u043c\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f 1\u0421 (Enter - \u043e\u0441\u0442\u0430\u0432\u0438\u0442\u044c') + ' ' + $defaultUser + ')')
if ([string]::IsNullOrWhiteSpace($user1c)) { $user1c = $defaultUser }
[IO.File]::WriteAllText((Join-Path $dir 'user.txt'), $user1c.Trim(), (New-Object Text.UTF8Encoding($false)))

$secure = Read-Host (T '\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f 1\u0421 (\u0441\u0438\u043c\u0432\u043e\u043b\u044b \u043d\u0435 \u043e\u0442\u043e\u0431\u0440\u0430\u0436\u0430\u044e\u0442\u0441\u044f)') -AsSecureString
if ($secure.Length -eq 0) { throw 'Empty password' }
# Encrypted with this Windows user's key (DPAPI): the file is useless on any other account/PC.
$secure | ConvertFrom-SecureString | Set-Content -Path (Join-Path $dir 'cred.txt')

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop ((T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0445 \u0432 ESP') + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Launcher + '"'
$lnk.WorkingDirectory = Split-Path $Launcher
if (Test-Path $OneCExe) { $lnk.IconLocation = $OneCExe + ',0' }
$lnk.Description = T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0445 \u0437\u0430\u043a\u0430\u0437-\u043d\u0430\u0440\u044f\u0434\u043e\u0432 \u0438\u0437 1\u0421 \u0432 ESP'
$lnk.Save()

Write-Host ((T '\u0413\u043e\u0442\u043e\u0432\u043e. \u042f\u0440\u043b\u044b\u043a \u0441\u043e\u0437\u0434\u0430\u043d:') + ' ' + $lnkPath)
