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
    import time
    _t_start = time.monotonic()
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
        def _stable_session_id():
            try:
                pid = os.getppid()
                with open(f"/proc/{pid}/stat") as f:
                    grandparent = f.read().split(")")[-1].split()[1]
                return f"gemini-{grandparent}"
            except Exception:
                return f"gemini-{os.getppid()}"
        SESSION_ID = _stable_session_id()
        WORKSPACE = os.environ.get("EMBER_WORKSPACE", "")
        engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
        os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

        embedder = get_embedding_provider()
        backend = get_backend_v2()

        results = retrieve(
            prompt=prompt,
            ai_id=AI_ID,
            workspace=WORKSPACE,
            cwd=os.getcwd(),
            session_id=SESSION_ID,
            backend=backend,
            embedder=embedder,
            limit=config.MAX_HOOK_RESULTS,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
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
            max_chars = config.MAX_PREVIEW_CHARS
            if len(preview) > max_chars:
                preview = preview[:max_chars] + "..."
            lines.append(preview)
            lines.append("")

        context_text = "\n".join(lines).strip()

        # Wrap in ember-memory tags
        tag = config.CONTEXT_TAG
        additional_context = f"<{tag}>\n{context_text}\n</{tag}>"

        # Write activity log + per-AI retrieval snapshot
        elapsed_ms = int((time.monotonic() - _t_start) * 1000)
        try:
            from datetime import datetime, timezone
            activity_path = os.path.join(config.DATA_DIR, "activity.jsonl")
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session": SESSION_ID,
                "ai_id": AI_ID,
                "prompt": prompt[:120],
                "hits": len(results),
                "top_score": round(results[0].composite_score, 3) if results else 0,
                "collections": list(set(r.collection for r in results)),
                "elapsed_ms": elapsed_ms,
            }
            os.makedirs(os.path.dirname(activity_path), exist_ok=True)
            with open(activity_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

            # Per-AI last retrieval snapshot
            snapshot = {
                "ts": entry["ts"],
                "prompt": prompt[:200],
                "elapsed_ms": elapsed_ms,
                "ai_id": AI_ID,
                "results": [
                    {
                        "collection": r.collection,
                        "content": r.content,
                        "similarity": round(r.similarity, 4),
                        "composite_score": round(r.composite_score, 4),
                        "score_breakdown": getattr(r, 'score_breakdown', {}),
                        "id": r.id[:32],
                    }
                    for r in results
                ],
            }
            # Write global + per-AI + per-session
            for path in [
                os.path.join(config.DATA_DIR, "last_retrieval.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{AI_ID}.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{SESSION_ID}.json"),
            ]:
                with open(path, "w") as f:
                    json.dump(snapshot, f, indent=2)
        except Exception:
            pass  # Never let logging break the hook

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
