# Ember Memory v2.0 — Plan 1: Core Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor ember-memory's core to decouple embedding from storage, add OpenAI/Google embedding providers, implement AI namespace resolution, and create the unified search layer with timeout contract.

**Architecture:** The current v1 tightly couples ChromaDB's embedding functions with storage. V2 decouples them: a new EmbeddingProvider abstract class handles embedding independently, backends receive pre-computed vectors, and a new search.py coordinates embedding, backend, and filtering. This enables any backend to work with any embedding provider.

**Tech Stack:** Python 3.10+, ChromaDB, Ollama, OpenAI SDK, Google GenAI SDK, MCP (FastMCP), pytest

**Spec:** `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md`

**Plan sequence (4 plans total):**
- **Plan 1 (this):** Core Foundation — interfaces, embeddings, namespaces, search.py
- **Plan 2:** Backend Arsenal — 7 additional backends (Qdrant, LanceDB, SQLite-vec, Weaviate, Pinecone, Milvus, pgvector)
- **Plan 3:** Ember Engine — heat maps, co-occurrence, decay, composite scoring
- **Plan 4:** CLI Integrations + Controller + Ship — Gemini/Codex hooks, controller refactor, tray, README

Plans 2 and 3 can run in parallel after Plan 1. Plan 4 depends on all three.

---

### Task 1: Embedding Provider Abstract Interface

**Files:**
- Create: `ember_memory/core/__init__.py`
- Create: `ember_memory/core/embeddings/__init__.py`
- Create: `ember_memory/core/embeddings/base.py`
- Test: `tests/test_embedding_base.py`

- [ ] **Step 1: Create core directory structure**

```bash
mkdir -p ember_memory/core/embeddings
mkdir -p ember_memory/core/backends
mkdir -p tests
touch ember_memory/core/__init__.py
touch ember_memory/core/embeddings/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_embedding_base.py
from ember_memory.core.embeddings.base import EmbeddingProvider
import pytest

def test_interface_is_abstract():
    with pytest.raises(TypeError):
        EmbeddingProvider()

def test_interface_defines_required_methods():
    class Incomplete(EmbeddingProvider):
        pass
    with pytest.raises(TypeError):
        Incomplete()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd ~/ember-memory && python -m pytest tests/test_embedding_base.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 4: Implement the abstract interface**

```python
# ember_memory/core/embeddings/base.py
"""Abstract base class for embedding providers."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Interface for all embedding providers. Decoupled from storage in v2."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns a vector."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns a list of vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension (e.g., 1024 for bge-m3)."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is reachable and working."""
        ...
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd ~/ember-memory && python -m pytest tests/test_embedding_base.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ember_memory/core/ tests/test_embedding_base.py
git commit -m "feat: add EmbeddingProvider abstract interface"
```

---

### Task 2: Ollama Embedding Provider

**Files:**
- Create: `ember_memory/core/embeddings/ollama.py`
- Test: `tests/test_embedding_ollama.py`

- [ ] **Step 1: Write the failing test**

Tests use mocks for Ollama API. Test that OllamaProvider implements the interface, returns correct dimensions, and handles health checks.

```python
# tests/test_embedding_ollama.py
import pytest
from unittest.mock import patch, MagicMock
from ember_memory.core.embeddings.ollama import OllamaProvider


def test_implements_interface():
    from ember_memory.core.embeddings.base import EmbeddingProvider
    assert issubclass(OllamaProvider, EmbeddingProvider)


def test_dimension_is_1024():
    provider = OllamaProvider(url="http://localhost:11434/api/embed", model="bge-m3")
    assert provider.dimension() == 1024


@patch("ember_memory.core.embeddings.ollama.requests.post")
def test_embed_returns_vector(mock_post):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"embeddings": [[0.1] * 1024]}
    mock_post.return_value = mock_response

    provider = OllamaProvider(url="http://localhost:11434/api/embed", model="bge-m3")
    result = provider.embed("test text")
    assert len(result) == 1024


@patch("ember_memory.core.embeddings.ollama.requests.post")
def test_embed_batch(mock_post):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"embeddings": [[0.1] * 1024, [0.2] * 1024]}
    mock_post.return_value = mock_response

    provider = OllamaProvider(url="http://localhost:11434/api/embed", model="bge-m3")
    results = provider.embed_batch(["text one", "text two"])
    assert len(results) == 2


@patch("ember_memory.core.embeddings.ollama.requests.get")
def test_health_check_true(mock_get):
    mock_get.return_value = MagicMock(ok=True)
    provider = OllamaProvider(url="http://localhost:11434/api/embed", model="bge-m3")
    assert provider.health_check() is True


@patch("ember_memory.core.embeddings.ollama.requests.get")
def test_health_check_false(mock_get):
    mock_get.side_effect = ConnectionError("refused")
    provider = OllamaProvider(url="http://localhost:11434/api/embed", model="bge-m3")
    assert provider.health_check() is False
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement Ollama provider**

Use requests to hit Ollama's /api/embed endpoint. Map known models to dimensions. Derive base URL for health check.

- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**

---

### Task 3: OpenAI Embedding Provider

**Files:**
- Create: `ember_memory/core/embeddings/openai_provider.py`
- Test: `tests/test_embedding_openai.py`

- [ ] **Step 1: Write the failing test**

Test interface compliance, dimension mapping for text-embedding-3-small (1536) and text-embedding-3-large (3072), mock API calls, and API key validation.

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement OpenAI provider**

Use requests to hit OpenAI's /v1/embeddings endpoint. Require API key. Map models to dimensions.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 4: Google Embedding Provider

**Files:**
- Create: `ember_memory/core/embeddings/google_provider.py`
- Test: `tests/test_embedding_google.py`

- [ ] **Step 1: Write the failing test**

Test interface compliance, dimension (768 for text-embedding-004), mock API calls, API key validation.

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement Google provider**

Use requests to hit Google's embedContent / batchEmbedContents endpoints. Require API key.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 5: Embedding Factory + Config Updates

**Files:**
- Create: `ember_memory/core/embeddings/loader.py`
- Modify: `ember_memory/config.py` — add new config entries
- Test: `tests/test_embedding_loader.py`

- [ ] **Step 1: Write the failing test**

Test that the factory returns the correct provider type for "ollama", "openai", "google", and raises ValueError for unknown.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement embedding factory**

Resolve provider name to class. Pass config values as defaults, allow kwargs overrides.

- [ ] **Step 4: Add config entries to config.py**

Add: OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL, GOOGLE_API_KEY, GOOGLE_EMBEDDING_MODEL, RETRIEVE_TIMEOUT_MS, WEIGHT_SIMILARITY, WEIGHT_HEAT, WEIGHT_CONNECTION, WEIGHT_DECAY, CONTEXT_TAG.

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

---

### Task 6: Backend Interface v2 (Vector-Based)

**Files:**
- Create: `ember_memory/core/backends/base.py`
- Create: `ember_memory/core/backends/__init__.py`
- Test: `tests/test_backend_base.py`

Key change: backends receive pre-computed embedding vectors, not raw text.

- [ ] **Step 1: Write the failing test**

Test that MemoryBackend is abstract and requires all methods.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement v2 abstract interface**

Methods: connect, create_collection(name, dimension), insert(collection, doc_id, content, embedding, metadata), insert_batch, search(collection, query_embedding, limit, filters), get, update, delete, list_collections, collection_count, collection_peek.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 7: Refactor ChromaDB Backend to v2 Interface

**Files:**
- Create: `ember_memory/core/backends/chromadb_backend.py`
- Create: `ember_memory/core/backends/loader.py`
- Test: `tests/test_backend_chromadb.py`

- [ ] **Step 1: Write the failing test**

Test create_collection, insert with pre-computed vectors, search returns similarity scores, get by ID, delete, collection_count. Use tmp_path fixture for isolated ChromaDB.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement ChromaDB v2 backend**

Key change: pass embeddings directly to ChromaDB instead of letting ChromaDB call the embedding function. Use `col.add(embeddings=[...])` and `col.query(query_embeddings=[...])`.

Convert ChromaDB cosine distance [0,2] to similarity [0,1] via `max(0, 1 - distance)`.

- [ ] **Step 4: Implement v2 backend loader**

Factory that resolves "chromadb" to ChromaBackendV2. Will be extended in Plan 2 for additional backends.

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

---

### Task 8: Namespace Resolution

**Files:**
- Create: `ember_memory/core/namespaces.py`
- Test: `tests/test_namespaces.py`

- [ ] **Step 1: Write the failing test**

Test resolve_collection_name (shared vs AI-prefixed), parse_collection_name (extract namespace + topic), get_visible_collections (filter by ai_id: include shared + own, exclude other AIs).

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement namespace resolution**

Three functions: resolve_collection_name(topic, scope), parse_collection_name(name), get_visible_collections(all_collections, ai_id). Known AI IDs: claude, gemini, codex.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 9: Unified Search Layer (search.py)

**Files:**
- Create: `ember_memory/core/search.py`
- Test: `tests/test_search.py`

Central coordinator: embed query -> search backend -> filter namespaces -> return results. Engine scoring integration point for Plan 3.

- [ ] **Step 1: Write the failing test**

Test retrieve() returns RetrievalResult objects, filters by namespace, respects limit, handles empty collections, returns empty on no backend.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement search.py**

Define RetrievalResult dataclass (id, content, collection, similarity, composite_score, metadata). Implement retrieve(prompt, ai_id, backend, embedder, limit, threshold). Steps: list collections -> filter by namespace -> embed query -> search each visible collection -> merge + sort by composite_score -> limit.

composite_score = similarity for now (Engine overrides in Plan 3).

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 10: Update MCP Server for v2

**Files:**
- Modify: `ember_memory/server.py`
- Test: `tests/test_server_tools.py`

- [ ] **Step 1: Write test for namespace-aware create_collection**

- [ ] **Step 2: Update server.py init to use v2 backend + embedder**

Replace `get_backend()` with `get_backend_v2()`. Create `embedder` via `get_embedding_provider()`.

- [ ] **Step 3: Update create_collection tool to accept scope parameter**

Add scope param: "shared", "claude", "gemini", "codex". Use resolve_collection_name to build full name.

- [ ] **Step 4: Update memory_store to embed content before calling backend.insert()**

Call `embedder.embed(content)` then pass vector to `backend.insert()`.

- [ ] **Step 5: Update memory_find to embed query before searching**

Call `embedder.embed(query)` then pass vector to `backend.search()`.

- [ ] **Step 6: Update all remaining tools (update, get, delete, etc.) for v2 interface**

- [ ] **Step 7: Run full test suite**

```bash
cd ~/ember-memory && python -m pytest tests/ -v
```

- [ ] **Step 8: Commit**

---

### Task 11: Update Hook for v2

**Files:**
- Modify: `ember_memory/hook.py`

- [ ] **Step 1: Refactor hook to use search.retrieve()**

Replace direct ChromaDB access with:
```python
from ember_memory.core.search import retrieve
from ember_memory.core.backends.loader import get_backend_v2
from ember_memory.core.embeddings.loader import get_embedding_provider
```

- [ ] **Step 2: Add ai_id parameter**

Default to "claude" for now (parameterized per-CLI in Plan 4):
```python
AI_ID = os.environ.get("EMBER_AI_ID", "claude")
```

- [ ] **Step 3: Update output formatting to use RetrievalResult fields**

- [ ] **Step 4: Test manually**

```bash
echo '{"prompt": "test query about architecture"}' | python3 ember_memory/hook.py
```

- [ ] **Step 5: Commit**

---

### Task 12: Integration Cleanup + Backward Compatibility

**Files:**
- Create: `integrations/claude_code/` (move plugin files)
- Deprecate: old `ember_memory/embeddings/`, old `ember_memory/backends/`

- [ ] **Step 1: Create integration directory and move Claude Code plugin files**

```bash
mkdir -p integrations/claude_code
cp .claude-plugin/plugin.json integrations/claude_code/
cp hooks.json integrations/claude_code/
cp .mcp.json integrations/claude_code/
```

- [ ] **Step 2: Add deprecation warnings to old modules**

Old `ember_memory/embeddings/loader.py` and `ember_memory/backends/loader.py` get deprecation warnings that re-export from new locations.

- [ ] **Step 3: Keep .claude-plugin/ as symlink or redirect for existing installs**

- [ ] **Step 4: Run full test suite**

```bash
cd ~/ember-memory && python -m pytest tests/ -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: complete Plan 1 — core foundation with multi-provider + namespaces"
```

---

## Plan 1 Complete — What's Ready

After Plan 1, ember-memory has:
- Decoupled embedding from storage (any provider + any backend)
- Three embedding providers (Ollama, OpenAI, Google)
- v2 backend interface ready for 7 new backends (Plan 2)
- AI namespace resolution (shared + per-AI collections)
- Unified search layer ready for Engine scoring (Plan 3)
- Updated MCP tools with namespace scope
- Updated hook using unified search with ai_id

**Next plans (can run in parallel):**
- **Plan 2:** Backend Arsenal — Qdrant, LanceDB, SQLite-vec, Weaviate, Pinecone, Milvus, pgvector
- **Plan 3:** Ember Engine — heat maps, co-occurrence, decay, composite scoring, SQLite state

Both depend on Plan 1 but are independent of each other.
