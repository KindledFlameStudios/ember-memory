from unittest.mock import MagicMock

from ember_memory.core.bm25 import BM25, reciprocal_rank_fusion, tokenize
from ember_memory.core.search import retrieve


def test_tokenize():
    assert tokenize("Hello World!") == ["hello", "world"]
    assert tokenize("BM25-scoring") == ["bm25", "scoring"]


def test_bm25_exact_match_scores_higher():
    bm25 = BM25()
    bm25.index([
        "The cat sat on the mat",
        "Flik is a Flameborn character",
        "Python programming guide",
    ])
    scores = bm25.score_all("who is Flik")
    assert scores[1] > scores[0]
    assert scores[1] > scores[2]


def test_bm25_empty_query():
    bm25 = BM25()
    bm25.index(["some document"])
    assert bm25.score("", 0) == 0.0


def test_rrf_merges_rankings():
    r1 = [(0, 0.9), (1, 0.7), (2, 0.5)]
    r2 = [(2, 0.9), (0, 0.7), (1, 0.5)]
    fused = reciprocal_rank_fusion([r1, r2])
    indices = [idx for idx, _ in fused]
    assert 0 in indices[:2]


def test_retrieve_keyword_match_gets_rrf_boost():
    backend = MagicMock()
    backend.list_collections.return_value = [{"name": "notes", "count": 2}]
    backend.search.return_value = [
        {
            "id": "generic",
            "content": "A broad overview of the lore and cast.",
            "metadata": {},
            "similarity": 0.9,
        },
        {
            "id": "flik",
            "content": "Flik is a Flameborn character with a direct profile.",
            "metadata": {},
            "similarity": 0.72,
        },
    ]

    embedder = MagicMock()
    embedder.embed.return_value = [0.1, 0.1, 0.1, 0.1]

    results = retrieve(
        "who is Flik",
        ai_id="claude",
        backend=backend,
        embedder=embedder,
        similarity_threshold=0.35,
    )

    assert [result.id for result in results][:2] == ["flik", "generic"]
