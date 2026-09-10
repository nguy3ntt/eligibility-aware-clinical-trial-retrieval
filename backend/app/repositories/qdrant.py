"""Local Qdrant REST boundary with a versioned collection contract."""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

import httpx

VECTOR_NAME = "overview_dense"
# Less than one millisecond in days; absorb JSON float round trips at boundaries.
AGE_TOLERANCE_DAYS = 1e-8
PAYLOAD_INDEXES = {
    "trial_id": "keyword",
    "artifact_sha256": "keyword",
    "sex": "keyword",
    "minimum_age_days": "float",
    "maximum_age_days": "float",
}
HNSW_PROFILE = {"m": 16, "ef_construct": 100, "full_scan_threshold": 10, "max_indexing_threads": 1}
OPTIMIZER_PROFILE = {"indexing_threshold": 1, "default_segment_number": 1}


def query_body(vector, contract, *, k=5, demographics=None, exact=True, hnsw_ef=32) -> dict:
    """Validate and prepare a query outside a benchmark's timed HTTP boundary."""
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
        raise ValueError("top-k must be 1..100")
    if not isinstance(exact, bool):
        raise ValueError("exact must be boolean")
    if isinstance(hnsw_ef, bool) or not isinstance(hnsw_ef, int) or not 10 <= hnsw_ef <= 512:
        raise ValueError("hnsw_ef must be 10..512")
    if (
        len(vector) != contract["dimension"]
        or not all(math.isfinite(v) for v in vector)
        or abs(sum(v * v for v in vector) - 1) > 1e-4
    ):
        raise ValueError("query must be a finite normalized vector with matching dimensions")
    query_filter = compatibility_filter(demographics or {})
    query_filter["must"] = [
        {"key": "artifact_sha256", "match": {"value": contract["artifact_sha256"]}}
    ]
    return {
        "query": vector,
        "using": VECTOR_NAME,
        "limit": k,
        "params": {"exact": True} if exact else {"exact": False, "hnsw_ef": hnsw_ef},
        "filter": query_filter,
        "with_payload": True,
    }


def point_id(trial_id: str) -> str:
    if not re.fullmatch(r"NCT\d{8}", trial_id):
        raise ValueError("invalid NCT ID")
    return str(uuid5(NAMESPACE_URL, f"https://clinicaltrials.gov/study/{trial_id}"))


def compatibility_filter(demographics: dict) -> dict:
    """Exclude known contradictions; absent payload values match no exclusion."""
    exclusions = []
    age = demographics.get("age_days")
    if age is not None:
        if (
            isinstance(age, bool)
            or not isinstance(age, int | float)
            or not math.isfinite(age)
            or age < 0
        ):
            raise ValueError("age must be a finite nonnegative number")
        exclusions.extend(
            [
                {"key": "minimum_age_days", "range": {"gt": age + AGE_TOLERANCE_DAYS}},
                {"key": "maximum_age_days", "range": {"lt": age - AGE_TOLERANCE_DAYS}},
            ]
        )
    sex = demographics.get("sex")
    if sex in {"Male", "Female"}:
        exclusions.append({"key": "sex", "match": {"value": "female" if sex == "Male" else "male"}})
    elif sex is not None:
        raise ValueError("unsupported topic sex")
    return {"must_not": exclusions} if exclusions else {}


class QdrantRepository:
    """Loopback-only server access; injected HTTP transports support offline contract tests."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:6333",
        collection: str = "trials_v1",
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("this milestone supports loopback HTTP Qdrant only")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", collection):
            raise ValueError("invalid collection name")
        self.collection = collection
        self.path = f"/collections/{collection}"
        self.client = httpx.Client(
            base_url=url, timeout=30, trust_env=False, follow_redirects=False, transport=transport
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def request(self, method: str, path: str, body: dict | None = None):
        response = self.client.request(method, path, json=body)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok" or "result" not in data:
            raise ValueError("Qdrant did not acknowledge the operation")
        return data["result"]

    def version(self) -> str:
        response = self.client.get("/")
        response.raise_for_status()
        version = response.json()["version"]
        if version != "1.19.0":
            raise ValueError(f"expected Qdrant 1.19.0, received {version}")
        return version

    def info(self) -> dict:
        return self.request("GET", self.path)

    def require_absent(self) -> None:
        response = self.client.get(self.path)
        if response.status_code == 404:
            return
        response.raise_for_status()
        raise ValueError("target collection already exists; choose a new collection name")

    def configure_hnsw(self, contract: dict, *, timeout: float = 120) -> dict:
        if not math.isfinite(timeout) or not 0 <= timeout <= 300:
            raise ValueError("index wait timeout must be 0..300 seconds")
        self.version()
        self.check_contract(contract)
        if self.count() != contract["documents"]:
            raise ValueError("load and verify all points before configuring HNSW")
        self.request(
            "PATCH",
            self.path,
            {
                "hnsw_config": HNSW_PROFILE,
                "optimizers_config": OPTIMIZER_PROFILE,
            },
        )
        return self.wait_hnsw(contract, timeout=timeout)

    def hnsw_ready(self, contract: dict) -> dict:
        self.check_contract(contract)
        info = self.info()
        config = info["config"]
        if (
            any(config["hnsw_config"].get(k) != v for k, v in HNSW_PROFILE.items())
            or any(config["optimizer_config"].get(k) != v for k, v in OPTIMIZER_PROFILE.items())
            or config.get("quantization_config") is not None
            or config["params"]["vectors"][VECTOR_NAME].get("hnsw_config")
            or config["params"]["vectors"][VECTOR_NAME].get("quantization_config")
        ):
            raise ValueError("HNSW diagnostic configuration mismatch; run configure-ann")
        if info["optimizer_status"] != "ok":
            raise ValueError(f"Qdrant optimizer failed: {info['optimizer_status']}")
        if (
            info["status"] != "green"
            or info["indexed_vectors_count"] != contract["documents"]
            or self.count() != contract["documents"]
        ):
            raise ValueError("HNSW is not ready: all artifact vectors must be indexed")
        return info

    def wait_hnsw(self, contract: dict, *, timeout: float = 120) -> dict:
        if not math.isfinite(timeout) or not 0 <= timeout <= 300:
            raise ValueError("index wait timeout must be 0..300 seconds")
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.hnsw_ready(contract)
            except ValueError as exc:
                if "not ready" not in str(exc) or time.monotonic() >= deadline:
                    raise
            time.sleep(0.5)

    def collection_telemetry(self) -> dict:
        data = self.request("GET", "/telemetry?details_level=4")
        matches = [c for c in data["collections"]["collections"] if c["id"] == self.collection]
        if len(matches) != 1:
            raise ValueError("collection telemetry unavailable")
        return matches[0]

    def download_snapshot(self, destination: Path) -> dict:
        snapshot = self.request("POST", self.path + "/snapshots?wait=true")
        name = snapshot["name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.snapshot", name):
            raise ValueError("unsafe server snapshot filename")
        size = snapshot.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 512 * 1024**2:
            raise ValueError("snapshot exceeds the bounded 512 MiB download limit")
        received = 0
        with self.client.stream("GET", self.path + "/snapshots/" + name) as response:
            response.raise_for_status()
            with destination.open("xb") as output:
                for block in response.iter_bytes():
                    received += len(block)
                    if received > size:
                        raise ValueError("snapshot exceeds declared size")
                    output.write(block)
        if received != size:
            raise ValueError("snapshot download was incomplete")
        return snapshot

    def upload_snapshot(self, snapshot: Path, checksum: str) -> None:
        self.version()
        self.require_absent()
        with snapshot.open("rb") as source:
            response = self.client.post(
                self.path + "/snapshots/upload",
                params={"wait": "true", "priority": "snapshot", "checksum": checksum},
                files={"snapshot": ("collection.snapshot", source, "application/octet-stream")},
                timeout=120,
            )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok" or data.get("result") is not True:
            raise ValueError("snapshot recovery was not acknowledged")

    def ensure_collection(self, contract: dict, *, sparse_vectors: dict | None = None) -> None:
        self.version()
        response = self.client.get(self.path)
        if response.status_code == 404:
            self.request(
                "PUT",
                self.path,
                {
                    "vectors": {VECTOR_NAME: {"size": contract["dimension"], "distance": "Cosine"}},
                    "hnsw_config": {"m": 16, "ef_construct": 100},
                    "metadata": {"retrieval_contract": contract},
                    **({"sparse_vectors": sparse_vectors} if sparse_vectors is not None else {}),
                },
            )
        else:
            response.raise_for_status()
        self.check_contract(contract)
        if sparse_vectors is not None:
            stored = self.info()["config"]["params"].get("sparse_vectors", {})
            for name, expected in sparse_vectors.items():
                actual = stored.get(name)
                if (
                    actual is None
                    or actual.get("modifier") != expected.get("modifier")
                    or any(
                        actual.get("index", {}).get(k) != v
                        for k, v in expected.get("index", {}).items()
                    )
                ):
                    raise ValueError("sparse vector configuration mismatch")
        for key, schema in PAYLOAD_INDEXES.items():
            existing = self.info().get("payload_schema", {}).get(key)
            if existing and existing.get("data_type") != schema:
                raise ValueError(f"incompatible payload index: {key}")
            if not existing:
                self.request(
                    "PUT",
                    self.path + "/index?wait=true",
                    {"field_name": key, "field_schema": schema},
                )

    def check_contract(self, contract: dict) -> None:
        info = self.info()
        config = info["config"]
        if config.get("metadata", {}).get("retrieval_contract") != contract:
            raise ValueError(
                "collection belongs to a different artifact/model/template; use a new collection"
            )
        vectors = config["params"]["vectors"]
        if (
            VECTOR_NAME not in vectors
            or vectors[VECTOR_NAME]["size"] != contract["dimension"]
            or vectors[VECTOR_NAME]["distance"] != "Cosine"
        ):
            raise ValueError("collection vector configuration mismatch")

    def upsert(self, points: list[dict]) -> None:
        result = self.request("PUT", self.path + "/points?wait=true", {"points": points})
        if result.get("status") != "completed":
            raise ValueError("Qdrant write was not completed; retry the same artifact")

    def count(self) -> int:
        return self.request("POST", self.path + "/points/count", {"exact": True})["count"]

    def retrieve(self, ids: list[str]) -> list[dict]:
        return self.request(
            "POST", self.path + "/points", {"ids": ids, "with_payload": True, "with_vector": True}
        )

    def search(
        self,
        vector: list[float],
        contract: dict,
        *,
        k: int = 5,
        demographics: dict | None = None,
        exact: bool = True,
        hnsw_ef: int = 32,
    ) -> list[dict]:
        self.check_contract(contract)
        body = query_body(
            vector, contract, k=k, demographics=demographics, exact=exact, hnsw_ef=hnsw_ef
        )
        if not exact:
            self.hnsw_ready(contract)
        return self.query_points(body)

    def query_points(self, body: dict) -> list[dict]:
        """Execute an already prepared query; callers preflight before timing repeated calls."""
        result = self.request("POST", self.path + "/points/query", body)
        return sorted(result["points"], key=lambda p: (-p["score"], p["payload"]["trial_id"]))
