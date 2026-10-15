# PowerShell від адміна:  powershell -ExecutionPolicy Bypass -File .\install.ps1
# Реєструє дві задачі Task Scheduler для поточного користувача (LogonType Interactive: їм треба твій екран):
#   Desk        pythonw desk.py при вході, без вікна, живе весь час (хоткеї Pause / Ctrl+Pause)
#   DeskMorning morning.ps1 щодня о 09:00 і при вході (сам перевіряє, чи вже запускався сьогодні)
# Потрібні Python у PATH і: pip install -r requirements.txt

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "pythonw.exe not found next to $python, falling back to python.exe (console window will show)."
    $pythonw = $python
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$noLimit = [TimeSpan]::Zero
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Write-Host "Folder: $here"
Write-Host "Python: $pythonw"
New-Item -ItemType Directory -Force -Path (Join-Path $here 'state') | Out-Null

# --- Desk: хоткеї, при вході ---
$deskAction = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$here\desk.py`"" -WorkingDirectory $here
$deskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$deskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit $noLimit -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName 'Desk' -Action $deskAction -Trigger $deskTrigger -Settings $deskSettings -Principal $principal -Force | Out-Null
Write-Host 'Desk registered (at logon, no console).'

# --- DeskMorning: о 09:00 і при вході ---
$hour = 9
try {
    $cfg = Get-Content (Join-Path $here 'desk.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $hour = [int]$cfg.morning.hour
} catch { Write-Host 'desk.json not readable, using 09:00' }
$morningAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\morning.ps1`"" -WorkingDirectory $here
$morningTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($hour))),
    (New-ScheduledTaskTrigger -AtLogOn -User $user)
)
$morningSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName 'DeskMorning' -Action $morningAction -Trigger $morningTriggers -Settings $morningSettings -Principal $principal -Force | Out-Null
Write-Host "DeskMorning registered (daily at ${hour}:00 and at logon)."

# Вбити копію, запущену руками з терміналу, і підняти задачу
Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'desk\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-ScheduledTask -TaskName 'Desk'
Start-Sleep -Seconds 4
$running = Get-CimInstance Win32_Process -Filter "name='pythonw.exe' OR name='python.exe'" | Where-Object { $_.CommandLine -match 'desk\.py' }
if ($running) {
    Write-Host "Desk is running (pid $($running.ProcessId)). Press Pause to check the overlay."
} else {
    Write-Host 'WARNING: Desk did not start. Check state\desk.log.'
}
Write-Host 'Done. DeskMorning runs itself at the next 09:00 or logon; to try now: schtasks /run /tn DeskMorning'
