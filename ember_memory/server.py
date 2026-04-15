"""
Ember Memory — MCP Server
==========================
Persistent semantic memory for AI coding CLIs via Model Context Protocol.
Provides tools to store, search, update, and manage knowledge across sessions.
"""

import logging
import os
import sys
from datetime import datetime, timezone

# Ensure the ember_memory package is importable when run as a standalone script.
_package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from mcp.server.fastmcp import FastMCP
from ember_memory import config
from ember_memory.core.embeddings.loader import get_embedding_provider
from ember_memory.core.backends.loader import get_backend_v2
from ember_memory.core.search import retrieve

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ember-memory")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

# ── Init ─────────────────────────────────────────────────────────────────────

mcp = FastMCP("ember-memory", instructions="""
Persistent semantic memory system. Use this to store and retrieve knowledge
across sessions — architecture decisions, project context, debugging insights,
anything worth remembering. Collections organize memories by topic.
""")

embedder = get_embedding_provider()
backend = get_backend_v2()


def _current_session_id() -> str:
    """Return a stable session ID for this MCP server process."""
    ai = os.environ.get("EMBER_AI_ID", "codex")
    return f"{ai}-{os.getpid()}"


def _write_retrieval_snapshot(prompt: str, results, elapsed_ms: int = 0):
    """Write activity log + last retrieval snapshots for the dashboard."""
    from datetime import datetime, timezone
    import json as _json

    ai_id = _current_ai_id()
    session_id = _current_session_id()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": session_id,
        "ai_id": ai_id,
        "prompt": prompt[:120],
        "hits": len(results),
        "top_score": round(results[0].composite_score, 3) if results else 0,
        "collections": list(set(r.collection for r in results)),
        "elapsed_ms": elapsed_ms,
    }
    try:
        log_path = os.path.join(config.DATA_DIR, "activity.jsonl")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(_json.dumps(entry) + "\n")
    except Exception:
        pass

    snapshot = {
        "ts": entry["ts"],
        "prompt": prompt[:200],
        "elapsed_ms": elapsed_ms,
        "ai_id": ai_id,
        "results": [
            {
                "collection": r.collection,
                "content": r.content,
                "similarity": round(r.similarity, 4),
                "composite_score": round(r.composite_score, 4),
                "score_breakdown": getattr(r, "score_breakdown", {}),
                "id": r.id[:32],
            }
            for r in results
        ],
    }
    try:
        for path in (
            os.path.join(config.DATA_DIR, "last_retrieval.json"),
            os.path.join(config.DATA_DIR, f"last_retrieval_{ai_id}.json"),
            os.path.join(config.DATA_DIR, f"last_retrieval_{session_id}.json"),
        ):
            with open(path, "w") as f:
                _json.dump(snapshot, f, indent=2)
    except Exception:
        pass


def _current_ai_id() -> str:
    """Return the current CLI identity for namespace-aware retrieval."""
    return os.environ.get("EMBER_AI_ID", "claude")


def _current_workspace() -> str | None:
    """Return the active workspace name, if one is set."""
    workspace = os.environ.get("EMBER_WORKSPACE", "").strip()
    return workspace or None


def _engine_db_path() -> str:
    """Return the configured Engine SQLite path."""
    return os.path.join(config.DATA_DIR, "engine", "engine.db")


def _preview_text(content: str, max_chars: int = 200) -> str:
    """Collapse whitespace and trim content for compact summaries."""
    compact = " ".join(content.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _format_search_result(
    heading: str,
    content: str,
    metadata: dict | None,
    similarity: float | None = None,
    composite_score: float | None = None,
) -> str:
    """Format a single search result block for MCP output."""
    meta = metadata or {}
    score_parts = []
    if composite_score is not None:
        score_parts.append(f"composite: {composite_score:.3f}")
    if similarity is not None:
        score_parts.append(f"similarity: {similarity:.3f}")

    score = f" ({', '.join(score_parts)})" if score_parts else ""
    tags = f" [tags: {meta.get('tags', '')}]" if meta.get("tags") else ""
    source = f" [source: {meta.get('source', '')}]" if meta.get("source") else ""
    return f"{heading}{score}{tags}{source}\n{content}"


def _get_hot_memories(limit: int, ai_id: str) -> tuple[list[dict], list[str]]:
    """Return the hottest tracked memories plus a deduped topic list."""
    from ember_memory.core.engine.heat import HeatMap
    from ember_memory.core.engine.state import EngineState
    from ember_memory.core.namespaces import parse_collection_name

    db_path = _engine_db_path()
    if not os.path.exists(db_path):
        return [], []

    state = EngineState(db_path=db_path)
    heat_map = HeatMap(state)
    heat_scope = ai_id if heat_map.get_mode() == "per_cli" else None
    ranked_heat = sorted(
        state.get_all_heat(ai_id=heat_scope).items(),
        key=lambda item: item[1],
        reverse=True,
    )

    hot_memories = []
    hot_topics = []
    for memory_id, heat in ranked_heat:
        meta = state.get_memory_meta(memory_id) or {}
        collection = meta.get("collection", "unknown")
        preview = meta.get("preview", f"Memory {memory_id}")
        hot_memories.append(
            {
                "id": memory_id,
                "collection": collection,
                "preview": preview,
                "heat": heat,
            }
        )
        topic = parse_collection_name(collection)[1] if collection != "unknown" else memory_id
        if topic not in hot_topics:
            hot_topics.append(topic)
        if len(hot_memories) >= limit:
            break

    return hot_memories, hot_topics


def _build_handoff_packet(
    topic: str,
    key_context: list[str],
    hot_topics: list[str],
    ai_id: str,
) -> str:
    """Render a compact, readable hand-off packet."""
    subject = topic or (hot_topics[0] if hot_topics else "Recent Context")
    lines = [
        "=== Hand-off Packet ===",
        f"Topic: {topic or 'Recent Context'}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"AI: {ai_id}",
        "",
        "## Key Context",
    ]

    if key_context:
        lines.extend(key_context)
    else:
        lines.append("No recent context available yet.")

    lines.extend(["", "## Hot Topics"])
    if hot_topics:
        lines.extend(f"- {hot_topic}" for hot_topic in hot_topics)
    else:
        lines.append("- None yet")

    lines.extend([
        "",
        "## Suggested Next Steps",
        f'- "What progress have we made on {subject}?"',
        f'- "Continue from where {ai_id} left off on {subject}"',
    ])
    return "\n".join(lines)


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def memory_store(
    content: str,
    collection: str | None = None,
    tags: str | None = None,
    source: str | None = None,
) -> str:
    """Store a memory for future retrieval. Use this to save architecture decisions,
    debugging insights, project context, or anything worth remembering across sessions.

    Args:
        content: The text to remember. Be specific — include context and reasoning.
        collection: Collection name (default: general). Use topic-based names
                   like 'architecture', 'debugging-notes', 'project-decisions'.
        tags: Comma-separated tags for filtering (e.g. 'backend,routing').
        source: Where this knowledge came from (e.g. 'session-2026-03-18', 'README.md').
    """
    col_name = collection or config.DEFAULT_COLLECTION
    doc_id = f"mem_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"

    metadata = {"stored_at": datetime.now(timezone.utc).isoformat()}
    if tags:
        metadata["tags"] = tags
    if source:
        metadata["source"] = source

    embedding = embedder.embed(content)
    count = backend.insert(col_name, doc_id, content, embedding, metadata)
    return f"Stored in '{col_name}' (id: {doc_id}). Collection now has {count} entries."


@mcp.tool()
def memory_find(
    query: str,
    collection: str | None = None,
    n_results: int | None = None,
    tags_filter: str | None = None,
) -> str:
    """Search memories by semantic similarity. Returns the most relevant stored knowledge.

    Args:
        query: Natural language search query (e.g. 'how does routing work').
        collection: Collection to search (default: general). Use '' or '*' to search all.
        n_results: Max results to return (default: 10).
        tags_filter: Only return entries containing this tag (e.g. 'backend').
    """
    n = max(n_results or config.SEARCH_LIMIT, 1)

    if collection in ("", "*"):
        raw_limit = n * 3 if tags_filter else n
        results = retrieve(
            prompt=query,
            ai_id=_current_ai_id(),
            workspace=_current_workspace(),
            cwd=os.getcwd(),
            session_id=_current_session_id(),
            backend=backend,
            embedder=embedder,
            limit=raw_limit,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
            engine_db_path=_engine_db_path(),
        )

        filtered_results = []
        for result in results:
            if tags_filter and tags_filter not in result.metadata.get("tags", ""):
                continue
            filtered_results.append(result)
            if len(filtered_results) >= n:
                break

        if not filtered_results:
            return "No memories found across any collection."

        try:
            _write_retrieval_snapshot(query, filtered_results)
        except Exception:
            pass

        output = []
        for result in filtered_results:
            composite_score = result.composite_score if result.score_breakdown else None
            output.append(
                _format_search_result(
                    heading=f"**[{result.collection}]**",
                    content=result.content,
                    metadata=result.metadata,
                    similarity=result.similarity,
                    composite_score=composite_score,
                )
            )
        return "\n\n---\n\n".join(output)

    col_name = collection or config.DEFAULT_COLLECTION
    query_embedding = embedder.embed(query)
    results = backend.search(col_name, query_embedding, n)

    if not results:
        return f"No matching memories found in '{col_name}'."

    output = []
    for r in results:
        metadata = r.get("metadata", {})
        if tags_filter and tags_filter not in metadata.get("tags", ""):
            continue
        output.append(
            _format_search_result(
                heading=f"**{r['id']}**",
                content=r["content"],
                metadata=metadata,
                similarity=r.get("similarity"),
            )
        )

    if not output:
        return f"No matching memories found in '{col_name}'."

    return f"Found {len(output)} results in '{col_name}':\n\n" + "\n\n---\n\n".join(output)


@mcp.tool()
def memory_handoff(topic: str = "", limit: int = 5) -> str:
    """Generate a hand-off packet — a compact summary of recent relevant context
    that another AI CLI can use to pick up where you left off.

    Args:
        topic: Optional topic focus for the hand-off. If empty, uses recent hot memories.
        limit: Number of memories to include.
    """
    packet_limit = max(limit, 1)
    ai_id = _current_ai_id()
    hot_memories, hot_topics = _get_hot_memories(packet_limit, ai_id)

    key_context = []
    if topic:
        results = retrieve(
            prompt=topic,
            ai_id=ai_id,
            workspace=_current_workspace(),
            backend=backend,
            embedder=embedder,
            limit=packet_limit,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
            engine_db_path=_engine_db_path(),
        )
        key_context = [
            f"{idx}. [{result.collection}] {_preview_text(result.content)}"
            for idx, result in enumerate(results, 1)
        ]
        if not hot_topics:
            hot_topics = list(dict.fromkeys(result.collection for result in results))
    else:
        key_context = [
            f"{idx}. [{memory['collection']}] {_preview_text(memory['preview'])}"
            for idx, memory in enumerate(hot_memories, 1)
        ]

    return _build_handoff_packet(
        topic=topic,
        key_context=key_context,
        hot_topics=hot_topics[:packet_limit],
        ai_id=ai_id,
    )


@mcp.tool()
def memory_delete(
    doc_id: str,
    collection: str | None = None,
) -> str:
    """Delete a specific memory entry by its ID.

    Args:
        doc_id: The ID of the memory to delete (returned by memory_find).
        collection: Collection containing the memory.
    """
    col_name = collection or config.DEFAULT_COLLECTION
    if not backend.delete(col_name, doc_id):
        return f"No memory with ID '{doc_id}' found in '{col_name}'."
    return f"Deleted '{doc_id}' from '{col_name}'."


@mcp.tool()
def memory_update(
    doc_id: str,
    content: str,
    collection: str | None = None,
    tags: str | None = None,
    source: str | None = None,
) -> str:
    """Update an existing memory entry with new content.

    Args:
        doc_id: The ID of the memory to update.
        content: New content to replace the existing text.
        collection: Collection containing the memory.
        tags: New tags (replaces existing). Pass empty string to clear.
        source: New source attribution. Pass empty string to clear.
    """
    col_name = collection or config.DEFAULT_COLLECTION
    existing = backend.get(col_name, doc_id)
    if not existing:
        return f"No memory with ID '{doc_id}' found in '{col_name}'."

    # Preserve existing metadata, merge in updates
    metadata = {**existing["metadata"], "updated_at": datetime.now(timezone.utc).isoformat()}
    if tags is not None:
        metadata["tags"] = tags
    if source is not None:
        metadata["source"] = source

    embedding = embedder.embed(content)
    backend.update(col_name, doc_id, content, embedding, metadata)
    return f"Updated '{doc_id}' in '{col_name}'."


@mcp.tool()
def list_collections() -> str:
    """List all memory collections and their entry counts."""
    collections = backend.list_collections()
    if not collections:
        return "No collections yet. Use memory_store to create one."

    lines = [f"- {c['name']} ({c['count']} entries)" for c in collections]
    return "\n".join(lines)


@mcp.tool()
def create_collection(
    name: str,
    scope: str = "shared",
    description: str | None = None,
) -> str:
    """Create a new memory collection for organizing knowledge by topic.

    Args:
        name: Collection name (use kebab-case, e.g. 'project-notes').
        scope: Namespace scope — 'shared' (default, visible to all AIs) or an AI
               identifier like 'claude', 'gemini', 'codex' (private to that AI).
        description: What this collection is for.
    """
    from ember_memory.core.namespaces import resolve_collection_name
    full_name = resolve_collection_name(name, scope)
    backend.create_collection(full_name, dimension=embedder.dimension(), description=description)
    return f"Collection '{full_name}' created (scope: {scope})."


@mcp.tool()
def delete_collection(name: str, confirm: bool = False) -> str:
    """Delete an entire memory collection. This cannot be undone.

    Args:
        name: Collection name to delete.
        confirm: Must be True to delete a non-empty collection.
    """
    # Check count first
    count = backend.collection_count(name)
    if count > 0 and not confirm:
        return f"Collection '{name}' has {count} entries. Set confirm=True to delete."

    deleted = backend.delete_collection(name)
    if deleted == 0 and count == 0:
        return f"Collection '{name}' does not exist."
    return f"Collection '{name}' deleted ({deleted} entries removed)."


@mcp.tool()
def collection_stats(collection: str | None = None) -> str:
    """Get statistics about a memory collection.

    Args:
        collection: Collection name (default: general).
    """
    col_name = collection or config.DEFAULT_COLLECTION
    count = backend.collection_count(col_name)

    if count == 0:
        return f"Collection '{col_name}' is empty."

    entries = backend.collection_peek(col_name, limit=5)
    recent = []
    for entry in entries:
        meta = entry["metadata"]
        stored = meta.get("stored_at", meta.get("updated_at", "unknown"))
        preview = entry["content"][:80] + "..." if len(entry["content"]) > 80 else entry["content"]
        recent.append(f"  - {entry['id']} ({stored}): {preview}")

    return f"Collection: {col_name}\nEntries: {count}\nRecent samples:\n" + "\n".join(recent)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Starting Ember Memory — backend: {config.BACKEND}, data: {config.DATA_DIR}")
    mcp.run(transport="stdio")
