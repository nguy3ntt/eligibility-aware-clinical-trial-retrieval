"""Local, pinned NLI advisories. They never override deterministic screening."""

import json
from importlib.metadata import version
from pathlib import Path

from backend.app.schemas.patient import SyntheticCase
from pipelines.criteria.artifacts import file_hash

REPOSITORY = "cross-encoder/nli-deberta-v3-small"
REVISION = "fa2804872c3b4bd748f38c0185cc85775361e735"
MODEL_DIR = "nli-deberta-" + REVISION[:12]
FILES = (
    "README.md",
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "spm.model",
)
LABELS = ("contradiction", "entailment", "neutral")
MAX_TOKENS = 512
THRESHOLD = 0.95
VERSION = "nli-advisory-v1"


def validate_snapshot(root):
    manifest = json.loads((root / "snapshot.json").read_bytes())
    if (
        manifest.get("repository") != REPOSITORY
        or manifest.get("revision") != REVISION
        or manifest.get("status") != "complete"
        or manifest.get("files") != {name: file_hash(root / name) for name in FILES}
    ):
        raise ValueError("NLI model snapshot is incomplete or incompatible")
    return manifest


def probabilities(logits, temperature=1.0):
    import numpy as np

    values = np.asarray(logits, dtype=np.float64)
    if values.shape != (3,) or not np.isfinite(values).all() or not 0.05 <= temperature <= 20:
        raise ValueError("NLI logits/temperature invalid")
    weights = np.exp((values - values.max()) / temperature)
    return (weights / weights.sum()).tolist()


def proposal(probs, section):
    if (
        len(probs) != 3
        or any(not 0 <= p <= 1 for p in probs)
        or abs(sum(probs) - 1) > 1e-6
        or section not in {"inclusion", "exclusion"}
    ):
        raise ValueError("invalid NLI probabilities/section")
    index = max(range(3), key=probs.__getitem__)
    if index == 2 or probs[index] < THRESHOLD:
        return "unknown"
    truth = index == 1
    return "satisfied" if truth == (section == "inclusion") else "violated"


class LocalNLI:
    def __init__(self, root=Path("models")):
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
                directory,
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
            )
            .to("cpu")
            .eval()
        )
        if self.model.config.num_labels != 3 or self.model.config.model_type != "deberta-v2":
            raise ValueError("NLI architecture/label contract mismatch")
        if self.model.config.id2label != {0: "contradiction", 1: "entailment", 2: "neutral"}:
            raise ValueError("NLI label order mismatch")
        self.metadata = {
            "version": VERSION,
            "repository": REPOSITORY,
            "revision": REVISION,
            "snapshot_sha256": file_hash(directory / "snapshot.json"),
            "labels": list(LABELS),
            "device": "cpu",
            "threads": 4,
            "seed": 0,
            "max_tokens": MAX_TOKENS,
            "truncation": "reject_pair",
            "threshold": THRESHOLD,
            "temperature": 1.0,
            "calibration": "raw_softmax_not_a_clinical_probability",
            "template": "full-synthetic-narrative__verbatim-criterion-v1",
            "versions": {name: version(name) for name in ("transformers", "torch", "numpy")},
            "promotion": "advisory_only_requires_independent_validation",
        }

    def score(self, case, hypothesis):
        import torch

        case = SyntheticCase.model_validate(case.model_dump())
        if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > 100000:
            raise ValueError("invalid criterion hypothesis")
        tokens = self.tokenizer(case.text, hypothesis, truncation=False, return_tensors="pt")
        count = int(tokens["input_ids"].shape[1])
        if count > MAX_TOKENS:
            return {"status": "abstained", "reason": "pair_exceeds_token_limit", "tokens": count}
        with torch.inference_mode():
            logits = self.model(**tokens).logits[0].tolist()
        return {
            "status": "scored",
            "tokens": count,
            "logits": logits,
            "probabilities": dict(zip(LABELS, probabilities(logits), strict=True)),
        }


def advise(assessment, model):
    advisories = []
    for decision, criterion in zip(assessment.criteria, assessment.parsed.criteria, strict=True):
        record = {
            "criterion_id": criterion.criterion_id,
            "method": "learned_nli",
            "promoted": False,
            "patient_evidence": assessment.profile.case.text,
            "criterion_evidence": criterion.evidence.model_dump(),
            "patient_fact_ids": [f.fact_id for f in assessment.profile.facts],
            "proposed_outcome": "unknown",
        }
        if decision.outcome != "unknown":
            record.update(status="not_run", reason="deterministic_outcome_retained")
        elif decision.reason in {
            "unknown_section_or_preamble",
            "shared_or_nested_context_requires_review",
        }:
            record.update(status="abstained", reason="unsupported_criterion_context")
        else:
            record.update(model.score(assessment.profile.case, criterion.evidence.text))
            if record["status"] == "scored":
                record["proposed_outcome"] = proposal(
                    [record["probabilities"][label] for label in LABELS],
                    criterion.section,
                )
        advisories.append(record)
    return {
        "model": model.metadata,
        "advisories": advisories,
        "screening_status_unchanged": assessment.status,
        "notice": "NLI probabilities describe text relations, not clinical eligibility.",
    }
