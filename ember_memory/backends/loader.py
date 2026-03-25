"""DEPRECATED — Use ember_memory.core.backends.loader instead."""
import warnings
warnings.warn(
    "ember_memory.backends.loader is deprecated. "
    "Use ember_memory.core.backends.loader instead.",
    DeprecationWarning,
    stacklevel=2,
)
# Re-export for backward compatibility
from ember_memory.core.backends.loader import get_backend_v2 as get_backend

# Original implementation preserved below for reference (renamed to avoid shadowing re-export)
from ember_memory.backends.base import MemoryBackend
from ember_memory.embeddings import get_embedding_fn


def _get_backend_legacy(backend: str = "chromadb", data_dir: str = "",
                        embedding_provider: str = "ollama", **kwargs) -> MemoryBackend:
    """Create and return the configured storage backend."""
    embedding_fn = get_embedding_fn(embedding_provider, **kwargs)

    if backend == "chromadb":
        from ember_memory.backends.chromadb_backend import ChromaBackend
        return ChromaBackend(data_dir=data_dir, embedding_fn=embedding_fn)
    else:
        raise ValueError(
            f"Unknown backend: '{backend}'. Available: chromadb"
        )
