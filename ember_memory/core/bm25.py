"""Lightweight BM25 keyword scoring for hybrid retrieval.

Used alongside vector similarity via Reciprocal Rank Fusion (RRF).
No external dependencies -- pure Python.
"""

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer, lowercased."""
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25:
    """BM25 scorer for a set of documents."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = 0
        self.avg_dl = 0.0
        self.doc_freqs: dict[str, int] = {}
        self.doc_lens: list[int] = []
        self.doc_term_freqs: list[dict[str, int]] = []

    def index(self, documents: list[str]) -> None:
        """Index a batch of documents for BM25 scoring."""
        self.doc_count = len(documents)
        self.doc_lens = []
        self.doc_term_freqs = []
        self.doc_freqs = {}

        for doc in documents:
            tokens = tokenize(doc)
            self.doc_lens.append(len(tokens))
            tf = Counter(tokens)
            self.doc_term_freqs.append(dict(tf))
            for term in set(tokens):
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

        self.avg_dl = sum(self.doc_lens) / max(self.doc_count, 1)

    def score(self, query: str, doc_index: int) -> float:
        """Score a single document against a query."""
        query_tokens = tokenize(query)
        doc_tf = self.doc_term_freqs[doc_index]
        doc_len = self.doc_lens[doc_index]

        score = 0.0
        for term in query_tokens:
            if term not in doc_tf:
                continue
            tf = doc_tf[term]
            df = self.doc_freqs.get(term, 0)
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * doc_len / max(self.avg_dl, 1)
            )
            score += idf * numerator / denominator

        return score

    def score_all(self, query: str) -> list[float]:
        """Score all indexed documents against a query."""
        return [self.score(query, i) for i in range(self.doc_count)]


def reciprocal_rank_fusion(
    rankings: list[list[tuple[int, float]]],
    k: int = 60,
) -> list[tuple[int, float]]:
    """Fuse multiple rankings via RRF.

    Each ranking is a list of (doc_index, score) sorted by score descending.
    Returns fused ranking as (doc_index, rrf_score) sorted descending.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, (doc_idx, _score) in enumerate(ranking):
            scores[doc_idx] = scores.get(doc_idx, 0.0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
