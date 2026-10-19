"""Read-only setup diagnostics; works before third-party dependencies are installed."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

VERSION = "setup-check-v1"
BASE = (
    "pip",
    "fastapi",
    "pydantic",
    "pydantic-settings",
    "httpx",
    "uvicorn",
    "pytest",
    "ruff",
    "numpy",
    "bm25s",
    "scipy",
    "threadpoolctl",
    "sqlalchemy",
    "alembic",
    "psycopg",
)
RESEARCH = (
    "torch",
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "safetensors",
)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def json_file(path: Path) -> dict:
    if path.stat().st_size > 4 * 1024**2:
        raise ValueError("manifest exceeds diagnostic bound")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("manifest object required")
    return value


def tool_version(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise ValueError("tool missing")
    result = subprocess.run([executable, "--version"], capture_output=True, timeout=5, check=True)
    match = re.fullmatch(rb"v?(\d+\.\d+\.\d+)[\r\n ]*", result.stdout)
    if not match:
        raise ValueError("unexpected tool version")
    return match[1].decode("ascii")


def loopback_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("plain loopback HTTP URL required")
    return url.rstrip("/")


def read_http(url: str) -> bytes:
    parsed = urlparse(url)
    loopback_url(f"{parsed.scheme}://{parsed.netloc}")
    if parsed.query or parsed.fragment:
        raise ValueError("unexpected HTTP parameters")

    # No proxy, redirects, cookies, authentication or response-body logging.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=3) as response:
        raw = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 1024 * 1024:
            raise ValueError("unexpected HTTP response")
        return raw


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, identity, title, run, remedy, *, required=True, level="checked"):
        try:
            detail = run()
            state = "pass"
        except Exception:
            # Exception strings may contain URLs, SQL parameters or credentials.
            detail = "Check could not be completed. Follow the suggested next step."
            state = "fail" if required else "warning"
        self.rows.append(
            {
                "id": identity,
                "title": title,
                "status": state,
                "detail": detail,
                "next_step": remedy if state != "pass" else None,
                "required": required,
                "level": level,
            }
        )
        return state == "pass"

    def skip(self, identity, title, detail):
        self.rows.append(
            {
                "id": identity,
                "title": title,
                "status": "not_checked",
                "detail": detail,
                "next_step": None,
                "required": False,
                "level": "not_checked",
            }
        )


def need_files(root: Path, names: tuple[str, ...]) -> str:
    if not all(contained(root, name).is_file() for name in names):
        raise ValueError("files missing")
    return "Required files are present."


def contained(root: Path, name: str) -> Path:
    path = Path(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or re.match(r"^[A-Za-z]:", name)
        or not (root / path).resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("unsafe manifest path")
    return root / path


def installed_packages(names: tuple[str, ...]) -> str:
    missing = [name for name in names if package_version(name) is None]
    if missing:
        # Distribution names come only from the fixed list, never from environment values.
        raise ValueError("dependencies missing")
    return f"All {len(names)} required distributions installed; import/inference not tested."


def python_runtime() -> str:
    if sys.version_info < (3, 11):  # noqa: UP036 - diagnose older bootstrap interpreters.
        raise ValueError("Python 3.11+ required")
    virtual = "virtual environment" if sys.prefix != sys.base_prefix else "system environment"
    return f"Python {platform.python_version()} ({virtual}); Python 3.12 is recommended."


def frontend(root: Path) -> str:
    node = tuple(map(int, tool_version("node").split(".")))
    tool_version("npm")
    if node < (24, 16, 0):
        raise ValueError("Node 24.16 or newer required")
    manifest = json_file(root / "frontend/package.json")
    lock = json_file(root / "frontend/package-lock.json")
    for kind in ("dependencies", "devDependencies"):
        if manifest.get(kind, {}) != lock["packages"][""].get(kind, {}):
            raise ValueError("package manifest and lock disagree")
        for name in manifest.get(kind, {}):
            expected = lock["packages"][f"node_modules/{name}"]["version"]
            if (
                json_file(contained(root / "frontend/node_modules", name + "/package.json"))[
                    "version"
                ]
                != expected
            ):
                raise ValueError("frontend dependency differs from lock")
    need_files(root, ("frontend/node_modules/vite/bin/vite.js",))
    return "Node/npm available; direct frontend dependency versions match the lockfile."


def model(root: Path, alias: str, verify: bool) -> str:
    from pipelines.embeddings import MODELS, model_directory, verify_model

    spec = MODELS[alias]
    directory = model_directory(root / "models", spec)
    if verify:
        verify_model(directory, spec)
        return (
            "Pinned model identity and all snapshot file hashes verified; weights were not loaded."
        )
    from dataclasses import asdict

    manifest = json_file(directory / "snapshot.json")
    if manifest.get("status") != "complete" or manifest.get("model") != asdict(spec):
        raise ValueError("model identity differs")
    from pipelines.embeddings import REQUIRED_MODEL_FILES

    need_files(directory, tuple(REQUIRED_MODEL_FILES))
    return "Pinned snapshot metadata and required files present; hashes not checked. Use --verify."


def optional_model(root: Path, kind: str, verify: bool) -> str:
    from importlib import import_module

    module = import_module(
        "backend.app.services."
        + ("retrieval.reranker" if kind == "reranker" else "eligibility.semantic")
    )
    directory = root / "models" / module.MODEL_DIR
    if verify:
        module.validate_snapshot(directory)
        return "Pinned optional model snapshot hashes verified; no inference performed."
    manifest = json_file(directory / "snapshot.json")
    if (
        manifest.get("status") != "complete"
        or manifest.get("repository") != module.REPOSITORY
        or manifest.get("revision") != module.REVISION
    ):
        raise ValueError("optional model identity differs")
    need_files(directory, module.FILES)
    return "Pinned optional model metadata/files present; hashes not checked."


def settings(root: Path):
    from backend.app.core.config import Settings

    config = Settings(_env_file=(root / ".env", root / ".env.api.local"))
    from sqlalchemy.engine import make_url

    database = make_url(config.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"localhost", "127.0.0.1", "::1"}
        or database.query
    ):
        raise ValueError("unsupported database connection")
    loopback_url(config.qdrant_url)
    from pipelines.criteria.artifacts import local_id

    for name in (
        config.api_index_id,
        config.api_evidence_id,
        config.api_catalog_id,
        config.api_collection,
    ):
        local_id(name)
    return config


def app_artifacts(root: Path, config, verify: bool):
    from pipelines.embeddings import MODELS, file_hash, model_directory

    processed = Path(config.processed_data_dir)
    if not processed.is_absolute():
        processed = root / processed
    index, evidence = processed / config.api_index_id, processed / config.api_evidence_id
    need_files(index, ("manifest.json", "documents.jsonl", "vectors.npy"))
    need_files(evidence, ("manifest.json", "evidence.json"))
    if verify:
        from pipelines.indexing.qdrant import artifact_contract
        from pipelines.reranking_data import load_evidence

        contract, rows, _ = artifact_contract(index)
        if contract["snapshot_sha256"] != file_hash(
            model_directory(root / "models", MODELS["minilm"]) / "snapshot.json"
        ):
            raise ValueError("document/query model identity differs")
        load_evidence(evidence, rows, contract["artifact_sha256"])
        return f"Verified {len(rows)} retrieval rows, vectors and aligned source-evidence records."
    manifest = json_file(index / "manifest.json")
    source = json_file(evidence / "manifest.json")
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != "dense-index-v1"
        or not 1 <= manifest.get("documents", 0) <= 512
        or source.get("status") != "complete"
        or source.get("trials") != manifest["documents"]
        or source.get("version") != "reranking-field-evidence-v1"
        or source.get("artifact_sha256")
        != hashlib.sha256((index / "manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("incomplete or incompatible artifact")
    if manifest.get("encoder", {}).get("snapshot_sha256") != file_hash(
        model_directory(root / "models", MODELS["minilm"]) / "snapshot.json"
    ):
        raise ValueError("document/query model identity differs")
    return "Completed bounded index/source manifests and files present; hashes not checked."


def topics(root: Path, verify: bool):
    path = root / "data/raw/m1-20260831-500-v2/topics2022.xml"
    need_files(path.parent, (path.name,))
    if verify:
        from pipelines.connectors.synthetic_cases import load_cases

        if len(load_cases(path, topics=True)) != 50:
            raise ValueError("all official synthetic cases required")
        return "All 50 official synthetic cases validate."
    return "App's documented synthetic topic source is present; records not validated."


def benchmark_artifacts(root: Path, verify: bool):
    index = root / "data/processed/release-full-minilm-v2"
    rendered = root / "data/processed/trec-ct-2021-render-v1"
    from pipelines.release_index import FROZEN_DOCUMENT_COUNT, FROZEN_DOCUMENTS_SHA256

    if verify:
        from pipelines.release_index import source_contract, verify_index

        manifest = verify_index(index)
        source = source_contract(rendered)
    else:
        manifest = json_file(index / "manifest.json")
        source = manifest["source"]
        need_files(rendered, ("manifest.json", "documents.jsonl"))
        render_manifest = json_file(rendered / "manifest.json")
        if (
            render_manifest.get("status") != "complete"
            or render_manifest.get("documents") != FROZEN_DOCUMENT_COUNT
            or render_manifest["files"][0]["sha256"] != FROZEN_DOCUMENTS_SHA256
        ):
            raise ValueError("full frozen render required")
        if not manifest.get("chunks"):
            raise ValueError("missing shards")
        for chunk in manifest["chunks"]:
            folder = contained(index, chunk["directory"])
            need_files(folder, ("documents.jsonl", "vectors.npy"))
            need_files(index, (chunk["checkpoint"]["path"],))
    if (
        manifest.get("status") != "complete"
        or manifest.get("documents") != FROZEN_DOCUMENT_COUNT
        or source != manifest["source"]
        or source["documents_sha256"] != FROZEN_DOCUMENTS_SHA256
    ):
        raise ValueError("full frozen corpus required")
    # This workflow requires exact query/document runtime identity.
    encoder = manifest["encoder"]
    from dataclasses import asdict

    from pipelines.embeddings import MODELS, file_hash, model_directory

    if (
        encoder["model"] != asdict(MODELS["minilm"])
        or encoder["snapshot_sha256"]
        != file_hash(model_directory(root / "models", MODELS["minilm"]) / "snapshot.json")
        or encoder.get("normalization") != "l2"
        or encoder.get("dtype") != "float32"
        or encoder.get("prompt") != ""
    ):
        raise ValueError("document/query model identity differs")
    if (
        encoder["python"] != platform.python_version()
        or encoder["platform"] != platform.platform()
        or encoder["machine"] != platform.machine()
        or encoder["processor"] != platform.processor()
        or any(package_version(n) != v for n, v in encoder["versions"].items())
    ):
        raise ValueError("query runtime differs from document runtime")
    return (
        "All 375,580 trials and full source/shard hashes verified; runtime matches."
        if verify
        else "Full-corpus manifests present and runtime matches; use --verify for hashes."
    )


def benchmark_sources(root: Path, verify: bool):
    from pipelines.connectors.trec import (
        KNOWN_2022_LEGACY_HEADER_SHA256,
        load_qrels,
        load_topics,
    )
    from pipelines.embeddings import file_hash, verify_files

    topics_path = root / "data/raw/m1-20260831-500-v2/topics2022.xml"
    qrels_path = topics_path.with_name("qrels2022.txt")
    if (
        file_hash(topics_path) != KNOWN_2022_LEGACY_HEADER_SHA256
        or file_hash(qrels_path)
        != "e569a531489e03f7b1fab03fe169c8ea66f4a59e8180fa9858b1a6e4bdcb0c5c"
    ):
        raise ValueError("frozen topics/qrels differ")
    topics_rows = load_topics(topics_path.read_bytes())
    load_qrels(qrels_path.read_bytes(), {t["topic_id"] for t in topics_rows})
    snapshot = root / "data/raw/trec-ct-2021-20210427"
    manifest = json_file(snapshot / "manifest.json")
    archives = manifest["archives"]
    if (
        manifest.get("status") != "complete"
        or len(archives) != 5
        or len({a["name"] for a in archives}) != 5
    ):
        raise ValueError("five completed source archives required")
    need_files(snapshot, tuple(a["name"] for a in archives))
    if verify:
        records = [
            {"path": a["name"], "bytes": a["bytes"], "sha256": a["sha256"]} for a in archives
        ]
        verify_files(snapshot, records, {a["name"] for a in archives})
    return "Frozen 2022 cases/judgments verified; original source archives " + (
        "hash-verified." if verify else "present (archive hashes not checked)."
    )


def database_ready(config):
    from backend.app.repositories.postgres import PostgresStore, local_engine

    engine = local_engine(config.database_url)
    try:
        store = PostgresStore(engine, config.api_catalog_id)
        store.ready()
        catalog = store.catalog()
        if len(catalog["case_hashes"]) != 51 or len(catalog["trial_hashes"]) != 446:
            raise ValueError("unexpected catalog")
        return "PostgreSQL migration and checksummed catalog ready: 51 synthetic cases, 446 trials."
    finally:
        engine.dispose()


def qdrant_ready(config):
    from backend.app.repositories.postgres import PostgresStore, local_engine
    from backend.app.repositories.qdrant import QdrantRepository

    payload = json.loads(read_http(loopback_url(config.qdrant_url) + "/"))
    if payload.get("version") != "1.19.0":
        raise ValueError("unsupported Qdrant version")
    engine = local_engine(config.database_url)
    try:
        catalog = PostgresStore(engine, config.api_catalog_id).catalog()
        with QdrantRepository(config.qdrant_url, config.api_collection) as repo:
            repo.check_contract(catalog["contract"])
        return "Qdrant 1.19.0 and catalog retrieval contract agree."
    finally:
        engine.dispose()


def api_ready(config):
    packet = json.loads(read_http("http://127.0.0.1:8000/v1/ready"))
    if (
        packet.get("status") != "ready"
        or packet.get("qdrant") != "ready"
        or packet.get("postgres", {}).get("status") != "ready"
        or packet.get("catalog_id") != config.api_catalog_id
    ):
        raise ValueError("API dependencies not ready")
    return "API reports database/catalog/index readiness. Models remain lazy; inference not tested."


def frontend_ready():
    raw = read_http("http://127.0.0.1:5173/")
    if b'id="root"' not in raw or b"/src/main.tsx" not in raw:
        raise ValueError("unexpected workspace response")
    return "Local Vite workspace responds. Browser rendering not tested."


def collect(root: Path, profile="app", *, online=False, verify=False) -> dict:
    checks = Checks()
    checks.add(
        "repository",
        "Repository root",
        lambda: need_files(
            root,
            (
                "pyproject.toml",
                "requirements/ci.txt",
                "requirements/research.txt",
                "frontend/package-lock.json",
            ),
        ),
        "Run from the nested Git repository; see docs/setup.md.",
    )
    checks.add(
        "python",
        "Python runtime",
        python_runtime,
        "Install Python 3.12 and create a short virtual environment; see docs/setup.md.",
    )
    names = BASE + (RESEARCH if profile != "tests" else ())
    missing = [n for n in names if package_version(n) is None]
    checks.add(
        "python_packages",
        "Python dependencies",
        lambda: installed_packages(names),
        "Install with python -m pip install -r requirements/"
        + ("ci.txt" if profile == "tests" else "research.txt")
        + ("; missing: " + ", ".join(missing) if missing else "; repair this environment."),
    )
    checks.add(
        "fixtures",
        "Synthetic test fixtures",
        lambda: need_files(
            root,
            (
                "evaluation/data/fixtures/screening.json",
                "evaluation/data/fixtures/screening_coverage.json",
            ),
        ),
        "Restore the deliberately tiny public fixtures from the repository.",
    )
    if profile != "tests":
        checks.add(
            "minilm",
            "Pinned MiniLM model",
            lambda: model(root, "minilm", verify),
            "Prepare pinned MiniLM: python -m pipelines.dense prepare-model --model minilm. "
            "For damaged artifacts follow docs/setup.md; do not edit manifest hashes.",
        )
        checks.add(
            "reranker",
            "Pinned reranker",
            lambda: optional_model(root, "reranker", verify),
            "Run python -m pipelines.prepare_reranker for optional reranking. "
            "The fixed benchmark requires this model.",
            required=profile == "benchmark",
        )
        if profile == "app":
            checks.add(
                "nli",
                "Optional NLI advisories",
                lambda: optional_model(root, "nli", verify),
                "Run python -m pipelines.prepare_nli only if you want optional local advisories.",
                required=False,
            )
            checks.add(
                "frontend",
                "Frontend toolchain and lockfile",
                lambda: frontend(root),
                "Install Node 24.16+ and npm, then run npm --prefix frontend ci.",
            )
            config = None

            def configuration():
                nonlocal config
                config = settings(root)
                return "Loopback-only API configuration validates. Connection values are withheld."

            checks.add(
                "configuration",
                "Local service configuration",
                configuration,
                "Prepare local configuration using docs/local-research-api.md. "
                "Keep credentials out of frontend files.",
            )
            if config is not None:
                checks.add(
                    "app_artifacts",
                    "Bounded search index and source evidence",
                    lambda: app_artifacts(root, config, verify),
                    "Follow docs/setup.md#prepare-the-local-application for the bounded index "
                    "and source evidence. An empty database is insufficient.",
                )
            else:
                checks.skip(
                    "app_artifacts", "Bounded search artifacts", "Resolve configuration first."
                )
            checks.add(
                "topics",
                "Curated synthetic case source",
                lambda: topics(root, verify),
                "Acquire official synthetic topics following the app preparation in docs/setup.md.",
            )
            if online and config is not None:
                for identity, title, run, remedy in (
                    (
                        "postgres",
                        "Database migrations and catalog",
                        lambda: database_ready(config),
                        "Start the database, then migrate and seed after preparing artifacts. "
                        "See docs/setup.md.",
                    ),
                    (
                        "qdrant",
                        "Qdrant and retrieval contract",
                        lambda: qdrant_ready(config),
                        "Start Qdrant and follow the verified hybrid-index load in docs/setup.md.",
                    ),
                    (
                        "api",
                        "Research API readiness",
                        lambda: api_ready(config),
                        "Start scripts/api-local.ps1 -Action Start after data preparation. "
                        "For a running stale API, explicitly stop it first.",
                    ),
                    (
                        "workspace",
                        "Browser workspace server",
                        frontend_ready,
                        "Run scripts/frontend-local.ps1 -Action Start; then open http://127.0.0.1:5173.",
                    ),
                ):
                    checks.add(identity, title, run, remedy)
            else:
                checks.skip(
                    "services",
                    "Running application services",
                    "Not probed. Use --online after local services are started.",
                )
        else:
            checks.add(
                "benchmark_artifacts",
                "Full offline benchmark artifacts and runtime",
                lambda: benchmark_artifacts(root, verify),
                "Follow docs/research-release.md for full-corpus data and matching model runtime; "
                "the app's bounded index is insufficient.",
            )
            checks.add(
                "benchmark_sources",
                "Frozen benchmark cases, judgments and XML sources",
                lambda: benchmark_sources(root, verify),
                "Acquire and validate the frozen sources using docs/research-release.md.",
            )
    elif online:
        checks.skip(
            "services", "Application services", "Fixture-test setup needs no running services."
        )
    blocked = any(r["status"] == "fail" for r in checks.rows)
    return {
        "version": VERSION,
        "profile": profile,
        "status": "blocked" if blocked else "checks_passed",
        "online": online,
        "verify_files": verify,
        "checks": checks.rows,
        "next_steps": list(dict.fromkeys(r["next_step"] for r in checks.rows if r["next_step"])),
        "scope": (
            "Selected setup checks only. No installation, downloads, migrations, "
            "inference or service changes performed."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["tests", "app", "benchmark"], default="app")
    parser.add_argument(
        "--online",
        action="store_true",
        help="Read local database/HTTP readiness; never starts services",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Validate full local model/artifact hashes; no inference",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable report with no credentials or source text",
    )
    args = parser.parse_args()
    result = collect(
        Path(__file__).resolve().parents[1], args.profile, online=args.online, verify=args.verify
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Themis Trial setup: {result['profile']} - {result['status']}")
        for row in result["checks"]:
            print(f"[{row['status'].upper()}] {row['title']}: {row['detail']}")
        if result["next_steps"]:
            print("\nNext steps:")
            for i, step in enumerate(result["next_steps"], 1):
                print(f"{i}. {step}")
        print("\n" + result["scope"])
    raise SystemExit(1 if result["status"] == "blocked" else 0)


if __name__ == "__main__":
    main()
