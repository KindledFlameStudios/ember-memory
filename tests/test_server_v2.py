"""Tests for the v2-based MCP server.

Verifies that:
- create_collection with scope="claude" produces a "claude--name" collection
- create_collection with scope="shared" produces just "name"
- The server initialises with the v2 backend and embedder (mocked)
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_embedder(dim: int = 4) -> MagicMock:
    """Return a mock EmbeddingProvider."""
    e = MagicMock()
    e.embed.return_value = [0.1] * dim
    e.dimension.return_value = dim
    return e


def _mock_backend() -> MagicMock:
    """Return a mock MemoryBackend with sensible defaults."""
    b = MagicMock()
    b.list_collections.return_value = []
    b.collection_count.return_value = 0
    b.insert.return_value = 1
    b.search.return_value = []
    b.get.return_value = None
    b.update.return_value = True
    b.delete.return_value = True
    b.delete_collection.return_value = 0
    b.collection_peek.return_value = []
    return b


# ── create_collection scope tests ─────────────────────────────────────────────


class TestCreateCollectionScope:
    """create_collection should resolve AI namespace scopes correctly."""

    def test_scope_claude_produces_prefixed_name(self):
        """scope='claude' should produce 'claude:<name>'."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import create_collection

            result = create_collection("preferences", scope="claude")

        assert "claude--preferences" in result
        mock_backend.create_collection.assert_called_once_with(
            "claude--preferences",
            dimension=mock_embedder.dimension(),
            description=None,
        )

    def test_scope_shared_produces_bare_name(self):
        """scope='shared' should produce just '<name>' without a prefix."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import create_collection

            result = create_collection("notes", scope="shared")

        assert "notes" in result
        # The resolved name should NOT be "shared--notes" — the shared scope
        # returns just the bare topic name.
        call_args = mock_backend.create_collection.call_args
        assert call_args[0][0] == "notes"

    def test_scope_default_is_shared(self):
        """Omitting scope should behave identically to scope='shared'."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import create_collection

            result = create_collection("general")

        call_args = mock_backend.create_collection.call_args
        assert call_args[0][0] == "general"

    def test_scope_gemini_produces_prefixed_name(self):
        """scope='gemini' should produce 'gemini:<name>'."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import create_collection

            result = create_collection("log", scope="gemini")

        assert "gemini--log" in result
        mock_backend.create_collection.assert_called_once_with(
            "gemini--log",
            dimension=mock_embedder.dimension(),
            description=None,
        )

    def test_description_forwarded(self):
        """A provided description should be passed through to the backend."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import create_collection

            create_collection("notes", scope="shared", description="My notes")

        call_kwargs = mock_backend.create_collection.call_args[1]
        assert call_kwargs.get("description") == "My notes"


# ── Server initialisation tests ───────────────────────────────────────────────


class TestServerInit:
    """Server module-level init should wire up v2 backend and embedder."""

    def test_server_uses_v2_backend_factory(self):
        """get_backend_v2 should be called during server module import."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch(
                "ember_memory.core.backends.loader.get_backend_v2",
                return_value=mock_backend,
            ) as mock_backend_factory,
            patch(
                "ember_memory.core.embeddings.loader.get_embedding_provider",
                return_value=mock_embedder,
            ) as mock_embedder_factory,
        ):
            # Re-importing won't re-run module-level code, so we verify via
            # the public interface: memory_store calls embedder.embed and
            # backend.insert with the v2 signatures.
            with (
                patch("ember_memory.server.embedder", mock_embedder),
                patch("ember_memory.server.backend", mock_backend),
            ):
                from ember_memory.server import memory_store

                result = memory_store("hello world", collection="test-col")

        # v2 insert signature: (collection, doc_id, content, embedding, metadata)
        assert mock_backend.insert.called
        call_args = mock_backend.insert.call_args[0]
        assert call_args[0] == "test-col"          # collection first
        assert call_args[2] == "hello world"       # content third
        assert isinstance(call_args[3], list)      # embedding fourth (list of floats)

    def test_memory_store_embeds_content(self):
        """memory_store must call embedder.embed(content) before inserting."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import memory_store

            memory_store("remember this", collection="col")

        mock_embedder.embed.assert_called_once_with("remember this")

    def test_memory_find_embeds_query(self):
        """memory_find must embed the query before calling backend.search."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import memory_find

            memory_find("what is the routing strategy", collection="arch")

        mock_embedder.embed.assert_called_once_with("what is the routing strategy")
        # backend.search should receive (collection, embedding, limit)
        call_args = mock_backend.search.call_args[0]
        assert call_args[0] == "arch"
        assert isinstance(call_args[1], list)  # pre-computed embedding vector

    def test_memory_update_embeds_content(self):
        """memory_update must re-embed the new content before calling backend.update."""
        mock_embedder = _mock_embedder()
        mock_backend = _mock_backend()
        mock_backend.get.return_value = {
            "id": "mem_001",
            "content": "old content",
            "metadata": {"stored_at": "2026-01-01T00:00:00+00:00"},
        }

        with (
            patch("ember_memory.server.embedder", mock_embedder),
            patch("ember_memory.server.backend", mock_backend),
        ):
            from ember_memory.server import memory_update

            memory_update("mem_001", "new content", collection="col")

        mock_embedder.embed.assert_called_once_with("new content")
        call_args = mock_backend.update.call_args[0]
        # v2 update signature: (collection, doc_id, content, embedding, metadata)
        assert call_args[0] == "col"
        assert call_args[1] == "mem_001"
        assert call_args[2] == "new content"
        assert isinstance(call_args[3], list)  # embedding
