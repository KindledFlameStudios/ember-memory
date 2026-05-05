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
import traceback

# Suppress all logging to stderr. Codex hooks expect clean stdout.
logging.disable(logging.CRITICAL)

# Ensure the ember_memory package is importable when run as a standalone script.
_package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)


def _output_continue():
    print(json.dumps({"continue": True}))


def _log_hook_error(exc):
    """Write hook failures locally without polluting stdout/stderr."""
    try:
        log_dir = os.environ.get("EMBER_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".ember-memory")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "hook_errors.log")
        with open(path, "a") as f:
            f.write("[codex] hook failed\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except Exception:
        pass


def _log_hook_event(status, prompt="", hits=None, elapsed_ms=None, input_keys=None):
    """Write local hook telemetry without polluting stdout/stderr."""
    try:
        from datetime import datetime, timezone

        log_dir = os.environ.get("EMBER_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".ember-memory")
        os.makedirs(log_dir, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hook": "codex",
            "status": status,
            "prompt_len": len(prompt or ""),
            "pid": os.getpid(),
            "ppid": os.getppid(),
        }
        if hits is not None:
            entry["hits"] = hits
        if elapsed_ms is not None:
            entry["elapsed_ms"] = elapsed_ms
        if input_keys:
            entry["input_keys"] = sorted(str(key) for key in input_keys)
        path = os.path.join(log_dir, "hook_invocations.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _codex_session_scope(raw_session_id):
    """Normalize Codex session ids so Engine heat can aggregate by CLI."""
    value = str(raw_session_id or "").strip()
    if not value:
        return f"codex-{os.getppid()}"
    if value.startswith("codex-"):
        return value
    return f"codex-{value}"


def _write_activity_snapshot(config, ai_id, session_id, prompt, elapsed_ms, results):
    """Write dashboard activity and retrieval snapshot for any hook result count."""
    try:
        from datetime import datetime, timezone

        data_dir = os.environ.get("EMBER_DATA_DIR") or config.DATA_DIR
        activity_path = os.path.join(data_dir, "activity.jsonl")
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
            os.path.join(data_dir, "last_retrieval.json"),
            os.path.join(data_dir, f"last_retrieval_{ai_id}.json"),
            os.path.join(data_dir, f"last_retrieval_{session_id}.json"),
        ]:
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
    except Exception:
        pass


def main():
    import time

    _t_start = time.monotonic()

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _log_hook_event("no_input", elapsed_ms=0)
            _output_continue()
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "").strip()

        if not prompt or len(prompt) < 3:
            _log_hook_event(
                "empty_prompt",
                prompt=prompt,
                elapsed_ms=int((time.monotonic() - _t_start) * 1000),
                input_keys=data.keys(),
            )
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
        fallback_used = False
        if not results and config.SIMILARITY_THRESHOLD > 0.45:
            results = retrieve(
                prompt=prompt,
                ai_id=ai_id,
                workspace=workspace,
                cwd=cwd,
                session_id=session_id,
                backend=backend,
                embedder=embedder,
                limit=config.MAX_HOOK_RESULTS,
                similarity_threshold=0.45,
                engine_db_path=engine_db_path,
            )
            fallback_used = bool(results)
        elapsed_ms = int((time.monotonic() - _t_start) * 1000)

        if not results:
            _write_activity_snapshot(config, ai_id, session_id, prompt, elapsed_ms, [])
            _log_hook_event(
                "no_results",
                prompt=prompt,
                hits=0,
                elapsed_ms=elapsed_ms,
                input_keys=data.keys(),
            )
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

        _write_activity_snapshot(config, ai_id, session_id, prompt, elapsed_ms, results)

        _log_hook_event(
            "fallback_results" if fallback_used else "results",
            prompt=prompt,
            hits=len(results),
            elapsed_ms=elapsed_ms,
            input_keys=data.keys(),
        )

        output = {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": additional_context,
            },
        }
        print(json.dumps(output))

    except Exception as exc:
        _log_hook_error(exc)
        _log_hook_event("error", elapsed_ms=int((time.monotonic() - _t_start) * 1000))
        _output_continue()


if __name__ == "__main__":
    main()
