"""Backend factory — resolves backend name to v2 implementation."""

import os

from ember_memory.core.backends.base import MemoryBackend
from ember_memory import config


def get_backend_v2(backend: str | None = None, **kwargs) -> MemoryBackend:
    """Create and return the configured v2 storage backend.

    Args:
        backend:  Backend name. Defaults to ``config.BACKEND`` (env/config.env).
                  Supported: ``"chromadb"``, ``"qdrant"``, ``"lancedb"``,
                  ``"sqlite-vec"``, ``"weaviate"``, ``"pinecone"``, ``"pgvector"``.
        **kwargs: Optional overrides passed to the backend constructor. Common
                  keys: ``data_dir``, ``url``, ``api_key``, ``in_memory``,
                  ``db_path``, ``index_name``, ``uri``, ``token``, ``dsn``,
                  ``host``, ``port``, ``dbname``, ``user``, ``password``.

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
    elif backend == "qdrant":
        from ember_memory.core.backends.qdrant_backend import QdrantBackend
        b = QdrantBackend(
            url=kwargs.get("url", "localhost:6333"),
            api_key=kwargs.get("api_key", ""),
            in_memory=kwargs.get("in_memory", False),
        )
        b.connect()
        return b
    elif backend == "lancedb":
        from ember_memory.core.backends.lancedb_backend import LanceBackend
        b = LanceBackend(data_dir=data_dir)
        b.connect()
        return b
    elif backend == "sqlite-vec":
        from ember_memory.core.backends.sqlite_vec_backend import SqliteVecBackend
        b = SqliteVecBackend(db_path=kwargs.get("db_path", os.path.join(data_dir, "ember_vec.db")))
        b.connect()
        return b
    elif backend == "weaviate":
        from ember_memory.core.backends.weaviate_backend import WeaviateBackend
        b = WeaviateBackend(
            url=kwargs.get("url", "http://localhost:8080"),
            api_key=kwargs.get("api_key", ""),
        )
        b.connect()
        return b
    elif backend == "pinecone":
        from ember_memory.core.backends.pinecone_backend import PineconeBackend
        b = PineconeBackend(
            api_key=kwargs.get("api_key", ""),
            index_name=kwargs.get("index_name", "ember-memory"),
        )
        b.connect()
        return b
    elif backend == "pgvector":
        from ember_memory.core.backends.pgvector_backend import PgvectorBackend
        b = PgvectorBackend(
            dsn=kwargs.get("dsn", ""),
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 5432),
            dbname=kwargs.get("dbname", "ember_memory"),
            user=kwargs.get("user", ""),
            password=kwargs.get("password", ""),
        )
        b.connect()
        return b
    else:
        raise ValueError(
            f"Unknown backend: '{backend}'. Available: chromadb, qdrant, lancedb, "
            f"sqlite-vec, weaviate, pinecone, pgvector"
        )
