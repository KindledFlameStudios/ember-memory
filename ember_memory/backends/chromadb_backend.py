"""ChromaDB storage backend for Ember Memory."""

import chromadb
from ember_memory.backends.base import MemoryBackend


class ChromaBackend(MemoryBackend):
    """ChromaDB persistent storage backend."""

    def __init__(self, data_dir: str, embedding_fn):
        self._client = chromadb.PersistentClient(path=data_dir)
        self._embedding_fn = embedding_fn

    def _get_collection(self, name: str):
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def store(self, doc_id: str, content: str, metadata: dict, collection: str) -> int:
        col = self._get_collection(collection)
        col.add(ids=[doc_id], documents=[content], metadatas=[metadata])
        return col.count()

    def search(self, query: str, collection: str, n_results: int) -> list[dict]:
        col = self._get_collection(collection)
        count = col.count()
        if count == 0:
            return []

        results = col.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )

        out = []
        for i, doc in enumerate(results["documents"][0]):
            out.append({
                "id": results["ids"][0][i],
                "content": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
        return out

    def get(self, doc_id: str, collection: str) -> dict | None:
        col = self._get_collection(collection)
        result = col.get(ids=[doc_id])
        if not result["ids"]:
            return None
        return {
            "id": result["ids"][0],
            "content": result["documents"][0],
            "metadata": result["metadatas"][0] if result["metadatas"] else {},
        }

    def update(self, doc_id: str, content: str, metadata: dict, collection: str) -> bool:
        col = self._get_collection(collection)
        existing = col.get(ids=[doc_id])
        if not existing["ids"]:
            return False
        col.update(ids=[doc_id], documents=[content], metadatas=[metadata])
        return True

    def delete(self, doc_id: str, collection: str) -> bool:
        col = self._get_collection(collection)
        existing = col.get(ids=[doc_id])
        if not existing["ids"]:
            return False
        col.delete(ids=[doc_id])
        return True

    def list_collections(self) -> list[dict]:
        collections = self._client.list_collections()
        out = []
        for col_obj in collections:
            name = col_obj.name if hasattr(col_obj, 'name') else str(col_obj)
            col = self._client.get_collection(name)
            out.append({"name": name, "count": col.count()})
        return out

    def create_collection(self, name: str, description: str | None = None) -> None:
        metadata = {"hnsw:space": "cosine"}
        if description:
            metadata["description"] = description
        self._client.get_or_create_collection(
            name=name,
            embedding_function=self._embedding_fn,
            metadata=metadata,
        )

    def delete_collection(self, name: str) -> int:
        try:
            col = self._client.get_collection(name)
            count = col.count()
        except Exception:
            return 0
        self._client.delete_collection(name)
        return count

    def collection_count(self, collection: str) -> int:
        col = self._get_collection(collection)
        return col.count()

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        col = self._get_collection(collection)
        count = col.count()
        if count == 0:
            return []

        peek = col.peek(limit=min(limit, count))
        out = []
        for i, doc_id in enumerate(peek["ids"]):
            out.append({
                "id": doc_id,
                "content": peek["documents"][i],
                "metadata": peek["metadatas"][i] if peek["metadatas"] else {},
            })
        return out

    def upsert_batch(self, ids: list[str], contents: list[str],
                     metadatas: list[dict], collection: str) -> int:
        col = self._get_collection(collection)
        col.upsert(ids=ids, documents=contents, metadatas=metadatas)
        return len(ids)

    def get_by_metadata(self, collection: str, field: str, value: str) -> list[dict]:
        col = self._get_collection(collection)
        result = col.get(where={field: {"$eq": value}}, include=["documents", "metadatas"])
        out = []
        for i, doc_id in enumerate(result["ids"]):
            out.append({
                "id": doc_id,
                "content": result["documents"][i],
                "metadata": result["metadatas"][i] if result["metadatas"] else {},
            })
        return out
