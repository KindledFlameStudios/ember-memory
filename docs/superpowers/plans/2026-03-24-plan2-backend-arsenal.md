# Ember Memory v2.0 — Plan 2: Backend Arsenal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 7 additional storage backends (Qdrant, LanceDB, SQLite-vec, Weaviate, Pinecone, Milvus, pgvector) + update the backend factory and setup.py extras. All backends implement the same v2 MemoryBackend interface from Plan 1.

**Architecture:** Each backend is a single file (~150-200 lines) implementing the abstract MemoryBackend interface. The backend factory resolves the configured name to the correct class. pip extras ensure users only install the dependencies they need.

**Tech Stack:** Python 3.10+, qdrant-client, lancedb, sqlite-vec, weaviate-client, pinecone-client, pymilvus, psycopg2, pytest

**Depends on:** Plan 1 (core/backends/base.py — v2 MemoryBackend interface)

**Spec:** `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md` — "Storage Backends" section

**Parallelization note:** Tasks 1-7 are completely independent. Each backend can be built by a separate agent simultaneously.

---

### Task 1: Qdrant Backend

**Files:**
- Create: `ember_memory/core/backends/qdrant_backend.py`
- Test: `tests/test_backend_qdrant.py`

- [ ] **Step 1: Write the failing test**

Test create_collection, insert with vectors, search returns similarity, get/delete/count. Use mocks for qdrant_client (don't require running server).

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement QdrantBackend**

Use qdrant_client. connect() creates QdrantClient (url or in-memory for testing). create_collection sets vector config with dimension. insert uses PointStruct. search uses query_points. Convert Qdrant scores to [0,1] similarity.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 2: LanceDB Backend

**Files:**
- Create: `ember_memory/core/backends/lancedb_backend.py`
- Test: `tests/test_backend_lancedb.py`

- [ ] **Step 1: Write the failing test**

Test using lancedb's embedded mode with tmp_path.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement LanceBackend**

Use lancedb. connect() opens local DB. Collections are tables. insert adds rows with vector column. search uses vector similarity via table.search(). Convert distances to [0,1] similarity.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 3: SQLite-vec Backend

**Files:**
- Create: `ember_memory/core/backends/sqlite_vec_backend.py`
- Test: `tests/test_backend_sqlite_vec.py`

- [ ] **Step 1: Write the failing test**

Test using tmp_path for SQLite file.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement SqliteVecBackend**

Use sqlite-vec extension. create_collection creates a virtual table. insert stores content in regular table + vector in vec table. search uses vec_distance_cosine. Manual join between metadata table and vec table.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 4: Weaviate Backend

**Files:**
- Create: `ember_memory/core/backends/weaviate_backend.py`
- Test: `tests/test_backend_weaviate.py`

- [ ] **Step 1: Write the failing test**

Mock weaviate_client. Test collection CRUD, insert with vectors, search.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement WeaviateBackend**

Use weaviate-client v4. connect() creates client (url + api_key or local embedded). Collections map to Weaviate classes. insert uses data_object with vector. search uses near_vector.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 5: Pinecone Backend

**Files:**
- Create: `ember_memory/core/backends/pinecone_backend.py`
- Test: `tests/test_backend_pinecone.py`

- [ ] **Step 1: Write the failing test**

Mock pinecone-client. Test namespace-based collections, upsert, query.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement PineconeBackend**

Use pinecone-client. Pinecone uses one index with namespaces for collections. connect() initializes Pinecone client + index. insert uses upsert with namespace. search uses query with namespace. Store content in metadata (Pinecone doesn't store documents natively).

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 6: Milvus Backend

**Files:**
- Create: `ember_memory/core/backends/milvus_backend.py`
- Test: `tests/test_backend_milvus.py`

- [ ] **Step 1: Write the failing test**

Mock pymilvus. Test collection CRUD, insert, search.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement MilvusBackend**

Use pymilvus. connect() establishes connection. Collections have schema (id, content, embedding, metadata fields). insert uses collection.insert. search uses collection.search with COSINE metric.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 7: pgvector Backend

**Files:**
- Create: `ember_memory/core/backends/pgvector_backend.py`
- Test: `tests/test_backend_pgvector.py`

- [ ] **Step 1: Write the failing test**

Mock psycopg2. Test table creation, insert, vector search.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement PgvectorBackend**

Use psycopg2 + pgvector extension. connect() establishes PostgreSQL connection, enables vector extension. Collections are tables with vector column. insert uses parameterized INSERT. search uses cosine distance operator (<=>).

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 8: Backend Factory + pip Extras

**Files:**
- Modify: `ember_memory/core/backends/loader.py` — add all 8 backends
- Create: `setup.py` or `pyproject.toml` — define pip extras
- Test: `tests/test_backend_loader.py`

- [ ] **Step 1: Write the failing test**

Test factory returns correct class for each backend name, raises ValueError for unknown.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update backend loader**

Add all 8 backends to the factory. Each import is lazy (inside the if branch) so missing dependencies only error when that specific backend is selected.

```python
def get_backend_v2(backend=None, **kwargs):
    backend = backend or config.BACKEND
    data_dir = kwargs.get("data_dir", config.DATA_DIR)

    if backend == "chromadb":
        from ember_memory.core.backends.chromadb_backend import ChromaBackendV2
        b = ChromaBackendV2(data_dir=data_dir); b.connect(); return b
    elif backend == "qdrant":
        from ember_memory.core.backends.qdrant_backend import QdrantBackend
        b = QdrantBackend(**kwargs); b.connect(); return b
    elif backend == "lancedb":
        from ember_memory.core.backends.lancedb_backend import LanceBackend
        b = LanceBackend(data_dir=data_dir); b.connect(); return b
    # ... etc for all 8
```

- [ ] **Step 4: Define pip extras in pyproject.toml**

```toml
[project.optional-dependencies]
qdrant = ["qdrant-client>=1.7"]
lancedb = ["lancedb>=0.4"]
sqlite-vec = ["sqlite-vec>=0.1"]
weaviate = ["weaviate-client>=4.0"]
pinecone = ["pinecone-client>=3.0"]
milvus = ["pymilvus>=2.3"]
pgvector = ["psycopg2-binary>=2.9"]
openai = ["openai>=1.0"]
google = ["google-generativeai>=0.3"]
all = ["qdrant-client", "lancedb", "sqlite-vec", "weaviate-client", "pinecone-client", "pymilvus", "psycopg2-binary"]
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

---

## Plan 2 Complete — What's Ready

After Plan 2, ember-memory supports:
- 8 storage backends total (ChromaDB + 7 new)
- Lazy imports — only the selected backend's dependency is required
- pip extras for clean dependency management
- Every backend passes the same test contract

**Independent of:** Plan 3 (Ember Engine)
**Required by:** Plan 4 (setup wizard needs to present backend options)
