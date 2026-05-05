"""
Tests for ember_memory.core.embeddings.openai_provider — OpenAIProvider.

All network calls are mocked so no real API key or internet access is needed.
"""

import pytest
from unittest.mock import MagicMock, patch

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory.core.embeddings.openai_provider import OpenAIProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_KEY = "test-openai-key"
SMALL_MODEL = "text-embedding-3-small"
LARGE_MODEL = "text-embedding-3-large"

FAKE_VECTOR = [0.1] * 1536
FAKE_VECTOR_LARGE = [0.2] * 3072


def _make_response(embeddings: list[list[float]]) -> MagicMock:
    """Build a mock requests.Response whose .json() returns valid OAI format."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": [
            {"embedding": vec, "index": i}
            for i, vec in enumerate(embeddings)
        ]
    }
    return mock_resp


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------

class TestImplementsInterface:
    def test_implements_interface(self):
        """OpenAIProvider must be a concrete subclass of EmbeddingProvider."""
        provider = OpenAIProvider(api_key=FAKE_KEY)
        assert isinstance(provider, EmbeddingProvider)


# ---------------------------------------------------------------------------
# Dimension checks
# ---------------------------------------------------------------------------

class TestDimension:
    def test_dimension_small(self):
        """text-embedding-3-small should report 1536 dimensions."""
        provider = OpenAIProvider(api_key=FAKE_KEY, model=SMALL_MODEL)
        assert provider.dimension() == 1536

    def test_dimension_large(self):
        """text-embedding-3-large should report 3072 dimensions."""
        provider = OpenAIProvider(api_key=FAKE_KEY, model=LARGE_MODEL)
        assert provider.dimension() == 3072


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------

class TestEmbed:
    def test_embed_returns_vector(self):
        """embed() should return the embedding list from the API response."""
        provider = OpenAIProvider(api_key=FAKE_KEY, model=SMALL_MODEL)
        mock_resp = _make_response([FAKE_VECTOR])

        with patch("ember_memory.core.embeddings.openai_provider.requests.post", return_value=mock_resp):
            result = provider.embed("hello world")

        assert result == FAKE_VECTOR
        assert len(result) == 1536


# ---------------------------------------------------------------------------
# embed_batch()
# ---------------------------------------------------------------------------

class TestEmbedBatch:
    def test_embed_batch_returns_sorted(self):
        """embed_batch() should return embeddings in input order, sorted by index."""
        provider = OpenAIProvider(api_key=FAKE_KEY, model=SMALL_MODEL)

        vec_a = [0.1] * 1536
        vec_b = [0.9] * 1536

        # Return the items deliberately out of order to test sorting
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": [
                {"embedding": vec_b, "index": 1},
                {"embedding": vec_a, "index": 0},
            ]
        }

        with patch("ember_memory.core.embeddings.openai_provider.requests.post", return_value=mock_resp):
            result = provider.embed_batch(["first", "second"])

        assert result == [vec_a, vec_b], "Batch results must be sorted by index"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestRequiresApiKey:
    def test_requires_api_key(self):
        """Passing an empty string as api_key must raise ValueError."""
        with pytest.raises(ValueError, match="OpenAI API key is required"):
            OpenAIProvider(api_key="")


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_true(self):
        """health_check() returns True when the API call succeeds."""
        provider = OpenAIProvider(api_key=FAKE_KEY)
        mock_resp = _make_response([[0.0] * 1536])

        with patch("ember_memory.core.embeddings.openai_provider.requests.post", return_value=mock_resp):
            assert provider.health_check() is True

    def test_health_check_false(self):
        """health_check() returns False when the API call raises an exception."""
        provider = OpenAIProvider(api_key=FAKE_KEY)

        with patch(
            "ember_memory.core.embeddings.openai_provider.requests.post",
            side_effect=Exception("network error"),
        ):
            assert provider.health_check() is False
