"""Experimental relevance-head adaptation; the original BERT backbone stays frozen."""

import json
import platform
from pathlib import Path

import numpy as np

from backend.app.services.retrieval.reranker import LocalReranker
from pipelines.embeddings import file_hash, verify_files

VERSION = "domain-relevance-head-v1"
DEFAULT_MODEL = "domain-hard-reranker-v1"
FEATURE_DIMENSION = 384
TRAINING = {
    "seed": 0,
    "epochs": 20,
    "learning_rate": 0.001,
    "delta_l2": 0.01,
    "checkpoints": [0, 5, 10, 15, 20],
    "objective": "query_balanced_pairwise_softplus_plus_delta_l2",
    "trainable": "384_classifier_weights_only_bias_and_bert_frozen",
    "checkpoint_selection": "dev_ndcg_at_10_then_earliest_epoch",
    "negatives": "external_grade_zero_only",
    "positives": "external_grades_one_and_two_equal_relevance_target",
    "default_promotion": False,
}


def code_identity():
    root = Path(__file__).resolve().parents[4]
    names = (
        "backend/app/services/retrieval/domain_reranker.py",
        "backend/app/services/retrieval/reranker.py",
        "pipelines/hard_negatives.py",
        "pipelines/train_domain_reranker.py",
    )
    return {name: file_hash(root / name) for name in names}


def runtime_identity():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


class FeatureReranker(LocalReranker):
    def __init__(self, root=Path("models")):
        super().__init__(root)
        import torch

        torch.use_deterministic_algorithms(True)
        layer = self.model.classifier
        if (
            not isinstance(layer, torch.nn.Linear)
            or tuple(layer.weight.shape) != (1, FEATURE_DIMENSION)
            or tuple(layer.bias.shape) != (1,)
        ):
            raise ValueError("a single pinned 384-dimensional linear relevance head is required")
        self.base_weight = layer.weight.detach().cpu().numpy()[0].copy()
        self.base_bias = float(layer.bias.detach().cpu()[0])
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def features(self, case, documents):
        captured = []

        def capture(_module, args):
            captured.append(args[0].detach().cpu().numpy().copy())

        hook = self.model.classifier.register_forward_pre_hook(capture)
        try:
            evidence = super().score(case, documents)
        finally:
            hook.remove()
        features = np.concatenate(captured).astype(np.float32)
        baseline = np.array([r["score"] for r in evidence], dtype=np.float32)
        if (
            features.shape != (len(documents), FEATURE_DIMENSION)
            or not np.isfinite(features).all()
            or not np.allclose(
                features @ self.base_weight + self.base_bias, baseline, atol=1e-5, rtol=0
            )
        ):
            raise ValueError("captured features do not reproduce the original relevance logits")
        return features, evidence


def validate_adapter(root, *, base_metadata=None, source_artifact_sha256=None):
    manifest = json.loads((root / "manifest.json").read_bytes())
    if (
        manifest.get("version") != VERSION
        or manifest.get("status") != "complete"
        or manifest.get("training") != TRAINING
        or manifest.get("code_identity") != code_identity()
        or manifest.get("runtime") != runtime_identity()
        or manifest.get("promoted") is not False
    ):
        raise ValueError("domain adapter configuration/code/runtime differs")
    verify_files(root, manifest["files"], {"head.json", "training.json"})
    if base_metadata is not None and manifest["base_model"] != base_metadata:
        raise ValueError("adapter differs from original pinned cross encoder")
    if (
        source_artifact_sha256 is not None
        and manifest["source_artifact_sha256"] != source_artifact_sha256
    ):
        raise ValueError("adapter training corpus differs from active index")
    head = json.loads((root / "head.json").read_bytes())
    weight = np.asarray(head["weight"], dtype=np.float32)
    if (
        weight.shape != (FEATURE_DIMENSION,)
        or not np.isfinite(weight).all()
        or not np.isfinite(head["bias"])
        or head["selected_epoch"] not in TRAINING["checkpoints"]
        or head.get("sampler") != "hard"
        or head.get("feature_contract") != "pinned_classifier_input_eval_v1"
    ):
        raise ValueError("invalid adapted relevance head")
    return manifest, head


class DomainReranker(FeatureReranker):
    def __init__(self, adapter_root=Path("models") / DEFAULT_MODEL, *, source_artifact_sha256=None):
        # Reject incomplete artifacts before loading model weights.
        manifest, head = validate_adapter(
            adapter_root, source_artifact_sha256=source_artifact_sha256
        )
        super().__init__()
        validate_adapter(
            adapter_root, base_metadata=self.metadata, source_artifact_sha256=source_artifact_sha256
        )
        self.adapter_root, self.adapter_manifest = (
            adapter_root,
            file_hash(adapter_root / "manifest.json"),
        )
        self.weight = np.asarray(head["weight"], dtype=np.float32)
        if head["bias"] != self.base_bias:
            raise ValueError("pairwise loss cannot identify bias; original bias must remain frozen")
        self.exposure = manifest["case_partitions"]
        self.metadata = {
            **self.metadata,
            "variant": "domain_hard",
            "adaptation": TRAINING["trainable"],
            "adapter_manifest_sha256": self.adapter_manifest,
            "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
            "selected_epoch": head["selected_epoch"],
            "retrospective_split_only": True,
            "promoted": False,
        }

    def score(self, case, documents):
        validate_adapter(self.adapter_root)
        if file_hash(self.adapter_root / "manifest.json") != self.adapter_manifest:
            raise ValueError("adapter changed after loading")
        features, baseline = self.features(case, documents)
        values = features @ self.weight + self.base_bias
        if not np.isfinite(values).all():
            raise ValueError("nonfinite adapted score")
        return [
            {
                **row,
                "score": float(value),
                "base_score": row["score"],
                "variant": "domain_hard",
                "adapter_manifest_sha256": self.adapter_manifest,
                "case_exposure": self.exposure.get(case.case_id, "outside_recorded_study"),
                "promoted": False,
            }
            for row, value in zip(baseline, values, strict=True)
        ]
