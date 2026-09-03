"""Pinned, local-only sentence encoders for synthetic-case retrieval experiments."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from pipelines.connectors.snapshots import write_json


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    repository: str
    revision: str
    dimension: int
    max_tokens: int
    license: str = "apache-2.0"


MODELS = {
    "minilm": ModelSpec(
        "minilm",
        "sentence-transformers/all-MiniLM-L6-v2",
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        384,
        256,
    ),
    "pubmedbert": ModelSpec(
        "pubmedbert",
        "NeuML/pubmedbert-base-embeddings",
        "b79526d6ef3645e0df4530322e266f24c829f5ef",
        768,
        512,
    ),
}
MODEL_FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "modules.json",
    "1_Pooling/config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.txt",
    "README.md",
)
REQUIRED_MODEL_FILES = set(MODEL_FILES) - {"added_tokens.json"}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_hash(path),
    }


def verify_files(root: Path, records: list[dict], required: set[str]) -> None:
    seen = set()
    for row in records:
        name = row["path"]
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or name in seen or not path.is_file():
            raise ValueError("invalid or duplicate artifact path")
        seen.add(name)
        if path.stat().st_size != row["bytes"] or file_hash(path) != row["sha256"]:
            raise ValueError(f"artifact checksum mismatch: {name}")
    if seen != required:
        raise ValueError("artifact file inventory mismatch")


def model_directory(root: Path, spec: ModelSpec) -> Path:
    # Keep Hugging Face's nested temporary paths below typical Windows limits.
    # The complete revision is still checked in snapshot.json before every load.
    return root / f"{spec.alias}-{spec.revision[:12]}"


def _verify_modules(root: Path) -> None:
    modules = json.loads((root / "modules.json").read_bytes())
    allowed = {
        ("sentence_transformers.models.Transformer", ""),
        ("sentence_transformers.models.Pooling", "1_Pooling"),
        ("sentence_transformers.models.Normalize", "2_Normalize"),
    }
    actual = [(module["type"], module["path"]) for module in modules]
    required = allowed - {("sentence_transformers.models.Normalize", "2_Normalize")}
    if not set(actual) >= required or not set(actual) <= allowed or len(set(actual)) != len(actual):
        raise ValueError("unsupported model module or path; remote code is forbidden")


def verify_model(root: Path, spec: ModelSpec) -> dict:
    manifest = json.loads((root / "snapshot.json").read_bytes())
    if manifest.get("status") != "complete" or manifest.get("model") != asdict(spec):
        raise ValueError("model snapshot is incomplete or differs from the pinned model")
    names = {entry["path"] for entry in manifest["files"]}
    if not names >= REQUIRED_MODEL_FILES or not names <= set(MODEL_FILES):
        raise ValueError("unexpected model snapshot file inventory")
    verify_files(root, manifest["files"], names)
    _verify_modules(root)
    return manifest


def prepare_model(spec: ModelSpec, root: Path) -> Path:
    """The only network step; download public configs and safetensors, never remote code."""
    from huggingface_hub import snapshot_download

    destination = model_directory(root, spec)
    if (destination / "snapshot.json").exists():
        verify_model(destination, spec)
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    download_path = str(destination.resolve())
    if os.name == "nt":
        download_path = (
            "\\\\?\\UNC\\" + download_path[2:]
            if download_path.startswith("\\\\")
            else "\\\\?\\" + download_path
        )
    snapshot_download(
        spec.repository,
        revision=spec.revision,
        local_dir=download_path,
        cache_dir=root / ".cache",
        allow_patterns=list(MODEL_FILES),
        token=False,
        max_workers=2,
    )
    files = [
        file_record(destination / name, destination)
        for name in MODEL_FILES
        if (destination / name).is_file()
    ]
    if not {row["path"] for row in files} >= REQUIRED_MODEL_FILES:
        raise ValueError("downloaded model is missing required files")
    _verify_modules(destination)
    write_json(
        destination / "snapshot.json",
        {
            "status": "complete",
            "model": asdict(spec),
            "files": files,
            "format": "safetensors",
            "trust_remote_code": False,
        },
    )
    verify_model(destination, spec)
    return destination


def validate_vectors(vectors: np.ndarray, rows: int, dimension: int) -> None:
    if vectors.dtype != np.float32 or vectors.shape != (rows, dimension):
        raise ValueError("embedding shape or dtype mismatch")
    if not np.isfinite(vectors).all():
        raise ValueError("embeddings contain non-finite values")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5, rtol=0):
        raise ValueError("embeddings must be nonzero L2-normalized vectors")


@dataclass
class EncodedBatch:
    vectors: np.ndarray
    token_counts: list[int]


class Encoder(Protocol):
    spec: ModelSpec
    metadata: dict

    def encode(self, texts: list[str]) -> EncodedBatch: ...


class LocalSentenceEncoder:
    """CPU float32 inference with no network fallback or hidden model prompts."""

    def __init__(self, spec: ModelSpec, model_root: Path, *, threads: int = 4):
        import torch
        from sentence_transformers import SentenceTransformer

        if not 1 <= threads <= 16:
            raise ValueError("CPU thread count must be 1..16")
        self.spec = spec
        snapshot = model_directory(model_root, spec)
        verify_model(snapshot, spec)
        torch.set_num_threads(threads)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        self.model = SentenceTransformer(
            str(snapshot.resolve()),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        dimension = getattr(self.model, "get_embedding_dimension", None)
        if dimension is None:
            dimension = self.model.get_sentence_embedding_dimension
        if dimension() != spec.dimension:
            raise ValueError("loaded model dimension differs from pinned specification")
        if self.model.max_seq_length != spec.max_tokens:
            raise ValueError("loaded model token limit differs from pinned specification")
        self.model.eval()
        self.metadata = {
            "model": asdict(spec),
            "snapshot_sha256": file_hash(snapshot / "snapshot.json"),
            "versions": {
                name: importlib.metadata.version(name)
                for name in (
                    "sentence-transformers",
                    "transformers",
                    "torch",
                    "numpy",
                    "huggingface-hub",
                    "safetensors",
                )
            },
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "device": "cpu",
            "threads": threads,
            "seed": 0,
            "dtype": "float32",
            "normalization": "l2",
            "prompt": "",
            "truncation": "right_at_model_token_limit",
            "trust_remote_code": False,
        }
        if self.model.tokenizer.truncation_side != "right":
            raise ValueError("only right-side truncation is supported")

    def encode(self, texts: list[str]) -> EncodedBatch:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("encoder requires nonempty text inputs")
        tokens = self.model.tokenizer(
            texts,
            add_special_tokens=True,
            truncation=False,
            padding=False,
            verbose=False,
        )["input_ids"]
        vectors = self.model.encode(
            texts,
            batch_size=len(texts),
            show_progress_bar=False,
            prompt="",
            convert_to_numpy=True,
            normalize_embeddings=True,
            precision="float32",
        )
        vectors = np.asarray(vectors, dtype=np.float32)
        validate_vectors(vectors, len(texts), self.spec.dimension)
        return EncodedBatch(vectors, [len(token_ids) for token_ids in tokens])
