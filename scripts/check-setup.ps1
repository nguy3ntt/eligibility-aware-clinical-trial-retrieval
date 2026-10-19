param(
    [ValidateSet('tests', 'app', 'benchmark')][string]$Profile = 'app',
    [switch]$Online,
    [switch]$Verify,
    [switch]$Json,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# Existing native service launchers use the short sibling virtual environment.
if (!$Python) {
    $candidate = Join-Path $repoRoot '../.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $candidate) { $Python = (Resolve-Path -LiteralPath $candidate).Path }
    else {
        $available = @(Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\*' })
        if ($available.Count -gt 0) { $Python = $available[0].Source }
    }
    if (!$Python) {
        Write-Error 'Install Python 3.12, then follow docs/setup.md. No environment was changed.'
        exit 1
    }
}
$arguments = @('-B', '-m', 'pipelines.setup_check', '--profile', $Profile)
if ($Online) { $arguments += '--online' }
if ($Verify) { $arguments += '--verify' }
if ($Json) { $arguments += '--json' }
Push-Location -LiteralPath $repoRoot
try {
    & $Python @arguments
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
