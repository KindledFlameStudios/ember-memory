"""OpenAI embedding provider — cloud-based, requires API key."""

import requests
from ember_memory.core.embeddings.base import EmbeddingProvider

_MODEL_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

API_URL = "https://api.openai.com/v1/embeddings"


class OpenAIProvider(EmbeddingProvider):
    """Embed via OpenAI's embedding API."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = api_key
        self._model = model
        self._dim = _MODEL_DIMS.get(model, 1536)

    def _request(self, input_data):
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "input": input_data},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def embed(self, text: str) -> list[float]:
        data = self._request(text)
        return data["data"][0]["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        data = self._request(texts)
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x.get("index", 0))]

    def dimension(self) -> int:
        return self._dim

    def health_check(self) -> bool:
        try:
            self._request("health check")
            return True
        except Exception:
            return False
