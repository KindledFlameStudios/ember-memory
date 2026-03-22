"""Embedding function loader — resolves provider name to callable."""

from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from ember_memory import config


def get_embedding_fn(provider: str = "ollama", **kwargs):
    """Create and return the configured embedding function.

    Returns a ChromaDB-compatible embedding function. For backends that
    accept raw vectors (like Qdrant), the embedding function is called
    directly to produce vectors before storage.
    """
    if provider == "ollama":
        url = kwargs.get("ollama_url", config.OLLAMA_URL)
        model = kwargs.get("embedding_model", config.EMBEDDING_MODEL)
        return OllamaEmbeddingFunction(url=url, model_name=model)
    else:
        raise ValueError(
            f"Unknown embedding provider: '{provider}'. Available: ollama"
        )
