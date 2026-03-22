"""
Ember Memory — MCP Server
==========================
Persistent semantic memory for Claude Code via Model Context Protocol.
Provides tools to store, search, update, and manage knowledge across sessions.
"""

import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from ember_memory import config
from ember_memory.backends import get_backend

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ember-memory")

# ── Init ─────────────────────────────────────────────────────────────────────

mcp = FastMCP("ember-memory", instructions="""
Persistent semantic memory system. Use this to store and retrieve knowledge
across sessions — architecture decisions, project context, debugging insights,
anything worth remembering. Collections organize memories by topic.
""")

backend = get_backend(
    backend=config.BACKEND,
    data_dir=config.DATA_DIR,
    embedding_provider=config.EMBEDDING_PROVIDER,
    embedding_model=config.EMBEDDING_MODEL,
    ollama_url=config.OLLAMA_URL,
)


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

    count = backend.store(doc_id, content, metadata, col_name)
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
        collection: Collection to search (default: general). Use '*' to search all.
        n_results: Max results to return (default: 10).
        tags_filter: Only return entries containing this tag (e.g. 'backend').
    """
    n = n_results or config.SEARCH_LIMIT

    if collection == "*":
        all_results = []
        for col_info in backend.list_collections():
            col_name = col_info["name"]
            try:
                results = backend.search(query, col_name, n)
                for r in results:
                    if tags_filter and tags_filter not in r["metadata"].get("tags", ""):
                        continue
                    r["_collection"] = col_name
                    all_results.append(r)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("distance", 999))
        all_results = all_results[:n]

        if not all_results:
            return "No memories found across any collection."

        output = []
        for r in all_results:
            score = f" (similarity: {1 - r['distance']:.3f})" if r.get("distance") is not None else ""
            tags = f" [tags: {r['metadata'].get('tags', '')}]" if r["metadata"].get("tags") else ""
            source = f" [source: {r['metadata'].get('source', '')}]" if r["metadata"].get("source") else ""
            output.append(f"**[{r['_collection']}]**{score}{tags}{source}\n{r['content']}")
        return "\n\n---\n\n".join(output)

    col_name = collection or config.DEFAULT_COLLECTION
    results = backend.search(query, col_name, n)

    if not results:
        return f"No matching memories found in '{col_name}'."

    output = []
    for r in results:
        if tags_filter and tags_filter not in r["metadata"].get("tags", ""):
            continue
        score = f" (similarity: {1 - r['distance']:.3f})" if r.get("distance") is not None else ""
        tags = f" [tags: {r['metadata'].get('tags', '')}]" if r["metadata"].get("tags") else ""
        source = f" [source: {r['metadata'].get('source', '')}]" if r["metadata"].get("source") else ""
        output.append(f"**{r['id']}**{score}{tags}{source}\n{r['content']}")

    if not output:
        return f"No matching memories found in '{col_name}'."

    return f"Found {len(output)} results in '{col_name}':\n\n" + "\n\n---\n\n".join(output)


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
    if not backend.delete(doc_id, col_name):
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
    existing = backend.get(doc_id, col_name)
    if not existing:
        return f"No memory with ID '{doc_id}' found in '{col_name}'."

    # Preserve existing metadata, merge in updates
    metadata = {**existing["metadata"], "updated_at": datetime.now(timezone.utc).isoformat()}
    if tags is not None:
        metadata["tags"] = tags
    if source is not None:
        metadata["source"] = source

    backend.update(doc_id, content, metadata, col_name)
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
    description: str | None = None,
) -> str:
    """Create a new memory collection for organizing knowledge by topic.

    Args:
        name: Collection name (use kebab-case, e.g. 'project-notes').
        description: What this collection is for.
    """
    backend.create_collection(name, description)
    return f"Collection '{name}' ready."


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
