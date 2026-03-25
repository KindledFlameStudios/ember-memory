"""Google embedding provider — uses Gemini embedding API."""

import requests
from ember_memory.core.embeddings.base import EmbeddingProvider

_MODEL_DIMS = {
    "text-embedding-004": 768,
}


class GoogleProvider(EmbeddingProvider):
    """Embed via Google's Gemini embedding API."""

    def __init__(self, api_key: str, model: str = "text-embedding-004"):
        if not api_key:
            raise ValueError("Google API key is required")
        self._api_key = api_key
        self._model = model
        self._dim = _MODEL_DIMS.get(model, 768)
        self._url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
        self._batch_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"

    def embed(self, text: str) -> list[float]:
        resp = requests.post(
            f"{self._url}?key={self._api_key}",
            json={"model": f"models/{self._model}", "content": {"parts": [{"text": text}]}},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]["values"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        requests_body = [
            {"model": f"models/{self._model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
        resp = requests.post(
            f"{self._batch_url}?key={self._api_key}",
            json={"requests": requests_body},
            timeout=60,
        )
        resp.raise_for_status()
        return [item["values"] for item in resp.json()["embeddings"]]

    def dimension(self) -> int:
        return self._dim

    def health_check(self) -> bool:
        try:
            self.embed("health check")
            return True
        except Exception:
            return False
