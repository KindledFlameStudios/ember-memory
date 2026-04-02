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
MIN_CHUNK = 50
MIN_STANDALONE_CHUNK = 20


def _normalize_chunk(text: str) -> str:
    """Trim a chunk and collapse excessive blank lines."""
    cleaned = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _split_header(section: str) -> tuple[str, str]:
    """Return the top-level header line and body for a section, if present."""
    lines = section.split('\n', 1)
    first_line = lines[0].strip() if lines else ""
    if re.match(r'^#{1,2}\s+', first_line):
        body = lines[1].strip() if len(lines) > 1 else ""
        return first_line, body
    return "", section.strip()


def _strip_markdown_chrome(text: str) -> str:
    """Strip markdown syntax when measuring substantive body text."""
    plain = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)
    plain = re.sub(r'\*\*[^*]+\*\*:?\s*', '', plain)
    plain = re.sub(r'^---+$', '', plain, flags=re.MULTILINE)
    plain = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', plain)
    plain = re.sub(r'\s+', ' ', plain)
    return plain.strip()


def _actual_text_len(text: str) -> int:
    return len(_strip_markdown_chrome(text))


def _split_oversized_section(section: str, max_chunk: int, min_body: int) -> list[str]:
    """Split a large section at paragraph boundaries while preserving header context."""
    section = _normalize_chunk(section)
    if len(section) <= max_chunk:
        return [section]

    header_line, body = _split_header(section)
    paragraphs = [part.strip() for part in re.split(r'\n\n+', body if header_line else section) if part.strip()]
    if not paragraphs:
        return [section] if len(section.strip()) >= MIN_STANDALONE_CHUNK else []

    results = []
    current = header_line if header_line else ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if (
            len(candidate) > max_chunk
            and current
            and _actual_text_len(current) >= min_body
        ):
            results.append(_normalize_chunk(current))
            current = f"{header_line}\n\n{para}".strip() if header_line else para
            continue

        current = candidate

    if current.strip():
        results.append(_normalize_chunk(current))

    return [chunk for chunk in results if len(chunk.strip()) >= MIN_STANDALONE_CHUNK]


def chunk_markdown(content: str, max_chunk: int = MAX_CHUNK, min_body: int = MIN_CHUNK) -> list[str]:
    """Split markdown into meaningful chunks, merging headers with their content."""
    if not content:
        return []

    content = _normalize_chunk(content)
    if len(content) < min_body:
        return [content] if len(content) >= MIN_STANDALONE_CHUNK else []

    sections = re.split(r'(?=^#{1,2}\s)', content, flags=re.MULTILINE)
    chunks = []
    buffer = ""

    for section in sections:
        section = _normalize_chunk(section)
        if not section:
            continue

        _header, body = _split_header(section)
        body_to_measure = body if body else section
        if _actual_text_len(body_to_measure) < min_body:
            buffer = _normalize_chunk(f"{buffer}\n\n{section}" if buffer else section)
            continue

        if buffer:
            section = _normalize_chunk(f"{buffer}\n\n{section}")
            buffer = ""

        chunks.extend(_split_oversized_section(section, max_chunk=max_chunk, min_body=min_body))

    if buffer and len(buffer.strip()) >= MIN_STANDALONE_CHUNK:
        chunks.extend(_split_oversized_section(buffer, max_chunk=max_chunk, min_body=min_body))

    return [chunk for chunk in chunks if len(chunk.strip()) >= MIN_STANDALONE_CHUNK]


def _chunk_section(chunk: str, source_file: str) -> str:
    """Derive a section label from the first markdown header in a chunk."""
    for line in chunk.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^#{1,6}\s+', stripped):
            return stripped.lstrip('#').strip()
        break
    return source_file


def _build_documents(filepath: str, collection: str) -> tuple[str, list[dict]]:
    """Read a file and convert it into deterministic document records."""
    filename = os.path.basename(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    chunks = chunk_markdown(text)
    ingested_at = datetime.now(timezone.utc).isoformat()
    documents = []

    for chunk in chunks:
        content_hash = hashlib.md5(chunk.encode()).hexdigest()[:12]
        documents.append({
            "id": f"{filename}_{content_hash}",
            "content": chunk,
            "metadata": {
                "source_file": filename,
                "section": _chunk_section(chunk, filename),
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
