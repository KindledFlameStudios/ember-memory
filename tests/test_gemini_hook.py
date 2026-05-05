import pytest
import json
from unittest.mock import patch, MagicMock
from ember_memory.core.search import RetrievalResult


def test_gemini_hook_output_format(tmp_path):
    """Verify the hook outputs correct Gemini CLI JSON format."""
    mock_results = [
        RetrievalResult(
            id="doc1", content="test content", collection="notes",
            similarity=0.8, composite_score=0.85, metadata={}
        )
    ]

    with patch("ember_memory.core.search.retrieve", return_value=mock_results), \
         patch("ember_memory.core.embeddings.loader.get_embedding_provider"), \
         patch("ember_memory.core.backends.loader.get_backend_v2"), \
         patch("sys.stdin") as mock_stdin, \
         patch("builtins.print") as mock_print:

        mock_stdin.read.return_value = json.dumps({"prompt": "test query"})

        # Import and run
        import importlib
        import integrations.gemini_cli.hook as gemini_hook
        importlib.reload(gemini_hook)
        gemini_hook.main()

        output = json.loads(mock_print.call_args[0][0])
        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["hookEventName"] == "BeforeAgent"
        assert "ember-memory" in output["hookSpecificOutput"]["additionalContext"]


def test_gemini_hook_empty_prompt():
    """Empty prompt should output allow decision."""
    with patch("sys.stdin") as mock_stdin, \
         patch("builtins.print") as mock_print:

        mock_stdin.read.return_value = json.dumps({"prompt": ""})

        import importlib
        import integrations.gemini_cli.hook as gemini_hook
        importlib.reload(gemini_hook)
        gemini_hook.main()

        output = json.loads(mock_print.call_args[0][0])
        assert output.get("decision") == "allow"


def test_gemini_hook_logs_no_result_invocation(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBER_DATA_DIR", str(tmp_path))

    with patch("ember_memory.core.search.retrieve", return_value=[]), \
         patch("ember_memory.core.embeddings.loader.get_embedding_provider"), \
         patch("ember_memory.core.backends.loader.get_backend_v2"), \
         patch("sys.stdin") as mock_stdin, \
         patch("builtins.print") as mock_print:

        mock_stdin.read.return_value = json.dumps({"prompt": "query with no matching memories"})

        import importlib
        import integrations.gemini_cli.hook as gemini_hook
        importlib.reload(gemini_hook)
        gemini_hook.main()

    output = json.loads(mock_print.call_args[0][0])
    assert output == {"decision": "allow"}

    entries = [
        json.loads(line)
        for line in (tmp_path / "hook_invocations.jsonl").read_text().splitlines()
    ]
    assert entries[-1]["hook"] == "gemini"
    assert entries[-1]["status"] == "no_results"
    assert entries[-1]["hits"] == 0
    assert entries[-1]["prompt_len"] == len("query with no matching memories")

    activity = [
        json.loads(line)
        for line in (tmp_path / "activity.jsonl").read_text().splitlines()
    ]
    assert activity[-1]["ai_id"] == "gemini"
    assert activity[-1]["hits"] == 0

    snapshot = json.loads((tmp_path / "last_retrieval_gemini.json").read_text())
    assert snapshot["ai_id"] == "gemini"
    assert snapshot["results"] == []


def test_gemini_hook_retries_strict_threshold_once(monkeypatch, tmp_path):
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

    with patch("ember_memory.core.search.retrieve", side_effect=[[], mock_results]) as mock_retrieve, \
         patch("ember_memory.core.embeddings.loader.get_embedding_provider"), \
         patch("ember_memory.core.backends.loader.get_backend_v2"), \
         patch("sys.stdin") as mock_stdin, \
         patch("builtins.print") as mock_print:

        mock_stdin.read.return_value = json.dumps({"prompt": "query that needs threshold fallback"})

        import importlib
        import integrations.gemini_cli.hook as gemini_hook
        from ember_memory import config

        importlib.reload(gemini_hook)
        monkeypatch.setattr(config, "SIMILARITY_THRESHOLD", 0.7)
        gemini_hook.main()

    output = json.loads(mock_print.call_args[0][0])
    assert "hookSpecificOutput" in output
    assert mock_retrieve.call_count == 2
    assert mock_retrieve.call_args_list[0].kwargs["similarity_threshold"] == 0.7
    assert mock_retrieve.call_args_list[1].kwargs["similarity_threshold"] == 0.45

    entries = [
        json.loads(line)
        for line in (tmp_path / "hook_invocations.jsonl").read_text().splitlines()
    ]
    assert entries[-1]["status"] == "fallback_results"
