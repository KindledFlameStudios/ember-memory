"""Tests for the Ollama embedding provider."""

import unittest
from unittest.mock import MagicMock, patch

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory.core.embeddings.ollama import OllamaProvider


class TestOllamaProviderInterface(unittest.TestCase):
    """Verify OllamaProvider correctly implements EmbeddingProvider."""

    def test_implements_interface(self):
        """OllamaProvider must be a subclass of EmbeddingProvider."""
        self.assertTrue(issubclass(OllamaProvider, EmbeddingProvider))

    @patch("ember_memory.core.embeddings.ollama.requests.post")
    def test_dimension_nomic_embed_text(self, mock_post):
        """nomic-embed-text should dynamically report 768 dimensions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1] * 768]}
        mock_post.return_value = mock_response
        
        provider = OllamaProvider(model="nomic-embed-text")
        self.assertEqual(provider.dimension(), 768)
        mock_post.assert_called_once()

    @patch("ember_memory.core.embeddings.ollama.requests.post")
    def test_dimension_bge_m3(self, mock_post):
        """bge-m3 should dynamically report 1024 dimensions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1] * 1024]}
        mock_post.return_value = mock_response
        
        provider = OllamaProvider(model="bge-m3")
        self.assertEqual(provider.dimension(), 1024)

    @patch("ember_memory.core.embeddings.ollama.requests.post")
    def test_dimension_unknown_model_defaults_to_768_on_error(self, mock_post):
        """If the API call fails, it falls back to 768."""
        mock_post.side_effect = Exception("API error")
        provider = OllamaProvider(model="some-future-model")
        self.assertEqual(provider.dimension(), 768)


class TestOllamaProviderEmbed(unittest.TestCase):
    """Tests for embed() and embed_batch()."""

    def _make_provider(self):
        return OllamaProvider()

    def test_embed_returns_vector(self):
        """embed() should return the first embedding from the response."""
        fake_vector = [0.1] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [fake_vector]}
        mock_response.raise_for_status.return_value = None

        with patch("ember_memory.core.embeddings.ollama.requests.post",
                   return_value=mock_response) as mock_post:
            provider = self._make_provider()
            result = provider.embed("hello world")

        mock_post.assert_called_once_with(
            "http://localhost:11434/api/embed",
            json={"model": "nomic-embed-text", "input": "hello world"},
            timeout=30,
        )
        self.assertEqual(result, fake_vector)
        self.assertEqual(len(result), 768)

    def test_embed_batch(self):
        """embed_batch() should return one vector per input text."""
        vec_a = [0.1] * 768
        vec_b = [0.2] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [vec_a, vec_b]}
        mock_response.raise_for_status.return_value = None

        texts = ["first sentence", "second sentence"]

        with patch("ember_memory.core.embeddings.ollama.requests.post",
                   return_value=mock_response) as mock_post:
            provider = self._make_provider()
            result = provider.embed_batch(texts)

        mock_post.assert_called_once_with(
            "http://localhost:11434/api/embed",
            json={"model": "nomic-embed-text", "input": texts},
            timeout=60,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], vec_a)
        self.assertEqual(result[1], vec_b)

    def test_embed_raises_on_http_error(self):
        """embed() must propagate HTTP errors from raise_for_status()."""
        import requests as req_lib

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req_lib.HTTPError("500 Server Error")

        with patch("ember_memory.core.embeddings.ollama.requests.post",
                   return_value=mock_response):
            provider = self._make_provider()
            with self.assertRaises(req_lib.HTTPError):
                provider.embed("bad request")


class TestOllamaProviderHealthCheck(unittest.TestCase):
    """Tests for health_check()."""

    def test_health_check_true(self):
        """health_check() returns True when Ollama responds with ok=True."""
        mock_response = MagicMock()
        mock_response.ok = True

        with patch("ember_memory.core.embeddings.ollama.requests.get",
                   return_value=mock_response):
            provider = OllamaProvider()
            self.assertTrue(provider.health_check())

    def test_health_check_false_on_connection_error(self):
        """health_check() returns False when a ConnectionError is raised."""
        with patch("ember_memory.core.embeddings.ollama.requests.get",
                   side_effect=ConnectionError("refused")):
            provider = OllamaProvider()
            self.assertFalse(provider.health_check())

    def test_health_check_false_on_bad_status(self):
        """health_check() returns False when server responds with ok=False."""
        mock_response = MagicMock()
        mock_response.ok = False

        with patch("ember_memory.core.embeddings.ollama.requests.get",
                   return_value=mock_response):
            provider = OllamaProvider()
            self.assertFalse(provider.health_check())

    def test_health_check_pings_base_url(self):
        """health_check() strips the /api/embed path and pings the root."""
        mock_response = MagicMock()
        mock_response.ok = True

        with patch("ember_memory.core.embeddings.ollama.requests.get",
                   return_value=mock_response) as mock_get:
            provider = OllamaProvider(url="http://localhost:11434/api/embed")
            provider.health_check()

        mock_get.assert_called_once_with("http://localhost:11434", timeout=5)


if __name__ == "__main__":
    unittest.main()
