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
