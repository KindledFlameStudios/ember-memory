"""Unified search layer — coordinates embedding, backend, namespaces, and scoring.

This is the central retrieval function called by every CLI hook.
Engine scoring is applied here when an engine DB path is available.
"""

import json
import logging
import os
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field

from ember_memory import config
from ember_memory.core.namespaces import get_visible_collections
from ember_memory.core.backends.base import MemoryBackend
from ember_memory.core.embeddings.base import EmbeddingProvider

logger = logging.getLogger("ember-memory.search")

# Module-level Engine cache: keyed by db_path so each unique DB gets one set of
# objects (lazy init, never re-created across calls with the same path).
_engine_cache: dict[str, tuple] = {}  # db_path -> (EngineState, HeatMap, ConnectionGraph)

# Module-level embedding cache: list of (query_text, embedding_vector)
_embed_cache: list[tuple[str, list[float]]] = []
_EMBED_CACHE_MAX = 20
_EMBED_CACHE_THRESHOLD = 0.85


def _get_cached_embedding(prompt: str) -> list[float] | None:
    """Check if a similar query was recently embedded. Returns cached vector or None."""
    for cached_text, cached_vec in reversed(_embed_cache):
        ratio = SequenceMatcher(None, prompt[:200], cached_text[:200]).ratio()
        if ratio >= _EMBED_CACHE_THRESHOLD:
            return cached_vec
    return None


def _cache_embedding(prompt: str, embedding: list[float]) -> None:
    """Add an embedding to the cache, evicting oldest if full."""
    _embed_cache.append((prompt, embedding))
    if len(_embed_cache) > _EMBED_CACHE_MAX:
        _embed_cache.pop(0)


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
    composite_score: float  # Defaults to similarity; Engine scoring may override it.
    metadata: dict = field(default_factory=dict)
    score_breakdown: dict = field(default_factory=dict)


def retrieve(
    prompt: str,
    ai_id: str | None = None,
    workspace: str | None = None,
    cwd: str | None = None,
    session_id: str | None = None,
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
    4. Fuse vector similarity with BM25 keyword ranking via RRF
    5. Engine re-scores results using heat, connections, and decay (if engine_db_path given)
    6. Deduplicate overlapping results
    7. Sort and limit by composite_score
    8. Record access patterns and co-occurrences in Engine state

    When engine_db_path is None, composite_score == similarity (backward compatible).
    Engine is always optional — any failure falls back to similarity-only scoring.
    """
    if not backend or not embedder:
        logger.warning("retrieve() called without backend or embedder")
        return []

    # 1. Get visible collections for this AI
    all_collections = backend.list_collections()
    all_names = [c["name"] for c in all_collections if c.get("count", 0) > 0]
    # "open" namespace mode bypasses AI filtering — all collections visible
    effective_ai_id = "*" if config.NAMESPACE_MODE == "open" else ai_id
    visible = get_visible_collections(all_names, ai_id=effective_ai_id)

    if engine_db_path and visible:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            engine_state, _, _ = engine
            visible = [
                name
                for name in visible
                if engine_state.get_config(f"collection_disabled_{name}", "false") != "true"
            ]

    # Workspace filtering: explicit > cwd auto-detect > none
    effective_workspace = workspace
    if not effective_workspace and cwd and engine_db_path:
        # Auto-detect workspace from working directory
        engine = _get_engine(engine_db_path)
        if engine:
            state = engine[0]
            ws_config = state.get_workspace_config()
            for ws_name, ws_def in ws_config.items():
                ws_cwd = ws_def.get("cwd", "")
                if ws_cwd and cwd.startswith(ws_cwd):
                    effective_workspace = ws_name
                    break

    if effective_workspace and engine_db_path:
        engine = _get_engine(engine_db_path)
        if engine:
            state = engine[0]
            ws_config = state.get_workspace_config()
            ws = ws_config.get(effective_workspace)
            if ws and "collections" in ws:
                ws_enabled = {k for k, v in ws["collections"].items() if v}
                visible = [v for v in visible if v in ws_enabled]

    if not visible:
        return []

    # 2. Embed the query (with cache)
    try:
        cached = _get_cached_embedding(prompt)
        if cached is not None:
            query_embedding = cached
            logger.debug("Embedding cache hit - skipping Ollama call")
        else:
            query_embedding = embedder.embed(prompt)
            _cache_embedding(prompt, query_embedding)
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
                if sim < similarity_threshold:
                    continue

                content = r.get("content", "")

                # Quality filter: skip chunks that are LONG but mostly
                # headers/metadata with no real content.
                # Short content (<100 chars) passes through — it might be
                # a valid concise entry. Only filter longer chunks that are
                # suspiciously hollow after stripping markdown chrome.
                if len(content) > 100:
                    plain = re.sub(r'^#{1,6}\s+.*$', '', content, flags=re.MULTILINE)
                    plain = re.sub(r'\*\*[^*]+\*\*:?\s*', '', plain)
                    plain = re.sub(r'^---+$', '', plain, flags=re.MULTILINE)
                    plain = plain.strip()
                    if len(plain) < 30:
                        continue  # Header-only chunk, skip

                all_results.append(RetrievalResult(
                        id=r["id"],
                        content=content,
                        collection=collection_name,
                        similarity=sim,
                        composite_score=sim,  # default; Engine overrides below
                        metadata=r.get("metadata", {}),
                    ))
        except Exception as e:
            logger.warning(f"Search failed for '{collection_name}': {e}")
            continue

    # 4. BM25 keyword re-ranking via Reciprocal Rank Fusion.
    # Threshold filtering already happened above, so keyword fusion only adjusts
    # ordering for candidate memories that were semantically relevant enough to pass.
    if len(all_results) > 1:
        from ember_memory.core.bm25 import BM25, reciprocal_rank_fusion

        bm25 = BM25()
        bm25.index([r.content for r in all_results])
        bm25_scores = bm25.score_all(prompt)

        # Only fuse when BM25 contributes a real keyword signal. Without this
        # guard, all-zero BM25 scores would still impose an arbitrary ranking.
        if any(score > 0 for score in bm25_scores):
            vec_ranking = sorted(
                enumerate(all_results),
                key=lambda item: item[1].similarity,
                reverse=True,
            )
            vec_ranking = [(idx, result.similarity) for idx, result in vec_ranking]

            bm25_ranking = sorted(
                enumerate(bm25_scores),
                key=lambda item: item[1],
                reverse=True,
            )
            bm25_ranking = [(idx, score) for idx, score in bm25_ranking]

            fused = reciprocal_rank_fusion([vec_ranking, bm25_ranking])
            fused.sort(
                key=lambda item: (
                    item[1],
                    bm25_scores[item[0]],
                    all_results[item[0]].similarity,
                ),
                reverse=True,
            )
            max_rrf = fused[0][1] if fused else 0.0

            reordered: list[RetrievalResult] = []
            total = len(fused)
            for rank, (doc_idx, rrf_score) in enumerate(fused):
                result = all_results[doc_idx]

                # Convert the fused order into a normalized score and blend it
                # into similarity so later composite-score sorting preserves the
                # hybrid ranking while staying in the [0, 1] range.
                rank_score = 1.0 if total == 1 else 1.0 - (rank / (total - 1))
                rrf_score_norm = (rrf_score / max_rrf) if max_rrf > 0 else rank_score
                fusion_score = (rrf_score_norm * 0.5) + (rank_score * 0.5)
                hybrid_similarity = (result.similarity * 0.6) + (fusion_score * 0.4)

                result.metadata = {
                    **result.metadata,
                    "vector_similarity": result.similarity,
                    "bm25_score": round(bm25_scores[doc_idx], 4),
                    "rrf_score": round(rrf_score, 4),
                }
                result.similarity = min(max(hybrid_similarity, 0.0), 1.0)
                result.composite_score = result.similarity
                reordered.append(result)

            all_results = reordered

    # 5. Engine re-scoring (optional — only when engine_db_path is provided)
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
                        heat_boost = heat_map.get_boost(result.id, ai_id=ai_id, session_id=session_id)

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
                    result.score_breakdown = {
                        "similarity": round(result.similarity, 4),
                        "heat_boost": round(heat_boost, 4),
                        "connection_bonus": round(connection_bonus, 4),
                        "decay_factor": round(decay_factor, 4),
                        "composite_score": round(result.composite_score, 4),
                    }
            except Exception as e:
                logger.warning(f"Engine scoring failed, keeping similarity scores: {e}")
                # Already defaulted to similarity — nothing to reset

    # Apply user feedback adjustments after Engine scoring and before the
    # final sort/dedup pass so explicit ratings can influence future ranking.
    if engine_db_path and all_results:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            state = engine[0]
            for result in all_results:
                try:
                    feedback = float(state.get_config(f"feedback_{result.id}", "0"))
                except (TypeError, ValueError):
                    feedback = 0.0
                if feedback != 0:
                    adjustment = feedback * 0.05
                    result.composite_score = max(0.0, result.composite_score + adjustment)
                    if result.score_breakdown:
                        result.score_breakdown["feedback_adjustment"] = round(adjustment, 4)
                        result.score_breakdown["composite_score"] = round(result.composite_score, 4)

    # 6. Deduplicate — same content from different collections wastes slots.
    #    Keep the highest-scoring version of each unique content snippet.
    seen_content: dict[str, int] = {}
    deduped: list[RetrievalResult] = []
    for r in all_results:
        # Use first 200 chars as dedup key (handles minor formatting diffs)
        key = r.content[:200].strip()
        if key in seen_content:
            # Keep the one with higher composite score
            existing_idx = seen_content[key]
            if r.composite_score > deduped[existing_idx].composite_score:
                deduped[existing_idx] = r
        else:
            seen_content[key] = len(deduped)
            deduped.append(r)

    # 7. Sort by composite score and limit
    deduped.sort(key=lambda r: r.composite_score, reverse=True)
    final_results = deduped[:limit]

    # Inject pinned memories that match the query so they always surface when
    # the user mentions the configured trigger topic.
    if engine_db_path:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            state = engine[0]
            prompt_lower = prompt.lower()
            try:
                pins = json.loads(state.get_config("pinned_memories", "[]"))
            except Exception:
                pins = []

            pinned_results: list[RetrievalResult] = []
            for pin in pins:
                trigger = str(pin.get("trigger", "")).strip().lower()
                pin_id = str(pin.get("memory_id", "")).strip()
                collection = str(pin.get("collection", "")).strip()
                if not trigger or trigger not in prompt_lower or not pin_id or not collection:
                    continue
                if any(r.id == pin_id for r in final_results) or any(r.id == pin_id for r in pinned_results):
                    continue

                try:
                    doc = backend.get(collection, pin_id)
                except Exception:
                    doc = None
                if not doc:
                    continue

                pinned_results.append(
                    RetrievalResult(
                        id=doc["id"],
                        content=doc.get("content", ""),
                        collection=collection,
                        similarity=1.0,
                        composite_score=1.0,
                        metadata=doc.get("metadata", {}),
                        score_breakdown={"pinned": True, "trigger": trigger, "composite_score": 1.0},
                    )
                )

            if pinned_results:
                final_results = pinned_results + final_results

    # 8. Update Engine state after retrieval (records patterns for future boosts)
    if engine_db_path and final_results:
        engine = _get_engine(engine_db_path)
        if engine is not None:
            engine_state, heat_map, connections = engine
            try:
                # Record access for every returned result
                for result in final_results:
                    heat_map.record_access(result.id, ai_id=ai_id, session_id=session_id)
                    engine_state.update_last_accessed(result.id)
                    engine_state.upsert_memory_meta(
                        result.id, result.collection, result.content
                    )

                # Record co-occurrence among returned results
                result_ids = [r.id for r in final_results]
                if len(result_ids) > 1:
                    connections.record_co_occurrence(result_ids)

                # Tick decay for this retrieval event
                heat_map.tick(ai_id=ai_id, session_id=session_id)
                connections.tick()
                engine_state.increment_tick()
            except Exception as e:
                logger.warning(f"Engine state update failed: {e}")

    return final_results
