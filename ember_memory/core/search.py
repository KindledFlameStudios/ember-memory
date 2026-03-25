"""Unified search layer — coordinates embedding, backend, namespaces, and scoring.

This is the central retrieval function called by every CLI hook.
The Engine scoring integration point is marked for Plan 3.
"""

import logging
from dataclasses import dataclass, field

from ember_memory.core.namespaces import get_visible_collections
from ember_memory.core.backends.base import MemoryBackend
from ember_memory.core.embeddings.base import EmbeddingProvider

logger = logging.getLogger("ember-memory.search")


@dataclass
class RetrievalResult:
    """A single memory retrieval result."""
    id: str
    content: str
    collection: str
    similarity: float
    composite_score: float  # = similarity for now; Engine overrides in Plan 3
    metadata: dict = field(default_factory=dict)


def retrieve(
    prompt: str,
    ai_id: str | None = None,
    backend: MemoryBackend | None = None,
    embedder: EmbeddingProvider | None = None,
    limit: int = 5,
    similarity_threshold: float = 0.35,
) -> list[RetrievalResult]:
    """Retrieve relevant memories for a prompt.

    Steps:
    1. Get visible collections for this AI (namespace filtering)
    2. Embed the query
    3. Search each visible collection
    4. Merge, filter by threshold, sort by composite_score
    5. Return top N results

    Engine scoring (Plan 3) will hook in between steps 3 and 4
    to re-score results using heat, connections, and decay.
    """
    if not backend or not embedder:
        logger.warning("retrieve() called without backend or embedder")
        return []

    # 1. Get visible collections for this AI
    all_collections = backend.list_collections()
    all_names = [c["name"] for c in all_collections if c.get("count", 0) > 0]
    visible = get_visible_collections(all_names, ai_id=ai_id)

    if not visible:
        return []

    # 2. Embed the query
    try:
        query_embedding = embedder.embed(prompt)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return []

    # 3. Search each visible collection
    all_results: list[RetrievalResult] = []
    for collection_name in visible:
        try:
            raw_results = backend.search(
                collection=collection_name,
                query_embedding=query_embedding,
                limit=limit,
            )
            for r in raw_results:
                sim = r.get("similarity", 0.0)
                if sim >= similarity_threshold:
                    all_results.append(RetrievalResult(
                        id=r["id"],
                        content=r["content"],
                        collection=collection_name,
                        similarity=sim,
                        composite_score=sim,  # Engine scoring overrides this in Plan 3
                        metadata=r.get("metadata", {}),
                    ))
        except Exception as e:
            logger.warning(f"Search failed for '{collection_name}': {e}")
            continue

    # 4. Sort by composite score and limit
    all_results.sort(key=lambda r: r.composite_score, reverse=True)
    return all_results[:limit]
