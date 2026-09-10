"""Separate criterion-vector contract over the existing loopback Qdrant transport."""

import math

from backend.app.repositories.qdrant import QdrantRepository

DENSE = "criterion_dense"
SPARSE = "criterion_sparse"
INDEXES = {
    "criterion_id": "keyword",
    "trial_id": "keyword",
    "section": "keyword",
    "artifact_sha256": "keyword",
    "parser_sha256": "keyword",
    "ordinal": "integer",
}


class CriteriaRepository(QdrantRepository):
    def check_contract(self, contract: dict) -> None:
        config = self.info()["config"]
        if config.get("metadata", {}).get("retrieval_contract") != contract:
            raise ValueError("criterion collection belongs to a different artifact/parser/model")
        dense = config["params"]["vectors"].get(DENSE, {})
        sparse = config["params"].get("sparse_vectors", {}).get(SPARSE, {})
        if (
            dense.get("size") != contract["dimension"]
            or dense.get("distance") != "Cosine"
            or sparse.get("modifier") is not None
            or sparse.get("index", {}).get("on_disk") is not False
        ):
            raise ValueError("criterion vector configuration mismatch")

    def ensure_criteria(self, contract: dict) -> None:
        self.version()
        response = self.client.get(self.path)
        if response.status_code == 404:
            self.request(
                "PUT",
                self.path,
                {
                    "vectors": {DENSE: {"size": contract["dimension"], "distance": "Cosine"}},
                    "sparse_vectors": {SPARSE: {"index": {"on_disk": False}}},
                    "metadata": {"retrieval_contract": contract},
                },
            )
        else:
            response.raise_for_status()
        self.check_contract(contract)
        for key, kind in INDEXES.items():
            existing = self.info().get("payload_schema", {}).get(key)
            if existing and existing.get("data_type") != kind:
                raise ValueError("criterion payload index mismatch")
            if not existing:
                self.request(
                    "PUT", self.path + "/index?wait=true", {"field_name": key, "field_schema": kind}
                )

    def query_criteria(self, vector, contract, *, sparse=False, k=5):
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
            raise ValueError("top-k must be 1..100")
        if type(contract["documents"]) is not int or not 1 <= contract["documents"] <= 512:
            raise ValueError("criterion query requires a bounded 1..512 point contract")
        self.check_contract(contract)
        if not sparse and (
            len(vector) != contract["dimension"]
            or not all(math.isfinite(v) for v in vector)
            or abs(sum(v * v for v in vector) - 1) > 1e-4
        ):
            raise ValueError("criterion query vector must be finite and normalized")
        if sparse:
            indices, values = vector["indices"], vector["values"]
            if (
                len(indices) != len(values)
                or any(
                    type(i) is not int or not 0 <= i < contract["lexical"]["vocabulary_size"]
                    for i in indices
                )
                or indices != sorted(set(indices))
                or any(isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in values)
            ):
                raise ValueError("criterion sparse query is invalid")
            if not indices:
                return []
        body = {
            "query": vector,
            "using": SPARSE if sparse else DENSE,
            "params": {"exact": True},
            "limit": contract["documents"],
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "artifact_sha256", "match": {"value": contract["artifact_sha256"]}}
                ]
            },
        }
        points = self.request("POST", self.path + "/points/query", body)["points"]
        return sorted(points, key=lambda p: (-p["score"], p["payload"]["criterion_id"]))[:k]
