import json
import subprocess

import pytest

from evaluation.release_source import export, safe_source


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_export_identifies_uncommitted_source_and_excludes_private_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    (root / ".gitignore").write_text(".env*\nAGENTS.md\nartifacts/\n")
    (root / "app.py").write_text("pass\n")
    # Only this invented temporary repository is committed to establish a test HEAD.
    git(root, "add", ".gitignore", "app.py")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    (root / ".env.local").write_text("INVENTED_SECRET")
    (root / "AGENTS.md").write_text("local only")
    (root / "new.py").write_text("value = 1\n")
    output = tmp_path / "export"
    result = export(root, output)
    assert result["working_tree_changed"] is True
    assert {r["path"] for r in result["files"]} == {".gitignore", "app.py", "new.py"}
    assert "INVENTED_SECRET" not in json.dumps(result)
    assert not (output / "source" / ".env.local").exists()
    (root / "app.py").write_text("value = 2\n")
    assert export(root, tmp_path / "second")["source_sha256"] != result["source_sha256"]


def test_outside_source_and_existing_destination_are_rejected(tmp_path):
    (tmp_path / "outside").write_text("invented")
    with pytest.raises(ValueError, match="contained"):
        safe_source(tmp_path / "repo", "../outside")
