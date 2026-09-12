param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendRoot = Join-Path $repoRoot 'frontend'
$nodePath = @(Get-Command node -CommandType Application)[0].Source
$vitePath = Join-Path $frontendRoot 'node_modules/vite/bin/vite.js'
$runtime = Join-Path $repoRoot 'artifacts/frontend-local'
$pidPath = Join-Path $runtime 'server.pid'
$owned = $null
if (Test-Path -LiteralPath $pidPath) {
    $frontendProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $owned = Get-CimInstance Win32_Process -Filter "ProcessId = $frontendProcessId"
    if ($owned -and ($owned.ExecutablePath -ne $nodePath -or -not $owned.CommandLine.Contains($vitePath))) {
        if ($Action -eq 'Start') { $owned = $null }
        else { throw 'Recorded PID no longer belongs to this frontend; no process was changed.' }
    }
}
if ($Action -eq 'Status') {
    if ($owned) { Write-Output 'Research workspace running at http://127.0.0.1:5173.' }
    else { Write-Output 'Research workspace is not running through this wrapper.' }
    exit
}
if ($Action -eq 'Stop') {
    if ($owned) { Stop-Process -Id $frontendProcessId }
    Write-Output 'Research workspace stopped; no stored evidence was changed.'
    exit
}
if ($owned) { Write-Output 'Research workspace already running.'; exit }
if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Install frontend dependencies with npm ci first.' }
if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 5173 is occupied; no existing listener was changed.'
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$server = Start-Process -FilePath $nodePath -ArgumentList ('"' + $vitePath + '"') -WorkingDirectory $frontendRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log') -PassThru
$server.Id | Set-Content -LiteralPath $pidPath
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -TimeoutSec 2
        if ($page.StatusCode -eq 200) { Write-Output 'Research workspace ready at http://127.0.0.1:5173'; exit }
    } catch { Start-Sleep -Seconds 1 }
}
throw 'Workspace did not become ready; inspect ignored runtime logs.'
