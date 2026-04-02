"""
Ember Memory — Ingestion Pipeline
===================================
Chunks and embeds markdown/text files into collections.
Splits on headers, stores with content-hash IDs for deduplication.

Usage:
    python -m ember_memory.ingest <directory>                    # Ingest all files
    python -m ember_memory.ingest <directory> --collection notes  # Into specific collection
    python -m ember_memory.ingest <directory> --sync              # Only new/changed files
    python -m ember_memory.ingest --rebuild <collection>          # Clear and re-ingest one collection
    python -m ember_memory.ingest --rebuild-all                   # Clear ALL (after model change)
"""

import os
import re
import sys
import hashlib
from datetime import datetime, timezone

from ember_memory import config
from ember_memory.core.backends.loader import get_backend_v2
from ember_memory.core.embeddings.loader import get_embedding_provider

# Chunk size limits in characters
MAX_CHUNK = 2000
MIN_CHUNK = 100


def chunk_markdown(text: str, source_file: str) -> list[dict]:
    """Split markdown into semantic chunks by headers."""
    chunks = []
    sections = re.split(r'^(#{1,3}\s+.+)$', text, flags=re.MULTILINE)

    current_header = source_file
    current_body = ""

    for part in sections:
        part = part.strip()
        if not part:
            continue

        if re.match(r'^#{1,3}\s+', part):
            if current_body.strip() and len(current_body.strip()) >= MIN_CHUNK:
                chunks.extend(_split_large_chunk(current_body.strip(), current_header, source_file))
            current_header = part.lstrip('#').strip()
            current_body = ""
        else:
            current_body += "\n" + part

    if current_body.strip() and len(current_body.strip()) >= MIN_CHUNK:
        chunks.extend(_split_large_chunk(current_body.strip(), current_header, source_file))

    return chunks


def _split_large_chunk(text: str, header: str, source: str) -> list[dict]:
    """Split chunks that exceed MAX_CHUNK by paragraphs."""
    if len(text) <= MAX_CHUNK:
        return [{"content": f"[{header}]\n{text}", "header": header, "source": source}]

    paragraphs = re.split(r'\n\n+', text)
    results = []
    current = ""
    part_num = 1

    for para in paragraphs:
        if len(current) + len(para) > MAX_CHUNK and current:
            results.append({
                "content": f"[{header} (part {part_num})]\n{current.strip()}",
                "header": f"{header} (part {part_num})",
                "source": source,
            })
            part_num += 1
            current = para
        else:
            current += "\n\n" + para if current else para

    if current.strip() and len(current.strip()) >= MIN_CHUNK:
        suffix = f" (part {part_num})" if part_num > 1 else ""
        results.append({
            "content": f"[{header}{suffix}]\n{current.strip()}",
            "header": f"{header}{suffix}",
            "source": source,
        })

    return results


def _build_documents(filepath: str, collection: str) -> tuple[str, list[dict]]:
    """Read a file and convert it into deterministic document records."""
    filename = os.path.basename(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    chunks = chunk_markdown(text, filename)
    ingested_at = datetime.now(timezone.utc).isoformat()
    documents = []

    for chunk in chunks:
        content_hash = hashlib.md5(chunk["content"].encode()).hexdigest()[:12]
        documents.append({
            "id": f"{filename}_{content_hash}",
            "content": chunk["content"],
            "metadata": {
                "source_file": filename,
                "section": chunk["header"],
                "collection": collection,
                "ingested_at": ingested_at,
            },
        })

    return filename, documents


def _embed_documents(documents: list[dict], embedder, first_embedding: list[float] | None = None) -> list[list[float]]:
    """Embed all document content before handing vectors to the backend."""
    if not documents:
        return []

    if first_embedding is None:
        return embedder.embed_batch([doc["content"] for doc in documents])

    if len(documents) == 1:
        return [first_embedding]

    remaining = embedder.embed_batch([doc["content"] for doc in documents[1:]])
    return [first_embedding, *remaining]


def _file_already_ingested(collection: str, filename: str, documents: list[dict], backend, probe_hits: list[dict]) -> bool:
    """Return True when every current content-hash ID already exists."""
    if not documents or not probe_hits:
        return False

    for doc in documents:
        stored = backend.get(collection, doc["id"])
        if stored is None:
            return False
        if stored.get("metadata", {}).get("source_file") != filename:
            return False

    return True


def ingest_file(filepath: str, collection: str, backend, embedder, sync: bool = False, verbose: bool = True) -> tuple[int, bool]:
    """Chunk, embed, and store a single file into a collection."""
    filename, documents = _build_documents(filepath, collection)

    if not documents:
        if verbose:
            print(f"  Skipped {filename} — no chunks generated")
        return 0, False

    first_embedding = None
    if sync and backend.collection_count(collection) > 0:
        first_embedding = embedder.embed(documents[0]["content"])
        probe_hits = backend.search(
            collection=collection,
            query_embedding=first_embedding,
            limit=1,
            filters={"source_file": filename},
        )
        if _file_already_ingested(collection, filename, documents, backend, probe_hits):
            if verbose:
                print(f"  {filename} — unchanged, skipping")
            return 0, True

    embeddings = _embed_documents(documents, embedder, first_embedding=first_embedding)
    inserted = 0
    updated = 0

    for doc, embedding in zip(documents, embeddings):
        if backend.get(collection, doc["id"]) is None:
            backend.insert(collection, doc["id"], doc["content"], embedding, doc["metadata"])
            inserted += 1
        else:
            backend.update(collection, doc["id"], doc["content"], embedding, doc["metadata"])
            updated += 1

    if verbose:
        suffix = ""
        if inserted and updated:
            suffix = f" ({inserted} inserted, {updated} refreshed)"
        elif updated and not inserted:
            suffix = " (refreshed)"
        print(f"  {filename} -> {collection}: {len(documents)} chunks{suffix}")

    return len(documents), False


def _collection_from_dir(filepath: str, base_dir: str, default: str) -> str:
    """Derive collection name from directory structure.

    Files in subdirectories use the subdirectory name as collection.
    Files in the root use the default collection name.
    """
    rel = os.path.relpath(os.path.dirname(filepath), base_dir)
    if rel == "." or not rel:
        return default
    # Use first directory level as collection, kebab-case
    first_dir = rel.split(os.sep)[0]
    return re.sub(r'[^a-zA-Z0-9-]', '-', first_dir.lower()).strip('-')


def ingest_directory(directory: str, collection: str | None = None,
                     sync: bool = False, verbose: bool = True) -> None:
    """Ingest all markdown/text files from a directory."""
    backend = get_backend_v2()
    embedder = get_embedding_provider()

    default_collection = collection or config.DEFAULT_COLLECTION
    total_chunks = 0
    total_files = 0
    skipped_files = 0
    ensured_collections = set()

    if verbose:
        print(f"Ingesting from: {directory}")
        print(f"Storage: {config.DATA_DIR}")
        print(f"Model: {config.EMBEDDING_MODEL}")
        if sync:
            print("Mode: sync (only new/changed files)")
        print("---")

    for root, _dirs, files in os.walk(directory):
        for filename in sorted(files):
            if not filename.endswith(('.md', '.txt')):
                continue

            filepath = os.path.join(root, filename)
            col_name = collection or _collection_from_dir(filepath, directory, default_collection)

            if col_name not in ensured_collections:
                backend.create_collection(col_name, dimension=embedder.dimension())
                ensured_collections.add(col_name)

            count, skipped = ingest_file(
                filepath,
                col_name,
                backend,
                embedder,
                sync=sync,
                verbose=verbose,
            )
            if skipped:
                skipped_files += 1
                continue

            total_chunks += count
            total_files += 1

    if verbose:
        print("---")
        msg = f"Done: {total_files} files -> {total_chunks} chunks"
        if skipped_files:
            msg += f", skipped {skipped_files} unchanged"
        print(msg)

        print("\nCollections:")
        for c in backend.list_collections():
            print(f"  {c['name']}: {c['count']} entries")


def rebuild_collection(collection: str) -> None:
    """Delete and rebuild a collection. Requires source directory as second arg."""
    backend = get_backend_v2()

    deleted = backend.delete_collection(collection)
    print(f"Deleted collection '{collection}' ({deleted} entries)")
    print("Re-ingest with: python -m ember_memory.ingest <directory> --collection " + collection)


def rebuild_all() -> None:
    """Delete ALL collections. Used after switching embedding models."""
    backend = get_backend_v2()

    collections = backend.list_collections()
    if not collections:
        print("No collections to rebuild.")
        return

    print(f"Deleting {len(collections)} collections...")
    for c in collections:
        count = c.get("count", 0)
        backend.delete_collection(c["name"])
        print(f"  Deleted '{c['name']}' ({count} entries)")

    print("\nAll collections cleared. Re-ingest your content:")
    print("  python -m ember_memory.ingest <directory>")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)

    if args[0] == "--rebuild-all":
        confirm = input("This will DELETE all memory collections. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            return
        rebuild_all()
        return

    if args[0] == "--rebuild":
        if len(args) < 2:
            print("Error: --rebuild requires a collection name")
            sys.exit(1)
        rebuild_collection(args[1])
        return

    directory = args[0]
    if not os.path.isdir(directory):
        print(f"Error: not a directory: {directory}")
        sys.exit(1)

    collection = None
    sync = False

    i = 1
    while i < len(args):
        if args[i] == "--collection" and i + 1 < len(args):
            collection = args[i + 1]
            i += 2
        elif args[i] == "--sync":
            sync = True
            i += 1
        else:
            print(f"Unknown argument: {args[i]}")
            sys.exit(1)

    ingest_directory(directory, collection=collection, sync=sync)


if __name__ == "__main__":
    main()
