"""Read-only setup checks on isolated invented files and service responses."""

import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipelines import setup_check as setup


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "package_version", lambda _: "invented-version")
    monkeypatch.setattr(setup, "need_files", lambda *_: "Present")
    for name in (
        "model",
        "optional_model",
        "frontend",
        "app_artifacts",
        "topics",
        "benchmark_artifacts",
        "benchmark_sources",
    ):
        monkeypatch.setattr(setup, name, lambda *_: "Fixture check passed")
    config = SimpleNamespace(api_catalog_id="invented")
    monkeypatch.setattr(setup, "settings", lambda _: config)
    return tmp_path


def test_fixture_profile_never_loads_research_models_or_contacts_services(prepared, monkeypatch):
    def forbidden(*_):
        pytest.fail("unnecessary research or network access")

    for name in ("model", "optional_model", "frontend", "settings", "read_http"):
        monkeypatch.setattr(setup, name, forbidden)
    report = setup.collect(prepared, "tests")
    assert report["status"] == "checks_passed"
    assert len(report["checks"]) == 4


def test_missing_packages_have_an_actionable_fix_without_importing_them(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "package_version", lambda _: None)
    report = setup.collect(tmp_path, "tests")
    assert report["status"] == "blocked"
    row = next(r for r in report["checks"] if r["id"] == "python_packages")
    assert "requirements/ci.txt" in row["next_step"] and "pytest" in row["next_step"]


def test_optional_models_do_not_block_default_app_and_offline_never_probes(prepared, monkeypatch):
    def absent(*_):
        raise FileNotFoundError("INVENTED_SECRET")

    monkeypatch.setattr(setup, "optional_model", absent)
    monkeypatch.setattr(setup, "read_http", lambda *_: pytest.fail("offline check used network"))
    report = setup.collect(prepared, "app")
    assert report["status"] == "checks_passed"
    assert [r["status"] for r in report["checks"] if r["id"] in {"nli", "reranker"}] == [
        "warning",
        "warning",
    ]
    assert "INVENTED_SECRET" not in json.dumps(report)
    assert next(r for r in report["checks"] if r["id"] == "services")["status"] == "not_checked"


def test_fixed_benchmark_requires_reranker_but_not_running_services(prepared, monkeypatch):
    monkeypatch.setattr(setup, "optional_model", lambda *_: (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(
        setup, "read_http", lambda *_: pytest.fail("offline benchmark used services")
    )
    report = setup.collect(prepared, "benchmark")
    assert report["status"] == "blocked"
    assert next(r for r in report["checks"] if r["id"] == "reranker")["required"] is True


def test_service_outage_and_secret_exception_are_safe_and_nonfatal(prepared, monkeypatch):
    def fail(*_):
        raise RuntimeError("postgresql://user:INVENTED_SECRET@localhost/db")

    for name in ("database_ready", "qdrant_ready", "api_ready", "frontend_ready"):
        monkeypatch.setattr(setup, name, fail)
    report = setup.collect(prepared, "app", online=True)
    assert report["status"] == "blocked"
    assert len([r for r in report["checks"] if r["status"] == "fail"]) == 4
    assert "INVENTED_SECRET" not in json.dumps(report)


@pytest.mark.parametrize(
    "packet",
    [
        {"status": "ok"},
        {"status": "ready", "qdrant": "down"},
        {
            "status": "ready",
            "qdrant": "ready",
            "postgres": {"status": "ready"},
            "catalog_id": "other",
        },
    ],
)
def test_http_success_is_not_sufficient_readiness(monkeypatch, packet):
    monkeypatch.setattr(setup, "read_http", lambda *_: json.dumps(packet).encode())
    with pytest.raises(ValueError):
        setup.api_ready(SimpleNamespace(api_catalog_id="invented"))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com",
        "http://user:secret@localhost",
        "http://127.0.0.1/?token=secret",
        "http://localhost/#secret",
    ],
)
def test_remote_or_credential_bearing_urls_fail_before_any_request(monkeypatch, url):
    monkeypatch.setattr(
        setup.urllib.request, "build_opener", lambda *_: pytest.fail("made an unsafe request")
    )
    with pytest.raises(ValueError):
        setup.read_http(url)


@pytest.mark.parametrize(
    "name", ["../outside", "C:/outside", "/outside", "sub/../../outside", r"..\outside"]
)
def test_manifest_paths_cannot_escape_their_root(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe"):
        setup.need_files(tmp_path, (name,))


def test_locked_frontend_dependency_drift_and_old_node_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "tool_version", lambda _: "24.16.0")
    manifest = {"dependencies": {"vite": "1.0.0"}, "devDependencies": {}}
    save(tmp_path / "frontend/package.json", manifest)
    save(
        tmp_path / "frontend/package-lock.json",
        {"packages": {"": manifest, "node_modules/vite": {"version": "1.0.0"}}},
    )
    save(tmp_path / "frontend/node_modules/vite/package.json", {"version": "0.0.1"})
    with pytest.raises(ValueError, match="differs from lock"):
        setup.frontend(tmp_path)
    monkeypatch.setattr(setup, "tool_version", lambda _: "23.0.0")
    with pytest.raises(ValueError, match="Node"):
        setup.frontend(tmp_path)


def test_missing_shard_or_damaged_weight_is_not_silently_accepted(tmp_path):
    from pipelines.embeddings import MODELS, REQUIRED_MODEL_FILES, file_record, model_directory

    root = model_directory(tmp_path / "models", MODELS["minilm"])
    root.mkdir(parents=True)
    for name in REQUIRED_MODEL_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invented fixture bytes")
    save(
        root / "snapshot.json",
        {
            "status": "complete",
            "model": asdict(MODELS["minilm"]),
            "files": [file_record(root / n, root) for n in sorted(REQUIRED_MODEL_FILES)],
        },
    )
    assert "not checked" in setup.model(tmp_path, "minilm", False)
    (root / "model.safetensors").write_text("damaged fixture")
    with pytest.raises(ValueError, match="checksum"):
        setup.model(tmp_path, "minilm", True)


def test_incompatible_source_and_dense_artifact_are_detected_even_without_deep_hashing(tmp_path):
    config = SimpleNamespace(
        processed_data_dir="data/processed", api_index_id="index", api_evidence_id="evidence"
    )
    index = tmp_path / "data/processed/index"
    evidence = index.parent / "evidence"
    save(
        index / "manifest.json", {"status": "complete", "version": "dense-index-v1", "documents": 1}
    )
    for name in ("documents.jsonl", "vectors.npy"):
        (index / name).write_text("invented")
    save(evidence / "evidence.json", {})
    save(
        evidence / "manifest.json",
        {
            "status": "complete",
            "version": "reranking-field-evidence-v1",
            "trials": 1,
            "artifact_sha256": "incorrect",
        },
    )
    with pytest.raises(ValueError, match="incompatible"):
        setup.app_artifacts(tmp_path, config, False)


def test_cli_runs_with_site_packages_disabled_and_returns_json_without_tracebacks():
    script = Path(setup.__file__).resolve()
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(script), "--profile", "tests", "--json"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "blocked" and report["next_steps"]
    assert "Traceback" not in result.stderr


def test_benchmark_rejects_wrong_query_runtime_or_model_even_with_present_files(
    tmp_path, monkeypatch
):
    from pipelines.embeddings import MODELS, model_directory
    from pipelines.release_index import FROZEN_DOCUMENT_COUNT, FROZEN_DOCUMENTS_SHA256

    index = tmp_path / "data/processed/release-full-minilm-v2"
    rendered = index.parent / "trec-ct-2021-render-v1"
    snapshot = model_directory(tmp_path / "models", MODELS["minilm"]) / "snapshot.json"
    save(snapshot, {"fixture": True})
    encoder = {
        "model": asdict(MODELS["minilm"]),
        "snapshot_sha256": setup.hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "normalization": "l2",
        "dtype": "float32",
        "prompt": "",
        "python": setup.platform.python_version(),
        "platform": setup.platform.platform(),
        "machine": setup.platform.machine(),
        "processor": setup.platform.processor(),
        "versions": {"numpy": "fixture-version"},
    }
    manifest = {
        "status": "complete",
        "documents": FROZEN_DOCUMENT_COUNT,
        "source": {"documents_sha256": FROZEN_DOCUMENTS_SHA256},
        "encoder": encoder,
        "chunks": [{"directory": "part", "checkpoint": {"path": "chunk.json"}}],
    }
    save(index / "manifest.json", manifest)
    save(index / "chunk.json", {})
    save(index / "part/documents.jsonl", {})
    save(index / "part/vectors.npy", {})
    save(
        rendered / "manifest.json",
        {
            "status": "complete",
            "documents": FROZEN_DOCUMENT_COUNT,
            "files": [{"sha256": FROZEN_DOCUMENTS_SHA256}],
        },
    )
    save(rendered / "documents.jsonl", {})
    monkeypatch.setattr(setup, "package_version", lambda _: "fixture-version")
    assert "runtime matches" in setup.benchmark_artifacts(tmp_path, False)
    monkeypatch.setattr(setup, "package_version", lambda _: "different-version")
    with pytest.raises(ValueError, match="runtime"):
        setup.benchmark_artifacts(tmp_path, False)
    monkeypatch.setattr(setup, "package_version", lambda _: "fixture-version")
    manifest["encoder"]["snapshot_sha256"] = "different model bytes"
    save(index / "manifest.json", manifest)
    with pytest.raises(ValueError, match="model identity"):
        setup.benchmark_artifacts(tmp_path, False)


def test_http_does_not_follow_redirects_or_use_environment_proxy(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.error import HTTPError

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/unexpected")
            elif self.path == "/unexpected":
                self.server.followed = True
                self.send_response(200)
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b"invented readiness")

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.followed = False
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert setup.read_http(url + "/") == b"invented readiness"
        with pytest.raises(HTTPError) as error:
            setup.read_http(url + "/redirect")
        assert error.value.code == 302
        assert server.followed is False
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


@pytest.mark.parametrize("code", [0, 1])
def test_powershell_wrapper_forwards_arguments_and_exit_code(tmp_path, code):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell unavailable")
    scripts = tmp_path / "repo/scripts"
    scripts.mkdir(parents=True)
    target = scripts / "check-setup.ps1"
    shutil.copyfile("scripts/check-setup.ps1", target)
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "param($Target,$Code)\nfunction fake-python {\n"
        ' if ((Get-Location).Path -notlike "*repo") { throw "wrong cwd" }\n'
        ' Write-Output ($args -join "|")\n $global:LASTEXITCODE = [int]$Code\n}\n'
        "& $Target -Python fake-python -Profile tests -Online -Verify -Json\nexit $LASTEXITCODE\n"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(harness), str(target), str(code)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == code, result.stderr
    assert "-B|-m|pipelines.setup_check|--profile|tests|--online|--verify|--json" in result.stdout
