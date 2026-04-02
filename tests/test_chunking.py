from ember_memory.ingest import chunk_markdown


def test_header_merged_with_content():
    md = "# Title\n\nSome real content here that is meaningful."
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert "# Title" in chunks[0]
    assert "meaningful" in chunks[0]


def test_header_only_merged_with_next():
    md = "# Just a Title\n---\n\n## Real Section\n\nThis has actual content worth embedding."
    chunks = chunk_markdown(md)
    assert all(len(c) > 50 for c in chunks)


def test_large_section_splits_at_paragraphs():
    md = "# Big Section\n\n" + "\n\n".join(
        [f"Paragraph {i} with enough text to be meaningful." for i in range(50)]
    )
    chunks = chunk_markdown(md, max_chunk=500)
    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)


def test_empty_content():
    assert chunk_markdown("") == []
    assert chunk_markdown("   ") == []


def test_no_headers_chunks_by_size():
    md = "Just plain text without any headers. " * 100
    chunks = chunk_markdown(md, max_chunk=500)
    assert len(chunks) >= 1
