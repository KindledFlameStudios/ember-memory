"""
Tests for ember_memory.core.namespaces — AI namespace resolution.
"""

import pytest
from ember_memory.core.namespaces import (
    KNOWN_AI_IDS,
    SHARED_NAMESPACE,
    get_visible_collections,
    parse_collection_name,
    resolve_collection_name,
)


# ---------------------------------------------------------------------------
# resolve_collection_name
# ---------------------------------------------------------------------------

class TestResolveCollectionName:
    def test_default_scope_returns_bare_topic(self):
        assert resolve_collection_name("notes") == "notes"

    def test_shared_scope_returns_bare_topic(self):
        assert resolve_collection_name("notes", scope="shared") == "notes"

    def test_ai_scope_prefixes_topic(self):
        assert resolve_collection_name("preferences", scope="claude") == "claude--preferences"

    def test_gemini_scope_prefixes_topic(self):
        assert resolve_collection_name("log", scope="gemini") == "gemini--log"

    def test_codex_scope_prefixes_topic(self):
        assert resolve_collection_name("tasks", scope="codex") == "codex--tasks"

    def test_topic_with_special_chars(self):
        # Colons inside the topic itself should survive untouched.
        assert resolve_collection_name("my:topic", scope="claude") == "claude--my:topic"

    def test_empty_topic_shared(self):
        assert resolve_collection_name("", scope="shared") == ""

    def test_empty_topic_ai(self):
        assert resolve_collection_name("", scope="claude") == "claude--"


# ---------------------------------------------------------------------------
# parse_collection_name
# ---------------------------------------------------------------------------

class TestParseCollectionName:
    def test_unprefixed_is_shared(self):
        assert parse_collection_name("notes") == ("shared", "notes")

    def test_shared_prefix_stripped(self):
        assert parse_collection_name("shared--notes") == ("shared", "notes")

    def test_claude_prefix(self):
        assert parse_collection_name("claude--preferences") == ("claude", "preferences")

    def test_gemini_prefix(self):
        assert parse_collection_name("gemini--log") == ("gemini", "log")

    def test_codex_prefix(self):
        assert parse_collection_name("codex--tasks") == ("codex", "tasks")

    def test_unknown_prefix_treated_as_shared(self):
        # Full name becomes the topic; namespace is shared.
        assert parse_collection_name("unknown--stuff") == ("shared", "unknown--stuff")

    def test_unknown_prefix_no_split_ambiguity(self):
        # Even a multi-colon name with an unknown prefix stays as shared.
        assert parse_collection_name("bot:a:b") == ("shared", "bot:a:b")

    def test_known_ai_with_sub_colon_in_topic(self):
        # Only the first colon is used as the delimiter.
        assert parse_collection_name("claude--a:b") == ("claude", "a:b")

    def test_empty_string_is_shared(self):
        assert parse_collection_name("") == ("shared", "")

    def test_shared_prefix_empty_topic(self):
        assert parse_collection_name("shared--") == ("shared", "")

    def test_known_ai_ids_constant(self):
        # Verify the expected IDs are present.
        assert {"claude", "gemini", "codex"} == set(KNOWN_AI_IDS)

    def test_shared_namespace_constant(self):
        assert SHARED_NAMESPACE == "shared"


# ---------------------------------------------------------------------------
# get_visible_collections
# ---------------------------------------------------------------------------

class TestGetVisibleCollections:
    # Fixture data reused across tests.
    MIXED = [
        "notes",           # unprefixed → shared
        "shared--facts",    # explicit shared
        "claude--prefs",    # claude-private
        "gemini--log",      # gemini-private
        "codex--tasks",     # codex-private
        "unknown--stuff",   # unknown prefix → shared
    ]

    def test_claude_sees_shared_and_own(self):
        result = get_visible_collections(self.MIXED, ai_id="claude")
        assert result == ["notes", "shared--facts", "claude--prefs", "unknown--stuff"]

    def test_gemini_sees_shared_and_own(self):
        result = get_visible_collections(self.MIXED, ai_id="gemini")
        assert result == ["notes", "shared--facts", "gemini--log", "unknown--stuff"]

    def test_codex_sees_shared_and_own(self):
        result = get_visible_collections(self.MIXED, ai_id="codex")
        assert result == ["notes", "shared--facts", "codex--tasks", "unknown--stuff"]

    def test_claude_excludes_other_ai_collections(self):
        result = get_visible_collections(self.MIXED, ai_id="claude")
        assert "gemini--log" not in result
        assert "codex--tasks" not in result

    def test_none_ai_id_returns_only_shared(self):
        result = get_visible_collections(self.MIXED, ai_id=None)
        assert result == ["notes", "shared--facts", "unknown--stuff"]
        assert "claude--prefs" not in result
        assert "gemini--log" not in result
        assert "codex--tasks" not in result

    def test_empty_collection_list(self):
        assert get_visible_collections([], ai_id="claude") == []

    def test_empty_collection_list_none_ai(self):
        assert get_visible_collections([], ai_id=None) == []

    def test_all_shared_visible_to_all(self):
        shared_only = ["alpha", "shared--beta", "unknown--gamma"]
        assert get_visible_collections(shared_only, ai_id="claude") == shared_only
        assert get_visible_collections(shared_only, ai_id="gemini") == shared_only
        assert get_visible_collections(shared_only, ai_id=None) == shared_only

    def test_all_private_hidden_to_others(self):
        private = ["claude--a", "gemini--b", "codex--c"]
        assert get_visible_collections(private, ai_id="claude") == ["claude--a"]
        assert get_visible_collections(private, ai_id="gemini") == ["gemini--b"]
        assert get_visible_collections(private, ai_id="codex") == ["codex--c"]
        assert get_visible_collections(private, ai_id=None) == []

    def test_unknown_ai_id_sees_only_shared(self):
        # An AI not in KNOWN_AI_IDS still gets shared collections.
        result = get_visible_collections(self.MIXED, ai_id="newbot")
        assert result == ["notes", "shared--facts", "unknown--stuff"]

    def test_order_preserved(self):
        ordered = ["shared--z", "claude--a", "notes", "gemini--b"]
        result = get_visible_collections(ordered, ai_id="claude")
        assert result == ["shared--z", "claude--a", "notes"]

    def test_duplicate_collections_preserved(self):
        dupes = ["notes", "notes", "claude--x", "claude--x"]
        result = get_visible_collections(dupes, ai_id="claude")
        assert result == ["notes", "notes", "claude--x", "claude--x"]
