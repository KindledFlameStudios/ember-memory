#!/usr/bin/env python3
"""Ember Memory — Codex CLI auto-retrieval hook.

Fires on Codex `UserPromptSubmit` lifecycle events. Retrieves relevant
memories and injects them via hookSpecificOutput.additionalContext.

Input (stdin): {"prompt": "user message", "hook_event_name": "UserPromptSubmit", ...}
Output (stdout): {"continue": true, "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
"""

import json
import logging
import os
import sys

# Suppress all logging to stderr. Codex hooks expect clean stdout.
logging.disable(logging.CRITICAL)

# Ensure the ember_memory package is importable when run as a standalone script.
_package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)


def _output_continue():
    print(json.dumps({"continue": True}))


def _codex_session_scope(raw_session_id):
    """Normalize Codex session ids so Engine heat can aggregate by CLI."""
    value = str(raw_session_id or "").strip()
    if not value:
        return f"codex-{os.getppid()}"
    if value.startswith("codex-"):
        return value
    return f"codex-{value}"


def main():
    import time

    _t_start = time.monotonic()

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _output_continue()
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "").strip()

        if not prompt or len(prompt) < 3:
            _output_continue()
            return

        from ember_memory import config
        from ember_memory.core.backends.loader import get_backend_v2
        from ember_memory.core.embeddings.loader import get_embedding_provider
        from ember_memory.core.search import retrieve

        ai_id = os.environ.get("EMBER_AI_ID", "codex")
        session_id = _codex_session_scope(data.get("session_id"))
        workspace = os.environ.get("EMBER_WORKSPACE", "")
        cwd = data.get("cwd") or os.getcwd()
        engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
        os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

        embedder = get_embedding_provider()
        backend = get_backend_v2()

        results = retrieve(
            prompt=prompt,
            ai_id=ai_id,
            workspace=workspace,
            cwd=cwd,
            session_id=session_id,
            backend=backend,
            embedder=embedder,
            limit=config.MAX_HOOK_RESULTS,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
            engine_db_path=engine_db_path,
        )

        if not results:
            _output_continue()
            return

        lines = []
        for result in results:
            score_pct = int(result.composite_score * 100)
            tags = result.metadata.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"[{result.collection}] ({score_pct}% match){tag_str}")

            preview = result.content
            max_chars = config.MAX_PREVIEW_CHARS
            if len(preview) > max_chars:
                preview = preview[:max_chars] + "..."
            lines.append(preview)
            lines.append("")

        context_text = "\n".join(lines).strip()
        tag = config.CONTEXT_TAG
        additional_context = (
            f"<{tag}>\n"
            f"Relevant memories retrieved automatically ({len(results)} results):\n\n"
            f"{context_text}\n"
            f"</{tag}>"
        )

        elapsed_ms = int((time.monotonic() - _t_start) * 1000)
        try:
            from datetime import datetime, timezone

            activity_path = os.path.join(config.DATA_DIR, "activity.jsonl")
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session": session_id,
                "ai_id": ai_id,
                "prompt": prompt[:120],
                "hits": len(results),
                "top_score": round(results[0].composite_score, 3) if results else 0,
                "collections": list(set(result.collection for result in results)),
                "elapsed_ms": elapsed_ms,
            }
            os.makedirs(os.path.dirname(activity_path), exist_ok=True)
            with open(activity_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

            snapshot = {
                "ts": entry["ts"],
                "prompt": prompt[:200],
                "elapsed_ms": elapsed_ms,
                "ai_id": ai_id,
                "results": [
                    {
                        "collection": result.collection,
                        "content": result.content,
                        "similarity": round(result.similarity, 4),
                        "composite_score": round(result.composite_score, 4),
                        "score_breakdown": getattr(result, "score_breakdown", {}),
                        "id": result.id[:32],
                    }
                    for result in results
                ],
            }
            for path in [
                os.path.join(config.DATA_DIR, "last_retrieval.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{ai_id}.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{session_id}.json"),
            ]:
                with open(path, "w") as f:
                    json.dump(snapshot, f, indent=2)
        except Exception:
            pass

        output = {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": additional_context,
            },
        }
        print(json.dumps(output))

    except Exception:
        _output_continue()


if __name__ == "__main__":
    main()
