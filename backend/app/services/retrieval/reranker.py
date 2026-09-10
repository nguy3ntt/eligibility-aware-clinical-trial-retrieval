"""Pinned local cross-encoder relevance scoring, independent of eligibility."""

import json
import math
from importlib.metadata import version
from pathlib import Path

from backend.app.schemas.patient import SyntheticCase, text_hash
from pipelines.criteria.artifacts import file_hash

REPOSITORY = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
MODEL_DIR = "reranker-minilm-" + REVISION[:12]
FILES = (
    "README.md",
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
)
VERSION = "bounded-cross-encoder-v1"
MAX_CANDIDATES = 50
MAX_TOKENS = 512
QUERY_TOKENS = 192
BATCH_SIZE = 8


def validate_snapshot(root: Path) -> dict:
    manifest = json.loads((root / "snapshot.json").read_bytes())
    if (
        manifest.get("status") != "complete"
        or manifest.get("repository") != REPOSITORY
        or manifest.get("revision") != REVISION
        or manifest.get("files") != {name: file_hash(root / name) for name in FILES}
    ):
        raise ValueError("reranker snapshot is incomplete or incompatible")
    return manifest


def reorder(candidates: list[dict], scores: list[dict]) -> list[dict]:
    """Replace only prefix order; never add unlike scores or discard the tail."""
    ids = [c["trial_id"] for c in candidates]
    if (
        len(ids) != len(set(ids))
        or len(ids) > 100
        or not 1 <= len(scores) <= min(MAX_CANDIDATES, len(ids))
    ):
        raise ValueError("unique candidates and a bounded nonempty scored prefix required")
    if any(not math.isfinite(c["score"]) for c in candidates):
        raise ValueError("candidate scores must be finite")
    if any(not math.isfinite(s["score"]) for s in scores):
        raise ValueError("reranker returned a nonfinite score")
    prefix = [
        {**c, "original_rank": i + 1, "reranker": score}
        for i, (c, score) in enumerate(zip(candidates[: len(scores)], scores, strict=True))
    ]
    prefix.sort(key=lambda c: (-c["reranker"]["score"], c["trial_id"]))
    tail = [
        {**c, "original_rank": i + 1, "reranker": None}
        for i, c in enumerate(candidates[len(scores) :], start=len(scores))
    ]
    return [{**c, "rank": i + 1} for i, c in enumerate(prefix + tail)]


class LocalReranker:
    def __init__(self, root: Path = Path("models")):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        directory = root / MODEL_DIR
        validate_snapshot(directory)
        torch.set_num_threads(4)
        torch.manual_seed(0)
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = (
            AutoModelForSequenceClassification.from_pretrained(
                directory, local_files_only=True, trust_remote_code=False, use_safetensors=True
            )
            .to("cpu")
            .eval()
        )
        if self.model.config.num_labels != 1 or self.model.config.model_type != "bert":
            raise ValueError("reranker architecture contract mismatch")
        if self.tokenizer.num_special_tokens_to_add(pair=True) != 3 or any(
            token is None for token in (self.tokenizer.cls_token_id, self.tokenizer.sep_token_id)
        ):
            raise ValueError("reranker BERT pair template mismatch")
        self.metadata = {
            "version": VERSION,
            "repository": REPOSITORY,
            "revision": REVISION,
            "snapshot_sha256": file_hash(directory / "snapshot.json"),
            "template": "synthetic-narrative__normalized-summary-prefix-v1",
            "max_tokens": MAX_TOKENS,
            "query_token_cap": QUERY_TOKENS,
            "batch_size": BATCH_SIZE,
            "max_candidates": MAX_CANDIDATES,
            "device": "cpu",
            "threads": 4,
            "seed": 0,
            "score": "raw_relevance_logit_not_eligibility_probability",
            "truncation": "explicit_token_prefix_with_character_spans",
            "versions": {n: version(n) for n in ("torch", "transformers", "numpy")},
        }

    def _prefix(self, text: str, cap: int) -> tuple[list[int], dict]:
        # Count full inputs without misleading length warnings; only the capped pair is scored.
        tokens = self.tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True, verbose=False
        )
        ids = tokens["input_ids"]
        if not ids:
            raise ValueError("reranking text has no usable tokens")
        used = min(cap, len(ids))
        start = tokens["offset_mapping"][0][0]
        end = tokens["offset_mapping"][used - 1][1]
        return ids[:used], {
            "source_sha256": text_hash(text),
            "total_tokens": len(ids),
            "used_tokens": used,
            "truncated": used < len(ids),
            "start": start,
            "end": end,
            "text": text[start:end],
        }

    def score(self, case: SyntheticCase, documents: list[str]) -> list[dict]:
        import torch

        case = SyntheticCase.model_validate(case.model_dump())
        if not 1 <= len(documents) <= MAX_CANDIDATES or any(
            not isinstance(t, str) or not t.strip() or len(t) > 200000 for t in documents
        ):
            raise ValueError("reranking requires 1..50 bounded nonempty documents")
        query, query_evidence = self._prefix(case.text, QUERY_TOKENS)
        capacity = MAX_TOKENS - len(query) - self.tokenizer.num_special_tokens_to_add(pair=True)
        inputs, evidence = [], []
        for text in documents:
            passage, passage_evidence = self._prefix(text, capacity)
            inputs.append(
                {
                    # Pinned BERT template, explicitly preserving token IDs after prefix selection.
                    "input_ids": [self.tokenizer.cls_token_id]
                    + query
                    + [self.tokenizer.sep_token_id]
                    + passage
                    + [self.tokenizer.sep_token_id],
                    "token_type_ids": [0] * (len(query) + 2) + [1] * (len(passage) + 1),
                }
            )
            evidence.append({"query": query_evidence, "document": passage_evidence})
        result = []
        for start in range(0, len(inputs), BATCH_SIZE):
            batch = self.tokenizer.pad(inputs[start : start + BATCH_SIZE], return_tensors="pt")
            with torch.inference_mode():
                values = self.model(**batch).logits[:, 0].tolist()
            for offset, value in enumerate(values):
                if not math.isfinite(value):
                    raise ValueError("reranker produced a nonfinite score")
                result.append(
                    {
                        "score": value,
                        "method": "learned_cross_encoder",
                        "input": evidence[start + offset],
                    }
                )
        return result
