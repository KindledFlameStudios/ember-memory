import json
from unittest.mock import patch

from ember_memory.core.search import RetrievalResult


def test_codex_hook_output_format():
    """Verify the hook outputs correct Codex lifecycle hook JSON."""
    mock_results = [
        RetrievalResult(
            id="doc1",
            content="test content",
            collection="notes",
            similarity=0.8,
            composite_score=0.85,
            metadata={},
        )
    ]

    with (
        patch("ember_memory.core.search.retrieve", return_value=mock_results) as mock_retrieve,
        patch("ember_memory.core.embeddings.loader.get_embedding_provider"),
        patch("ember_memory.core.backends.loader.get_backend_v2"),
        patch("sys.stdin") as mock_stdin,
        patch("builtins.print") as mock_print,
    ):
        mock_stdin.read.return_value = json.dumps(
            {
                "prompt": "test query",
                "session_id": "thread-123",
                "cwd": "/tmp/project",
                "hook_event_name": "UserPromptSubmit",
            }
        )

        import importlib
        import integrations.codex.hook as codex_hook

        importlib.reload(codex_hook)
        codex_hook.main()

        output = json.loads(mock_print.call_args[0][0])
        assert output["continue"] is True
        assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "ember-memory" in output["hookSpecificOutput"]["additionalContext"]
        assert mock_retrieve.call_args.kwargs["session_id"] == "codex-thread-123"


def test_codex_hook_empty_prompt_outputs_continue():
    with patch("sys.stdin") as mock_stdin, patch("builtins.print") as mock_print:
        mock_stdin.read.return_value = json.dumps({"prompt": ""})

        import importlib
        import integrations.codex.hook as codex_hook

        importlib.reload(codex_hook)
        codex_hook.main()

        output = json.loads(mock_print.call_args[0][0])
        assert output == {"continue": True}


def test_codex_session_scope_prefixes_raw_thread_id():
    import importlib
    import integrations.codex.hook as codex_hook

    importlib.reload(codex_hook)

    assert codex_hook._codex_session_scope("019d543a-d11f-7421-b007-db86f14bd1a9") == (
        "codex-019d543a-d11f-7421-b007-db86f14bd1a9"
    )
    assert codex_hook._codex_session_scope("codex-thread-123") == "codex-thread-123"


def test_codex_hook_logs_no_result_invocation(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBER_DATA_DIR", str(tmp_path))

    with (
        patch("ember_memory.core.search.retrieve", return_value=[]),
        patch("ember_memory.core.embeddings.loader.get_embedding_provider"),
        patch("ember_memory.core.backends.loader.get_backend_v2"),
        patch("sys.stdin") as mock_stdin,
        patch("builtins.print") as mock_print,
    ):
        mock_stdin.read.return_value = json.dumps(
            {
                "prompt": "query with no matching memories",
                "session_id": "thread-456",
                "cwd": "/tmp/project",
                "hook_event_name": "UserPromptSubmit",
            }
        )

        import importlib
        import integrations.codex.hook as codex_hook

        importlib.reload(codex_hook)
        codex_hook.main()

    output = json.loads(mock_print.call_args[0][0])
    assert output == {"continue": True}

    entries = [
        json.loads(line)
        for line in (tmp_path / "hook_invocations.jsonl").read_text().splitlines()
    ]
    assert entries[-1]["hook"] == "codex"
    assert entries[-1]["status"] == "no_results"
    assert entries[-1]["hits"] == 0
    assert entries[-1]["prompt_len"] == len("query with no matching memories")

    activity = [
        json.loads(line)
        for line in (tmp_path / "activity.jsonl").read_text().splitlines()
    ]
    assert activity[-1]["ai_id"] == "codex"
    assert activity[-1]["hits"] == 0

    snapshot = json.loads((tmp_path / "last_retrieval_codex.json").read_text())
    assert snapshot["ai_id"] == "codex"
    assert snapshot["results"] == []


def test_codex_hook_retries_strict_threshold_once(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBER_DATA_DIR", str(tmp_path))
    mock_results = [
        RetrievalResult(
            id="fallback-doc",
            content="fallback content",
            collection="notes",
            similarity=0.5,
            composite_score=0.52,
            metadata={},
        )
    ]

    with (
        patch("ember_memory.core.search.retrieve", side_effect=[[], mock_results]) as mock_retrieve,
        patch("ember_memory.core.embeddings.loader.get_embedding_provider"),
        patch("ember_memory.core.backends.loader.get_backend_v2"),
        patch("sys.stdin") as mock_stdin,
        patch("builtins.print") as mock_print,
    ):
        mock_stdin.read.return_value = json.dumps(
            {
                "prompt": "query that needs threshold fallback",
                "session_id": "thread-789",
                "cwd": "/tmp/project",
                "hook_event_name": "UserPromptSubmit",
            }
        )

        import importlib
        import integrations.codex.hook as codex_hook
        from ember_memory import config

        importlib.reload(codex_hook)
        monkeypatch.setattr(config, "SIMILARITY_THRESHOLD", 0.7)
        codex_hook.main()

    output = json.loads(mock_print.call_args[0][0])
    assert output["continue"] is True
    assert "hookSpecificOutput" in output
    assert mock_retrieve.call_count == 2
    assert mock_retrieve.call_args_list[0].kwargs["similarity_threshold"] == 0.7
    assert mock_retrieve.call_args_list[1].kwargs["similarity_threshold"] == 0.45

    entries = [
        json.loads(line)
        for line in (tmp_path / "hook_invocations.jsonl").read_text().splitlines()
    ]
    assert entries[-1]["status"] == "fallback_results"
