import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from pipelines.connectors.snapshots import write_json
from pipelines.embeddings import EncodedBatch, ModelSpec, file_record
from pipelines.release_index import build_index, read_chunk, verify_index
from pipelines.render_trials import REPRESENTATIONS, VERSION, render_trial


class FixtureEncoder:
    spec = ModelSpec("fixture", "invented", "pinned", 2, 8)
    metadata = {"model": "invented", "revision": "pinned"}

    def __init__(self, fail_after=None):
        self.calls = 0
        self.fail_after = fail_after

    def encode(self, texts):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("invented interruption")
        return EncodedBatch(
            np.tile(np.array([[0.6, 0.8]], dtype=np.float32), (len(texts), 1)), [10] * len(texts)
        )


def rendered(root, count=3):
    root.mkdir()
    with (root / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for i in range(count):
            element = ET.fromstring(
                f"<clinical_study><id_info><nct_id>NCT90000{i:03d}</nct_id></id_info>"
                f"<brief_title>Invented study {i}</brief_title></clinical_study>"
            )
            element.find("brief_title").text += "x" * (count - i) * 20
            row = render_trial(
                element,
                {
                    "archive": "invented.zip",
                    "archive_sha256": "a" * 64,
                    "member": f"{i}.xml",
                    "crc32": i,
                },
            )
            handle.write(json.dumps(row) + "\n")
    write_json(
        root / "manifest.json",
        {
            "status": "complete",
            "renderer_version": VERSION,
            "representations": {k: list(v) for k, v in REPRESENTATIONS.items()},
            "documents": count,
            "files": [file_record(root / "documents.jsonl", root)],
        },
    )
    return root


def test_full_index_preserves_every_row_and_checks_vectors(tmp_path):
    source, output = rendered(tmp_path / "source"), tmp_path / "output"
    result = build_index(source, output, FixtureEncoder(), chunk_size=2, batch_size=2)
    assert result["documents"] == 3 and result["truncated"] == 3
    assert len(result["chunks"]) == 2
    assert verify_index(output) == result
    with (output / result["chunks"][0]["directory"] / "vectors.npy").open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(ValueError, match="checksum"):
        verify_index(output)


def test_resume_skips_only_committed_verified_chunks(tmp_path):
    source, output = rendered(tmp_path / "source"), tmp_path / "output"
    with pytest.raises(RuntimeError, match="interruption"):
        build_index(source, output, FixtureEncoder(fail_after=1), chunk_size=2, batch_size=2)
    assert not (output / "manifest.json").exists()
    encoder = FixtureEncoder()
    result = build_index(source, output, encoder, chunk_size=2, batch_size=2, resume=True)
    assert result["documents"] == 3 and encoder.calls == 1
    with pytest.raises(ValueError, match="identical"):
        build_index(source, output, encoder, chunk_size=1, batch_size=2, resume=True)


def test_incomplete_or_changed_source_is_rejected(tmp_path):
    source = rendered(tmp_path / "source")
    with (source / "documents.jsonl").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="checksum"):
        build_index(source, tmp_path / "output", FixtureEncoder())
    assert not (tmp_path / "output").exists()


def test_length_buckets_restore_exact_document_and_token_alignment(tmp_path):
    class LengthEncoder(FixtureEncoder):
        def encode(self, texts):
            vectors = np.array([[len(text), 1] for text in texts], dtype=np.float32)
            vectors /= np.linalg.norm(vectors, axis=1)[:, None]
            return EncodedBatch(vectors, [len(text) for text in texts])

    root = tmp_path / "output"
    result = build_index(rendered(tmp_path / "source"), root, LengthEncoder(), batch_size=2)
    chunk = result["chunks"][0]
    rows, vectors = read_chunk(root / chunk["directory"], chunk)
    assert [row["trial_id"] for row in rows] == ["NCT90000000", "NCT90000001", "NCT90000002"]
    for row, vector in zip(rows, vectors, strict=True):
        assert row["token_count"] == len(row["text"])
        assert float(vector[0] / vector[1]) == pytest.approx(len(row["text"]))
