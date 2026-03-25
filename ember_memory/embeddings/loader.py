"""DEPRECATED — Use ember_memory.core.embeddings.loader instead."""
import warnings
warnings.warn(
    "ember_memory.embeddings.loader is deprecated. "
    "Use ember_memory.core.embeddings.loader instead.",
    DeprecationWarning,
    stacklevel=2,
)
# Re-export for backward compatibility
from ember_memory.core.embeddings.loader import get_embedding_provider as get_embedding_fn

# Original implementation preserved below for reference (renamed to avoid shadowing re-export)
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from ember_memory import config


def _get_embedding_fn_legacy(provider: str = "ollama", **kwargs):
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
