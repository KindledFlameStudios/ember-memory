"""
Tests for ember_memory.core.embeddings.google_provider — GoogleProvider.

Verifies:
- Implements the EmbeddingProvider interface
- Returns correct dimension (3072 for gemini-embedding-001)
- embed() correctly parses a single-embedding API response
- embed_batch() correctly parses a batch API response
- Empty API key raises ValueError at construction
- health_check() returns True on success, False on failure
"""

from unittest.mock import MagicMock, patch

import pytest

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory.core.embeddings.google_provider import GoogleProvider

_FAKE_KEY = "test-api-key-abc123"
_FAKE_VEC = [0.1, 0.2, 0.3, 0.4]


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------

class TestGoogleProviderInterface:
    def test_implements_interface(self):
        """GoogleProvider must be a concrete subclass of EmbeddingProvider."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        assert isinstance(provider, EmbeddingProvider)


# ---------------------------------------------------------------------------
# Configuration / dimension
# ---------------------------------------------------------------------------

class TestGoogleProviderDimension:
    def test_dimension_3072(self):
        """Default model (gemini-embedding-001) must report 3072 dimensions."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        assert provider.dimension() == 3072


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------

class TestGoogleProviderEmbed:
    def _make_response(self, values: list[float]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embedding": {"values": values}}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_embed_returns_vector(self):
        """embed() should return the values list from the API response."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        mock_resp = self._make_response(_FAKE_VEC)

        with patch("ember_memory.core.embeddings.google_provider.requests.post", return_value=mock_resp) as mock_post:
            result = provider.embed("hello world")

        assert result == _FAKE_VEC
        mock_post.assert_called_once()
        # Verify the API key was in the URL
        call_url = mock_post.call_args[0][0]
        assert _FAKE_KEY in call_url

    def test_embed_sends_correct_payload(self):
        """embed() must send the model and content in the request body."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        mock_resp = self._make_response(_FAKE_VEC)

        with patch("ember_memory.core.embeddings.google_provider.requests.post", return_value=mock_resp) as mock_post:
            provider.embed("test text")

        call_kwargs = mock_post.call_args[1]
        body = call_kwargs["json"]
        assert body["content"]["parts"][0]["text"] == "test text"
        assert "models/gemini-embedding-001" in body["model"]


# ---------------------------------------------------------------------------
# embed_batch()
# ---------------------------------------------------------------------------

class TestGoogleProviderEmbedBatch:
    def _make_batch_response(self, vectors: list[list[float]]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": [{"values": v} for v in vectors]}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_embed_batch(self):
        """embed_batch() should return a list of vectors matching the input count."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        vecs = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        mock_resp = self._make_batch_response(vecs)

        with patch("ember_memory.core.embeddings.google_provider.requests.post", return_value=mock_resp) as mock_post:
            result = provider.embed_batch(["a", "b", "c"])

        assert result == vecs
        mock_post.assert_called_once()

    def test_embed_batch_preserves_order(self):
        """embed_batch() must return vectors in the same order as inputs."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        vecs = [[1.0], [2.0]]
        mock_resp = self._make_batch_response(vecs)

        with patch("ember_memory.core.embeddings.google_provider.requests.post", return_value=mock_resp):
            result = provider.embed_batch(["first", "second"])

        assert result[0] == [1.0]
        assert result[1] == [2.0]


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------

class TestGoogleProviderValidation:
    def test_requires_api_key(self):
        """Empty string for api_key must raise ValueError."""
        with pytest.raises(ValueError, match="API key"):
            GoogleProvider(api_key="")

    def test_requires_api_key_none_raises(self):
        """None for api_key must also raise ValueError."""
        with pytest.raises(ValueError):
            GoogleProvider(api_key=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------

class TestGoogleProviderHealthCheck:
    def test_health_check_true(self):
        """health_check() returns True when embed() succeeds."""
        provider = GoogleProvider(api_key=_FAKE_KEY)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embedding": {"values": _FAKE_VEC}}
        mock_resp.raise_for_status = MagicMock()

        with patch("ember_memory.core.embeddings.google_provider.requests.post", return_value=mock_resp):
            result = provider.health_check()

        assert result is True

    def test_health_check_false(self):
        """health_check() returns False when embed() raises an exception."""
        provider = GoogleProvider(api_key=_FAKE_KEY)

        with patch(
            "ember_memory.core.embeddings.google_provider.requests.post",
            side_effect=Exception("network error"),
        ):
            result = provider.health_check()

        assert result is False
