"""Tests for ember_memory.core.embeddings.openrouter_provider."""

from unittest.mock import MagicMock, patch

import pytest

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory.core.embeddings.openrouter_provider import API_URL, OpenRouterProvider

FAKE_KEY = "sk-or-test"
MODEL = "baai/bge-m3"
FAKE_VECTOR = [0.1] * 1024


def _make_response(embeddings):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": [
            {"embedding": vec, "index": i}
            for i, vec in enumerate(embeddings)
        ]
    }
    return mock_resp


def test_implements_interface():
    provider = OpenRouterProvider(api_key=FAKE_KEY)
    assert isinstance(provider, EmbeddingProvider)


def test_dimension_bge_m3():
    provider = OpenRouterProvider(api_key=FAKE_KEY, model=MODEL)
    assert provider.dimension() == 1024


def test_embed_posts_to_openrouter_embeddings_api():
    provider = OpenRouterProvider(api_key=FAKE_KEY, model=MODEL)
    mock_resp = _make_response([FAKE_VECTOR])

    with patch("ember_memory.core.embeddings.openrouter_provider.requests.post", return_value=mock_resp) as post:
        result = provider.embed("hello world")

    assert result == FAKE_VECTOR
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == API_URL
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert kwargs["json"] == {"model": MODEL, "input": "hello world"}


def test_embed_batch_returns_sorted():
    provider = OpenRouterProvider(api_key=FAKE_KEY, model=MODEL)
    vec_a = [0.1] * 1024
    vec_b = [0.9] * 1024
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": [
            {"embedding": vec_b, "index": 1},
            {"embedding": vec_a, "index": 0},
        ]
    }

    with patch("ember_memory.core.embeddings.openrouter_provider.requests.post", return_value=mock_resp):
        result = provider.embed_batch(["first", "second"])

    assert result == [vec_a, vec_b]


def test_requires_api_key():
    with pytest.raises(ValueError, match="OpenRouter API key is required"):
        OpenRouterProvider(api_key="")


def test_health_check_false_on_exception():
    provider = OpenRouterProvider(api_key=FAKE_KEY)
    with patch.object(provider, "_request", side_effect=RuntimeError("boom")):
        assert provider.health_check() is False
