# Ранок. Запускається Task Scheduler'ом (DeskMorning): щодня о 09:00 і при вході в систему.
# Що робить:
#   1. якщо сьогодні вже запускався або ще нема 9:00 - нічого;
#   2. просить апку скласти план на сьогодні, якщо його ще нема (/api/plan/generate);
#   3. відкриває апку окремим вікном Chrome без адресного рядка (або в браузері за замовчуванням).
# Лог: state\morning.log.

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$cfg = Get-Content (Join-Path $here 'desk.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$state = Join-Path $here 'state'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$marker = Join-Path $state 'morning.txt'
$logFile = Join-Path $state 'morning.log'
$today = (Get-Date).ToString('yyyy-MM-dd')

function Log($message) {
    Add-Content -Path $logFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
}

if ((Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $today)) {
    Log 'already ran today'
    exit 0
}
$hour = [int]$cfg.morning.hour
if ((Get-Date).Hour -lt $hour) {
    Log "before ${hour}:00, skip"
    exit 0
}

# 1. План на сьогодні. Після входу мережа може піднятись не одразу, тому три спроби.
$appUrl = ([string]$cfg.app_url).TrimEnd('/')
$headers = @{ 'x-automation-token' = [string]$cfg.token }
$planned = $false
for ($try = 1; $try -le 3 -and -not $planned; $try++) {
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$appUrl/api/plan/generate" -Headers $headers -TimeoutSec 90
        Log "plan: created=$($r.created) items=$($r.items) $($r.error)"
        $planned = $true
    } catch {
        Log "plan request failed (try $try): $($_.Exception.Message)"
        if ($try -lt 3) { Start-Sleep -Seconds 20 }
    }
}

# 2. Апка окремим вікном.
$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($chrome) {
    Start-Process $chrome "--app=$appUrl/"
} else {
    Start-Process "$appUrl/"
}
Set-Content -Path $marker -Value $today
Log 'opened app'
