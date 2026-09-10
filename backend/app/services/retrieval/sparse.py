"""Versioned Lucene BM25 factorization for Qdrant sparse dot products."""

import hashlib
import json
import math
from collections import Counter

import bm25s
import numpy as np

SPARSE_NAME = "lexical_sparse"
SPARSE_CONFIG = {SPARSE_NAME: {"index": {"on_disk": False}}}
PARAMETERS = {
    "version": "bm25-sparse-v1",
    "method": "lucene",
    "k1": 1.2,
    "b": 0.75,
    "token_pattern": r"(?u)\b\w\w+\b",
    "lower": True,
    "stopwords": "english",
    "stemmer": None,
    "query_tf": "raw_count",
    "dtype": "float32",
    "representation": "title_conditions",
    "server_idf_modifier": None,
}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_sparse_config(info: dict) -> None:
    settings = info["config"]["params"].get("sparse_vectors", {}).get(SPARSE_NAME)
    if (
        settings is None
        or settings.get("modifier") is not None
        or settings.get("index", {}).get("on_disk") is not False
    ):
        raise ValueError("sparse vector configuration mismatch")


def tokenize(texts: list[str]) -> list[list[str]]:
    if any(not isinstance(t, str) for t in texts):
        raise ValueError("lexical inputs must be strings")
    return bm25s.tokenize(
        texts,
        lower=True,
        token_pattern=PARAMETERS["token_pattern"],
        stopwords="english",
        return_ids=False,
        show_progress=False,
    )


class SparseBM25:
    """Derived entirely from a frozen, ordered corpus; never fit on query text or qrels."""

    def __init__(self, texts: list[str]):
        if not 1 <= len(texts) <= 512:
            raise ValueError("sparse diagnostic requires 1..512 documents")
        self.tokens = tokenize(texts)
        df = Counter(term for tokens in self.tokens for term in set(tokens))
        if not df:
            raise ValueError("corpus has no lexical terms")
        self.vocabulary = {term: i for i, term in enumerate(sorted(df))}
        self.idf = {
            term: math.log1p((len(texts) - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }
        lengths = [len(tokens) for tokens in self.tokens]
        average = sum(lengths) / len(lengths)
        self.manifest = {
            **PARAMETERS,
            "bm25s_version": bm25s.__version__,
            "documents": len(texts),
            "vocabulary_size": len(df),
            "average_document_length": average,
            "vocabulary_sha256": digest(self.vocabulary),
            "document_frequencies_sha256": digest(dict(df)),
            "document_lengths_sha256": digest(lengths),
        }
        self.document_vectors = []
        for tokens in self.tokens:
            counts = Counter(tokens)
            terms = sorted(counts, key=self.vocabulary.__getitem__)
            denominator = PARAMETERS["k1"] * (
                1 - PARAMETERS["b"] + PARAMETERS["b"] * len(tokens) / average
            )
            self.document_vectors.append(
                {
                    "indices": [self.vocabulary[t] for t in terms],
                    "values": [
                        float(np.float32(counts[t] / (counts[t] + denominator))) for t in terms
                    ],
                }
            )

    def query(self, text: str) -> tuple[dict, dict]:
        tokens = tokenize([text])[0]
        counts = Counter(tokens)
        terms = sorted((t for t in counts if t in self.vocabulary), key=self.vocabulary.__getitem__)
        vector = {
            "indices": [self.vocabulary[t] for t in terms],
            "values": [float(np.float32(self.idf[t] * counts[t])) for t in terms],
        }
        audit = {
            "tokens": len(tokens),
            "known_terms": len(terms),
            "unknown_terms": sorted(set(counts) - self.vocabulary.keys()),
            "empty_lexical_query": not terms,
        }
        return vector, audit
