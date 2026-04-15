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
