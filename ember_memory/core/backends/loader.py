"""Backend factory — resolves backend name to v2 implementation."""

from ember_memory.core.backends.base import MemoryBackend
from ember_memory import config


def get_backend_v2(backend: str | None = None, **kwargs) -> MemoryBackend:
    """Create and return the configured v2 storage backend.

    Args:
        backend:  Backend name. Defaults to ``config.BACKEND`` (env/config.env).
                  Currently supported: ``"chromadb"``.
        **kwargs: Optional overrides. Recognised keys:
                  - ``data_dir`` (str): Storage directory. Defaults to
                    ``config.DATA_DIR``.

    Returns:
        A connected :class:`MemoryBackend` instance ready for use.

    Raises:
        ValueError: If the backend name is not recognised.
    """
    backend = backend or config.BACKEND
    data_dir = kwargs.get("data_dir", config.DATA_DIR)

    if backend == "chromadb":
        from ember_memory.core.backends.chromadb_backend import ChromaBackendV2
        b = ChromaBackendV2(data_dir=data_dir)
        b.connect()
        return b
    else:
        raise ValueError(
            f"Unknown backend: '{backend}'. Available: chromadb"
        )
