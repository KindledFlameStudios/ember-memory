"""ember_memory.core — v2 abstract interfaces for embeddings and backends."""

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory.core.backends.base import MemoryBackend

__all__ = ["EmbeddingProvider", "MemoryBackend"]
