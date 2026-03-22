"""Backend loader — resolves backend name to implementation."""

from ember_memory.backends.base import MemoryBackend
from ember_memory.embeddings import get_embedding_fn


def get_backend(backend: str = "chromadb", data_dir: str = "",
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
