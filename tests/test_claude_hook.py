import json
import pytest
from unittest.mock import patch


def test_claude_hook_logs_no_result_invocation(monkeypatch, tmp_path):
    import importlib
    import ember_memory.hook as claude_hook

    importlib.reload(claude_hook)
    monkeypatch.setattr(claude_hook.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(claude_hook, "ACTIVITY_LOG", str(tmp_path / "activity.jsonl"))
    monkeypatch.setattr(claude_hook, "LAST_RETRIEVAL", str(tmp_path / "last_retrieval.json"))

    with (
        patch("ember_memory.core.search.retrieve", return_value=[]),
        patch("ember_memory.core.embeddings.loader.get_embedding_provider"),
        patch("ember_memory.core.backends.loader.get_backend_v2"),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.read.return_value = json.dumps(
            {
                "prompt": "query with no matching memories",
                "hook_event_name": "UserPromptSubmit",
            }
        )

        with pytest.raises(SystemExit) as exc:
            claude_hook.main()

    assert exc.value.code == 0

    entries = [
        json.loads(line)
        for line in (tmp_path / "hook_invocations.jsonl").read_text().splitlines()
    ]
    assert entries[-1]["hook"] == "claude"
    assert entries[-1]["status"] == "no_results"
    assert entries[-1]["hits"] == 0
    assert entries[-1]["prompt_len"] == len("query with no matching memories")


def test_claude_hook_supports_generic_identity_map(monkeypatch):
    monkeypatch.setenv("FORGE_IDENTITY", "custom-writer")
    monkeypatch.setenv("EMBER_AI_ID_MAP", "custom-writer=codex,reviewer=gemini")
    monkeypatch.delenv("EMBER_AI_ID", raising=False)

    import importlib
    import ember_memory.hook as claude_hook

    importlib.reload(claude_hook)

    assert claude_hook.AI_ID == "codex"
