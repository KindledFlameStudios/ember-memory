"""OpenRouter embedding provider — OpenAI-compatible embeddings API."""

import requests

from ember_memory.core.embeddings.base import EmbeddingProvider

API_URL = "https://openrouter.ai/api/v1/embeddings"

_MODEL_DIMS = {
    # OpenAI
    "openai/text-embedding-3-large": 3072,
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-ada-002": 1536,
    # Google
    "google/gemini-embedding-2-preview": 3072,
    "google/gemini-embedding-001": 3072,
    # Mistral
    "mistralai/mistral-embed-2312": 1024,
    "mistralai/codestral-embed-2505": 1024,
    # Qwen
    "qwen/qwen3-embedding-8b": 4096,
    "qwen/qwen3-embedding-4b": 2560,
    "qwen/qwen3-embedding-0.6b": 1024,
    # NVIDIA
    "nvidia/llama-nemotron-embed-vl-1b-v2:free": 1024,
    # Perplexity
    "perplexity/pplx-embed-v1-4b": 1024,
    "perplexity/pplx-embed-v1-0.6b": 768,
    # BAAI
    "baai/bge-m3": 1024,
    "baai/bge-large-en-v1.5": 1024,
    "baai/bge-base-en-v1.5": 768,
    # Intfloat / E5
    "intfloat/multilingual-e5-large": 1024,
    "intfloat/e5-large-v2": 1024,
    "intfloat/e5-base-v2": 768,
    # Thenlper / GTE
    "thenlper/gte-large": 1024,
    "thenlper/gte-base": 768,
    # Sentence Transformers
    "sentence-transformers/all-mpnet-base-v2": 768,
    "sentence-transformers/multi-qa-mpnet-base-dot-v1": 768,
    "sentence-transformers/all-minilm-l12-v2": 384,
    "sentence-transformers/all-minilm-l6-v2": 384,
    "sentence-transformers/paraphrase-minilm-l6-v2": 384,
}


class OpenRouterProvider(EmbeddingProvider):
    """Embed via OpenRouter's unified embeddings endpoint."""

    def __init__(self, api_key: str, model: str = "baai/bge-m3"):
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        self._api_key = api_key
        self._model = model
        self._dim = _MODEL_DIMS.get(model, 1024)

    def _request(self, input_data):
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/KindledFlameStudios/ember-memory",
                "X-Title": "Ember Memory",
            },
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
