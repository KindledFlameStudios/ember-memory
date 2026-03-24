"""
AI namespace resolution for multi-CLI collection filtering.

Collections follow the convention:
  - "topic"           — shared (visible to all AIs)
  - "shared:topic"    — explicitly shared (same as above)
  - "{ai_id}:topic"   — private to that AI (e.g., "claude:preferences")

Known AI namespaces: claude, gemini, codex.
"""

from typing import Optional

# All recognized AI identifiers. Collections prefixed with one of these
# are considered private to that specific AI.
KNOWN_AI_IDS: frozenset[str] = frozenset({"claude", "gemini", "codex"})

# The reserved namespace for collections visible to every AI.
SHARED_NAMESPACE = "shared"


def resolve_collection_name(topic: str, scope: str = "shared") -> str:
    """Return the full collection name for a given topic and scope.

    Args:
        topic: The bare topic name (e.g., "preferences", "notes").
        scope: Either "shared" (default) or an AI identifier such as
               "claude", "gemini", or "codex".

    Returns:
        Just ``topic`` when scope is "shared"; "{scope}:{topic}" otherwise.

    Examples:
        >>> resolve_collection_name("notes")
        'notes'
        >>> resolve_collection_name("notes", scope="shared")
        'notes'
        >>> resolve_collection_name("preferences", scope="claude")
        'claude:preferences'
    """
    if scope == SHARED_NAMESPACE:
        return topic
    return f"{scope}:{topic}"


def parse_collection_name(name: str) -> tuple[str, str]:
    """Decompose a collection name into its (namespace, topic) parts.

    Rules:
      - Names that contain no ":" are unprefixed and belong to "shared".
      - Names prefixed with a known AI ID (e.g., "claude:") map to that
        AI's namespace.
      - Names prefixed with "shared:" map to the "shared" namespace.
      - Any other prefix (unknown) is also treated as "shared", with the
        full original name used as the topic.

    Args:
        name: A raw collection name, e.g., "notes", "shared:notes",
              "claude:preferences", or "unknown:whatever".

    Returns:
        A (namespace, topic) tuple where namespace is one of the
        KNOWN_AI_IDS or "shared".

    Examples:
        >>> parse_collection_name("notes")
        ('shared', 'notes')
        >>> parse_collection_name("shared:notes")
        ('shared', 'notes')
        >>> parse_collection_name("claude:preferences")
        ('claude', 'preferences')
        >>> parse_collection_name("unknown:stuff")
        ('shared', 'unknown:stuff')
    """
    if ":" not in name:
        return (SHARED_NAMESPACE, name)

    prefix, topic = name.split(":", 1)

    if prefix == SHARED_NAMESPACE or prefix in KNOWN_AI_IDS:
        namespace = SHARED_NAMESPACE if prefix == SHARED_NAMESPACE else prefix
        return (namespace, topic)

    # Unknown prefix — treat the whole name as a shared topic.
    return (SHARED_NAMESPACE, name)


def get_visible_collections(
    all_collections: list[str],
    ai_id: Optional[str] = None,
) -> list[str]:
    """Filter a collection list to those visible to a given AI.

    Visibility rules:
      - Shared collections (unprefixed or "shared:" prefixed) are always
        visible to every AI.
      - An AI-prefixed collection (e.g., "claude:*") is visible only to
        that specific AI.
      - Collections belonging to a *different* AI are excluded.
      - When ``ai_id`` is None, only shared collections are returned.

    Args:
        all_collections: The full list of collection names to filter.
        ai_id: The identifier of the requesting AI, or None to return
               only shared collections.

    Returns:
        A filtered list preserving the original order.

    Examples:
        >>> cols = ["notes", "shared:facts", "claude:prefs", "gemini:log"]
        >>> get_visible_collections(cols, ai_id="claude")
        ['notes', 'shared:facts', 'claude:prefs']
        >>> get_visible_collections(cols, ai_id=None)
        ['notes', 'shared:facts']
    """
    visible: list[str] = []

    for collection in all_collections:
        namespace, _topic = parse_collection_name(collection)

        if namespace == SHARED_NAMESPACE:
            # Shared collections are always included.
            visible.append(collection)
        elif ai_id is not None and namespace == ai_id:
            # This AI's own private collection.
            visible.append(collection)
        # else: another AI's private collection — skip.

    return visible
