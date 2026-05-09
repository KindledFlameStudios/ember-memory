"""Ollama embedding provider — local nomic-embed-text by default."""

import requests
from ember_memory.core.embeddings.base import EmbeddingProvider


class OllamaProvider(EmbeddingProvider):
    """Embed via local Ollama server.

    Uses the Ollama ``/api/embed`` endpoint. The default model is ``nomic-embed-text``,
    which produces 768-dimensional vectors and runs well on CPU.

    Args:
        url: Full URL to the Ollama embed endpoint.
        model: Name of the Ollama model to use for embedding.
    """

    def __init__(self, url: str = "http://localhost:11434/api/embed",
                 model: str = "nomic-embed-text"):
        # Normalize: always use /api/embed (the modern endpoint)
        self._url = url.replace("/api/embeddings", "/api/embed")
        self._model = model
        self._dim = None
        self._base_url = self._url.rsplit("/api/", 1)[0] if "/api/" in self._url else self._url

    def embed(self, text: str) -> list[float]:
        """Embed a single piece of text via Ollama.

        Args:
            text: The input string to embed. Must be non-empty.

        Returns:
            A list of floats of length ``self.dimension()``.

        Raises:
            requests.HTTPError: If the Ollama server returns a non-2xx status.
        """
        resp = requests.post(self._url, json={"model": self._model, "input": text}, timeout=30)
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in a single Ollama request.

        Ollama's ``/api/embed`` endpoint accepts an array for ``input``, so
        this avoids the overhead of one HTTP round-trip per text.

        Args:
            texts: A non-empty list of input strings.

        Returns:
            A list of embedding vectors in the same order as ``texts``.

        Raises:
            requests.HTTPError: If the Ollama server returns a non-2xx status.
        """
        resp = requests.post(self._url, json={"model": self._model, "input": texts}, timeout=60)
        resp.raise_for_status()
        return resp.json()["embeddings"]

    def dimension(self) -> int:
        """Return the vector dimensionality for the configured model.

        Dynamically determines the dimension by embedding a single token
        on the first call, defaulting to 768 if the server is unreachable.
        
        Returns:
            An integer representing the dimensionality of the model.
        """
        if self._dim is None:
            try:
                self._dim = len(self.embed("test"))
            except Exception:
                self._dim = 768
        return self._dim

    def health_check(self) -> bool:
        """Ping the Ollama base URL to verify the server is reachable.

        Returns:
            True if the server responds with an OK status, False otherwise.
            Never raises; all exceptions are swallowed.
        """
        try:
            resp = requests.get(self._base_url, timeout=5)
            return resp.ok
        except Exception:
            return False
