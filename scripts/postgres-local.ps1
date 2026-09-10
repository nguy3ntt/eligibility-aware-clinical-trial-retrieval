param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status',
      [string]$Bin = 'C:\Program Files\PostgreSQL\17\bin')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $repoRoot 'artifacts/postgres-local'
$cluster = Join-Path $runtime 'data'
$envPath = Join-Path $repoRoot '.env.api.local'
$ctl = Join-Path $Bin 'pg_ctl.exe'
if (!(Test-Path -LiteralPath $ctl)) { throw 'Install PostgreSQL or supply its binary folder with -Bin.' }
if ($Action -eq 'Status') {
    if (Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION')) { & $ctl status -D $cluster }
    else { Write-Output 'Project PostgreSQL has not been initialized.' }
    exit
}
if ($Action -eq 'Stop') {
    if (!(Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION'))) { throw 'No project cluster.' }
    & $ctl stop -D $cluster -m fast -w
    if ($LASTEXITCODE -ne 0) { throw 'Project PostgreSQL stop failed.' }
    exit
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (!(Test-Path -LiteralPath (Join-Path $cluster 'PG_VERSION'))) {
    if (Test-Path -LiteralPath $envPath) { throw 'Existing API environment found; refusing to replace it.' }
    $password = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
    $passwordFile = Join-Path $runtime 'init-password.tmp'
    [IO.File]::WriteAllText($passwordFile, $password)
    try {
        & (Join-Path $Bin 'initdb.exe') -D $cluster -U ctr_local --encoding=UTF8 --locale=C --auth=scram-sha-256 --pwfile=$passwordFile
        if ($LASTEXITCODE -ne 0) { throw 'Cluster initialization failed; partial output retained for inspection.' }
    } finally {
        Remove-Item -LiteralPath $passwordFile -Force
    }
    [IO.File]::WriteAllText($envPath, "DATABASE_URL=postgresql+psycopg://ctr_local:${password}@127.0.0.1:55432/postgres`n")
}
& $ctl status -D $cluster *> $null
if ($LASTEXITCODE -eq 0) { Write-Output 'Project PostgreSQL already running on loopback port 55432.'; exit }
# This cluster is separate from installed Windows services. Never change their data or config.
$log = Join-Path $runtime 'server.log'
$arguments = @('start', '-D', ('"' + $cluster + '"'), '-l', ('"' + $log + '"'), '-o', '"-h 127.0.0.1 -p 55432"', '-w')
$started = Start-Process -FilePath $ctl -ArgumentList $arguments -WindowStyle Hidden -PassThru
# Wait only for pg_ctl, not its long-lived PostgreSQL descendant process tree.
$started.WaitForExit()
if ($started.ExitCode -ne 0) { throw 'Project PostgreSQL startup failed; inspect the ignored server log.' }
Write-Output 'Project PostgreSQL ready on loopback port 55432. Credentials stay in ignored .env.api.local.'
