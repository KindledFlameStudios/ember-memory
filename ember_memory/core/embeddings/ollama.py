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
        self._url = url
        self._model = model
        self._dim = None
        self._base_url = self._url.rsplit("/api/", 1)[0] if "/api/" in self._url else self._url

    def embed(self, text: str) -> list[float]:
        """Embed a single piece of text via Ollama.

        Attempts to use the modern ``/api/embed`` endpoint first. If it receives
        a 404 Not Found (indicating an older Ollama version), it falls back
        gracefully to the legacy ``/api/embeddings`` endpoint.

        Args:
            text: The input string to embed. Must be non-empty.

        Returns:
            A list of floats of length ``self.dimension()``.

        Raises:
            requests.HTTPError: If the Ollama server returns a non-2xx status.
        """
        # Try modern endpoint first
        url = f"{self._base_url}/api/embed"
        resp = requests.post(url, json={"model": self._model, "input": text}, timeout=30)
        if resp.status_code != 404:
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
            
        # Fallback to legacy endpoint
        url = f"{self._base_url}/api/embeddings"
        resp = requests.post(url, json={"model": self._model, "prompt": text}, timeout=30)
        resp.raise_for_status()
        return resp.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in a single Ollama request.

        Ollama's ``/api/embed`` endpoint accepts an array for ``input``. If the
        modern endpoint is unavailable, it gracefully falls back to iterating
        requests against the legacy ``/api/embeddings`` endpoint.

        Args:
            texts: A non-empty list of input strings.

        Returns:
            A list of embedding vectors in the same order as ``texts``.

        Raises:
            requests.HTTPError: If the Ollama server returns a non-2xx status.
        """
        # Try modern endpoint first
        url = f"{self._base_url}/api/embed"
        resp = requests.post(url, json={"model": self._model, "input": texts}, timeout=60)
        if resp.status_code != 404:
            resp.raise_for_status()
            return resp.json()["embeddings"]
            
        # Fallback to iterating legacy endpoint
        results = []
        for text in texts:
            results.append(self.embed(text))
        return results

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
