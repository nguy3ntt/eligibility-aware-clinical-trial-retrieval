"""Execute launcher ownership checks with fake process and network inventories."""

import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell not installed")


@pytest.mark.parametrize(
    "name,runtime",
    [("qdrant", "qdrant-1.19.0"), ("api", "api-local"), ("frontend", "frontend-local")],
)
@pytest.mark.parametrize("action", ["Start", "Stop"])
def test_recycled_pid_never_stops_foreign_process_or_bypasses_port_guard(
    tmp_path, name, runtime, action
):
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    source = Path("scripts") / f"{name}-local.ps1"
    shutil.copyfile(source, scripts / source.name)
    directory = root / "artifacts" / runtime
    directory.mkdir(parents=True)
    (directory / "server.pid").write_text("12345")
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("invented placeholder; never execute")
    vite = root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("invented placeholder; never execute")
    harness = tmp_path / "check.ps1"
    harness.write_text(
        """
param($Target, $Action)
function Get-Process { [PSCustomObject]@{ Id=12345; Path='unrelated.exe' } }
function Get-CimInstance {
  [PSCustomObject]@{ ExecutablePath='unrelated.exe'; CommandLine='unrelated' }
}
function Get-Command { [PSCustomObject]@{ Source='invented-node.exe' } }
function Get-NetTCPConnection { [PSCustomObject]@{ LocalPort=6333 } }
function Stop-Process { throw 'UNSAFE_STOP' }
function Start-Process { throw 'UNSAFE_START' }
try { & $Target -Action $Action; exit 9 }
catch {
  $message = $_.Exception.Message
  if ($message -like '*UNSAFE*') { Write-Output $message; exit 8 }
  if ($Action -eq 'Start' -and $message -like '*Port*occupied*') { exit 0 }
  if ($Action -eq 'Stop' -and $message -like '*Recorded PID*') { exit 0 }
  Write-Output $message; exit 7
}
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(harness), str(scripts / source.name), action],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
