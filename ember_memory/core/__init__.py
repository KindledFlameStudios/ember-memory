"""Public core interfaces loaded lazily to keep headless consumers lightweight."""

from __future__ import annotations

from typing import Any

__all__ = ["EmbeddingProvider", "MemoryBackend"]


def __getattr__(name: str) -> Any:
    if name == "EmbeddingProvider":
        from ember_memory.core.embeddings.base import EmbeddingProvider

        return EmbeddingProvider
    if name == "MemoryBackend":
        from ember_memory.core.backends.base import MemoryBackend

        return MemoryBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
