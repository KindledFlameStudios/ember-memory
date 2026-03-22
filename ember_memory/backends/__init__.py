"""Storage backend abstraction for Ember Memory."""

from ember_memory.backends.base import MemoryBackend
from ember_memory.backends.loader import get_backend

__all__ = ["MemoryBackend", "get_backend"]
