"""Unified search layer — coordinates embedding, backend, namespaces, and scoring.

This is the central retrieval function called by every CLI hook.
The Engine scoring integration point is marked for Plan 3.
"""

import logging
import os
from dataclasses import dataclass, field

from ember_memory.core.namespaces import get_visible_collections
from ember_memory.core.backends.base import MemoryBackend
from ember_memory.core.embeddings.base import EmbeddingProvider

logger = logging.getLogger("ember-memory.search")

# Module-level Engine cache: keyed by db_path so each unique DB gets one set of
# objects (lazy init, never re-created across calls with the same path).
_engine_cache: dict[str, tuple] = {}  # db_path -> (EngineState, HeatMap, ConnectionGraph)


def _get_engine(db_path: str):
    """Return (EngineState, HeatMap, ConnectionGraph) for db_path, creating once.

    Returns None if initialization fails — Engine is always optional.
    """
    if db_path in _engine_cache:
        return _engine_cache[db_path]

    try:
        # Ensure the parent directory exists
        engine_dir = os.path.dirname(db_path)
        os.makedirs(engine_dir, exist_ok=True)

        from ember_memory.core.engine.state import EngineState
        from ember_memory.core.engine.heat import HeatMap
        from ember_memory.core.engine.connections import ConnectionGraph

        state = EngineState(db_path=db_path)
        heat = HeatMap(state)
        connections = ConnectionGraph(state)
        _engine_cache[db_path] = (state, heat, connections)
        return _engine_cache[db_path]
    except Exception as e:
        logger.warning(f"Engine init failed for '{db_path}', falling back to similarity-only: {e}")
        return None


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
    engine_db_path: str | None = None,
) -> list[RetrievalResult]:
    """Retrieve relevant memories for a prompt.

    Steps:
    1. Get visible collections for this AI (namespace filtering)
    2. Embed the query
    3. Search each visible collection
    4. Engine re-scores results using heat, connections, and decay (if engine_db_path given)
    5. Merge, filter by threshold, sort by composite_score
    6. Record access patterns and co-occurrences in Engine state
    7. Return top N results

    When engine_db_path is None, composite_score == similarity (backward compatible).
    Engine is always optional — any failure falls back to similarity-only scoring.
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

    # 3. Search each visible collection — collect ALL raw results first so the
    #    connection bonus calculation has the full result set available.
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
                        composite_score=sim,  # default; Engine overrides below
                        metadata=r.get("metadata", {}),
                    ))
        except Exception as e:
            logger.warning(f"Search failed for '{collection_name}': {e}")
            continue

    # 4. Engine re-scoring (optional — only when engine_db_path is provided)
    if engine_db_path and all_results:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            engine_state, heat_map, connections = engine
            try:
                from ember_memory.core.engine.scoring import composite_score, compute_decay

                # Need all IDs up-front for connection bonus calculation
                all_ids = [r.id for r in all_results]

                for result in all_results:
                    # Heat boost — skip if this ai_id is on the ignore list
                    if ai_id and heat_map.is_ignored(ai_id):
                        heat_boost = 0.0
                    else:
                        heat_boost = heat_map.get_boost(result.id, ai_id=ai_id)

                    # Connection bonus: other results in this retrieval as context
                    context_ids = [rid for rid in all_ids if rid != result.id]
                    connection_bonus = connections.get_bonus(result.id, context_ids)

                    # Decay: based on how recently this memory was accessed
                    last_accessed = engine_state.get_last_accessed(result.id)
                    decay_factor = compute_decay(last_accessed)

                    result.composite_score = composite_score(
                        similarity=result.similarity,
                        heat_boost=heat_boost,
                        connection_bonus=connection_bonus,
                        decay_factor=decay_factor,
                    )
            except Exception as e:
                logger.warning(f"Engine scoring failed, keeping similarity scores: {e}")
                # Already defaulted to similarity — nothing to reset

    # 5. Sort by composite score and limit
    all_results.sort(key=lambda r: r.composite_score, reverse=True)
    final_results = all_results[:limit]

    # 6. Update Engine state after retrieval (records patterns for future boosts)
    if engine_db_path and final_results:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            engine_state, heat_map, connections = engine
            try:
                # Record access for every returned result
                for result in final_results:
                    heat_map.record_access(result.id, ai_id=ai_id)
                    engine_state.update_last_accessed(result.id)

                # Record co-occurrence among returned results
                result_ids = [r.id for r in final_results]
                if len(result_ids) > 1:
                    connections.record_co_occurrence(result_ids)

                # Tick decay for this retrieval event
                heat_map.tick(ai_id=ai_id)
                connections.tick()
                engine_state.increment_tick()
            except Exception as e:
                logger.warning(f"Engine state update failed: {e}")

    return final_results
