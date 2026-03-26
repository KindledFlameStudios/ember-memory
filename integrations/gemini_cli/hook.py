#!/usr/bin/env python3
"""Ember Memory — Gemini CLI auto-retrieval hook.

Fires on BeforeAgent events. Retrieves relevant memories and injects
them via hookSpecificOutput.additionalContext.

Input (stdin): {"prompt": "user message", "hook_event_name": "BeforeAgent", ...}
Output (stdout): {"hookSpecificOutput": {"hookEventName": "BeforeAgent", "additionalContext": "..."}}
"""

import json
import os
import sys
import logging

# Suppress all logging to stderr (Gemini CLI golden rule: only JSON on stdout)
logging.disable(logging.CRITICAL)

# Ensure the ember_memory package is importable when run as a standalone script
_package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _output_allow()
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "").strip()

        if not prompt or len(prompt) < 3:
            _output_allow()
            return

        # Import here to avoid slow startup on non-memory events
        from ember_memory.core.search import retrieve
        from ember_memory.core.embeddings.loader import get_embedding_provider
        from ember_memory.core.backends.loader import get_backend_v2
        from ember_memory import config

        AI_ID = os.environ.get("EMBER_AI_ID", "gemini")
        engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
        os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

        embedder = get_embedding_provider()
        backend = get_backend_v2()

        results = retrieve(
            prompt=prompt,
            ai_id=AI_ID,
            backend=backend,
            embedder=embedder,
            limit=int(os.environ.get("EMBER_MAX_HOOK_RESULTS", "5")),
            similarity_threshold=float(os.environ.get("EMBER_SIMILARITY_THRESHOLD", "0.35")),
            engine_db_path=engine_db_path,
        )

        if not results:
            _output_allow()
            return

        # Format results as context text
        lines = []
        for r in results:
            score_pct = int(r.composite_score * 100)
            tags = r.metadata.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"[{r.collection}] ({score_pct}% match){tag_str}")

            preview = r.content
            max_chars = int(os.environ.get("EMBER_MAX_PREVIEW_CHARS", "800"))
            if len(preview) > max_chars:
                preview = preview[:max_chars] + "..."
            lines.append(preview)
            lines.append("")

        context_text = "\n".join(lines).strip()

        # Wrap in ember-memory tags
        tag = os.environ.get("EMBER_CONTEXT_TAG", "ember-memory")
        additional_context = f"<{tag}>\n{context_text}\n</{tag}>"

        # Output Gemini CLI format
        output = {
            "hookSpecificOutput": {
                "hookEventName": "BeforeAgent",
                "additionalContext": additional_context
            }
        }
        print(json.dumps(output))

    except Exception:
        # Never crash the CLI — output allow on any error
        _output_allow()


def _output_allow():
    """Output a minimal allow response."""
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
