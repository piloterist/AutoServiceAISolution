# Run-AlphaExport.ps1 - starts 1C, runs the export processing (EPF) and waits until 1C closes itself.
# Started from a desktop shortcut (see Setup-AlphaExportShortcut.ps1). ASCII only: texts are \u escapes.
param(
    [string]$Exe = 'C:\Program Files (x86)\1cv8\8.3.16.1148\bin\1cv8.exe',
    [string]$Base = 'ONEC-6\U036-alfa',
    [string]$Epf = (Join-Path $PSScriptRoot 'ExportOrderChanges.epf'),
    [int]$TimeoutMinutes = 30,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

function T([string]$s) { [regex]::Unescape($s) }

function Show([string]$text, [string]$icon = 'Information') {
    if ($Quiet) { Write-Host $text; return }
    [void][System.Windows.Forms.MessageBox]::Show($text, (T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u0432 ESP'), 'OK', $icon)
}

$dir = Join-Path $env:APPDATA 'AlphaExport'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$credFile = Join-Path $dir 'cred.txt'
$logFile = Join-Path $dir 'export.log'

function Log([string]$text) {
    Add-Content -Path $logFile -Value ('{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $text)
}

# One run at a time.
$mutex = New-Object System.Threading.Mutex($false, 'Local\EspAlphaExport')
if (-not $mutex.WaitOne(0)) {
    Show (T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u0443\u0436\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f. \u041f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435 \u0435\u0451 \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f.') 'Warning'
    exit 1
}

try {
    if (-not (Test-Path $credFile)) {
        Show (T '\u041f\u0430\u0440\u043e\u043b\u044c 1\u0421 \u043d\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d. \u041e\u0434\u0438\u043d \u0440\u0430\u0437 \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 Setup-AlphaExportShortcut.ps1.') 'Error'
        exit 2
    }
    $secure = ConvertTo-SecureString (Get-Content $credFile -Raw).Trim()
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $pass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

    if (-not (Test-Path $Epf)) {
        Show ((T '\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0444\u0430\u0439\u043b \u0432\u044b\u0433\u0440\u0443\u0437\u043a\u0438:') + ' ' + $Epf) 'Error'
        exit 5
    }

    # The 1C user name is asked once by the setup script (user.txt, UTF-8).
    $userFile = Join-Path $dir 'user.txt'
    if (Test-Path $userFile) { $user = ([IO.File]::ReadAllText($userFile, [Text.Encoding]::UTF8)).Trim() }
    else { $user = T '\u041f\u0430\u043d \u0421\u0442\u0430\u043d\u0438\u0441\u043b\u0430\u0432 \u0412\u044f\u0447\u0435\u0441\u043b\u0430\u0432\u043e\u0432\u0438\u0447' }
    $argLine = 'ENTERPRISE /S"{0}" /N"{1}" /P"{2}" /Execute "{3}"' -f $Base, $user, $pass, $Epf

    Log 'start'
    $started = Get-Date
    $p = Start-Process -FilePath $Exe -ArgumentList $argLine -PassThru
    if ($p.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        $secs = [int]((Get-Date) - $started).TotalSeconds
        Log "done in $secs s"
        Show ((T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430. \u0414\u0430\u043d\u043d\u044b\u0435 \u043f\u043e\u044f\u0432\u044f\u0442\u0441\u044f \u0432 \u0441\u0438\u0441\u0442\u0435\u043c\u0435 \u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u0438\u0445 \u043c\u0438\u043d\u0443\u0442.'))
    }
    else {
        try { $p.Kill() } catch { }
        Log "timeout after $TimeoutMinutes min, 1C killed"
        Show ((T '\u0412\u044b\u0433\u0440\u0443\u0437\u043a\u0430 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0438\u043b\u0430\u0441\u044c \u0432\u043e\u0432\u0440\u0435\u043c\u044f, 1\u0421 \u0437\u0430\u043a\u0440\u044b\u0442\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437 \u0438\u043b\u0438 \u0441\u043e\u043e\u0431\u0449\u0438\u0442\u0435 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443.')) 'Error'
        exit 3
    }
}
catch {
    Log ('error: ' + $_.Exception.Message)
    Show ((T '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0432\u044b\u0433\u0440\u0443\u0437\u043a\u0443:') + ' ' + $_.Exception.Message) 'Error'
    exit 4
}
finally {
    $mutex.ReleaseMutex()
}
