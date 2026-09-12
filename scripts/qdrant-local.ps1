param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimePath = Join-Path $repoRoot 'artifacts/qdrant-1.19.0'
$exePath = Join-Path $runtimePath 'qdrant.exe'
$pidPath = Join-Path $runtimePath 'server.pid'
$expectedHash = '369c562eae3d89333a13abfdb522fa209e3f587c1217a1059d817e80814ea9d4'

function Get-OwnedServer {
    if (!(Test-Path -LiteralPath $pidPath)) { return $null }
    $serverId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $serverProcess = Get-Process -Id $serverId -ErrorAction SilentlyContinue
    if ($serverProcess -and $serverProcess.Path -ne $exePath) {
        # A recycled PID is stale bookkeeping, never permission to stop its new owner.
        # Start still checks both ports before launching a verified executable.
        if ($Action -eq 'Start') { return $null }
        throw 'Recorded PID belongs to another executable; no process was changed.'
    }
    return $serverProcess
}

$ownedServer = Get-OwnedServer
if ($Action -eq 'Stop') {
    if ($ownedServer) { Stop-Process -Id $ownedServer.Id; $ownedServer.WaitForExit() }
    Write-Output 'Local Qdrant stopped. Persistent data retained.'
    exit 0
}
if ($Action -eq 'Status') {
    if ($ownedServer) { Write-Output "Local Qdrant running (PID $($ownedServer.Id))." }
    else { Write-Output 'Local Qdrant is not running through this wrapper.' }
    exit 0
}
if ($ownedServer) { Write-Output 'Local Qdrant is already running.'; exit 0 }

# Never start a second server on ports owned by another application.
$listener = Get-NetTCPConnection -LocalPort 6333,6334 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw 'Port 6333 or 6334 is occupied; inspect the existing service first.' }
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
if (!(Test-Path -LiteralPath $exePath)) {
    $zipPath = Join-Path $runtimePath 'qdrant.zip'
    Invoke-WebRequest -Uri 'https://github.com/qdrant/qdrant/releases/download/v1.19.0/qdrant-x86_64-pc-windows-msvc.zip' -OutFile $zipPath
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($zipHash -ne '980cb2e1ae771155cf211da8c0a8a9206b6482bd4effdc4db994d3adb707b087') {
        throw 'Qdrant archive checksum mismatch; executable was not installed.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entry = $archive.GetEntry('qdrant.exe')
        if (!$entry) { throw 'Expected executable is missing from the release archive.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $exePath, $false)
    } finally { $archive.Dispose() }
}
if ((Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Qdrant executable checksum mismatch; refusing to start.'
}

# Extended paths avoid the Windows MAX_PATH failure in payload index creation.
$previousStorage = $env:QDRANT__STORAGE__STORAGE_PATH
$previousSnapshots = $env:QDRANT__STORAGE__SNAPSHOTS_PATH
try {
    $env:QDRANT__STORAGE__STORAGE_PATH = '\\?\' + (Join-Path $repoRoot 'qdrant_storage\storage')
    $env:QDRANT__STORAGE__SNAPSHOTS_PATH = '\\?\' + (Join-Path $repoRoot 'qdrant_storage\snapshots')
    $serverProcess = Start-Process -FilePath $exePath -ArgumentList '--config-path','infrastructure/qdrant-local.yaml' -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'server.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'server.stderr.log') -PassThru
    $serverProcess.Id | Set-Content -LiteralPath $pidPath
} finally {
    $env:QDRANT__STORAGE__STORAGE_PATH = $previousStorage
    $env:QDRANT__STORAGE__SNAPSHOTS_PATH = $previousSnapshots
}
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($serverProcess.HasExited) { throw "Qdrant exited; inspect logs in $runtimePath" }
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:6333/' -TimeoutSec 1
        if ($response.version -eq '1.19.0') {
            Write-Output "Qdrant 1.19.0 ready at http://127.0.0.1:6333 (PID $($serverProcess.Id))."
            exit 0
        }
    } catch { Start-Sleep -Milliseconds 250 }
}
throw "Qdrant did not become ready; inspect logs in $runtimePath"
