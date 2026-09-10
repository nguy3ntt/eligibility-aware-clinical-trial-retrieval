param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Resolve-Path (Join-Path $repoRoot '../.venv/Scripts/python.exe')).Path
$runtime = Join-Path $repoRoot 'artifacts/api-local'
$pidPath = Join-Path $runtime 'server.pid'
$owned = $null
if (Test-Path -LiteralPath $pidPath) {
    $apiProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $owned = Get-CimInstance Win32_Process -Filter "ProcessId = $apiProcessId"
    if ($owned -and ($owned.ExecutablePath -ne $python -or $owned.CommandLine -notlike '*uvicorn backend.app.main:app*')) {
        throw 'Recorded PID no longer belongs to this API; no process was changed.'
    }
}
if ($Action -eq 'Status') {
    if ($owned) { Write-Output "Research API running on http://127.0.0.1:8000 (PID $apiProcessId)." }
    else { Write-Output 'Research API is not running through this wrapper.' }
    exit
}
if ($Action -eq 'Stop') {
    if ($owned) { Stop-Process -Id $apiProcessId }
    Write-Output 'Research API stopped; saved PostgreSQL records retained.'
    exit
}
if ($owned) { Write-Output 'Research API already running.'; exit }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is occupied; no existing listener was changed.'
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$server = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8000','--workers','1','--no-access-log','--log-level','warning' -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log') -PassThru
$server.Id | Set-Content -LiteralPath $pidPath
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { Write-Output 'Research API ready at http://127.0.0.1:8000/docs'; exit }
    } catch { Start-Sleep -Seconds 1 }
}
throw 'API did not become live; inspect ignored runtime logs.'
