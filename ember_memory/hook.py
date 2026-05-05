"""
Ember Memory — Auto-retrieval hook.
Fires on every UserPromptSubmit, searches all collections, and injects
relevant memories as context for the AI.

Wired as a UserPromptSubmit hook in Claude Code settings.
"""

import json
import sys
import os
import re
import logging
from datetime import datetime, timezone
import traceback

# Ensure the ember_memory package is importable when run as a standalone script
_package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

# Hooks must keep stdout/stderr quiet; stdout is reserved for injected context.
logging.disable(logging.CRITICAL)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

from ember_memory import config

LOG_FILE = os.path.join(config.DATA_DIR, "hook_debug.log")
ACTIVITY_LOG = os.path.join(config.DATA_DIR, "activity.jsonl")

# Session ID: walk up process tree to find the stable shell that launched Claude Code.
# The hook's immediate parent (claude) changes each invocation. Its parent (the terminal
# shell) is stable for the session lifetime.
def _stable_session_id():
    try:
        pid = os.getppid()  # claude process
        with open(f"/proc/{pid}/stat") as f:
            # Field 4 (0-indexed after splitting past comm) is ppid
            grandparent = f.read().split(")")[-1].split()[1]
        return f"cc-{grandparent}"
    except Exception:
        return f"cc-{os.getppid()}"

SESSION_ID = _stable_session_id()

# AI namespace — controls which collections are visible during retrieval.
# Priority: EMBER_AI_ID, then optional EMBER_AI_ID_MAP, then Claude Code default.
def _mapped_ai_id(identity):
    mapping = os.environ.get("EMBER_AI_ID_MAP", "")
    identity = str(identity or "").strip()
    if not mapping or not identity:
        return ""

    for item in mapping.split(","):
        if "=" in item:
            source, target = item.split("=", 1)
        elif ":" in item:
            source, target = item.split(":", 1)
        else:
            continue
        if source.strip() == identity:
            return target.strip()
    return ""


AI_ID = (
    os.environ.get("EMBER_AI_ID")
    or _mapped_ai_id(os.environ.get("FORGE_IDENTITY", ""))
    or "claude"
)
WORKSPACE = os.environ.get("EMBER_WORKSPACE", "")


def debug_log(msg):
    if not config.HOOK_DEBUG:
        return
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def _log_hook_error(exc):
    """Write hook failures locally without polluting stdout/stderr."""
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        path = os.path.join(config.DATA_DIR, "hook_errors.log")
        with open(path, "a") as f:
            f.write("[claude] hook failed\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except Exception:
        pass


def _log_hook_event(status, prompt="", hits=None, elapsed_ms=None, input_keys=None):
    """Write local hook telemetry without polluting stdout/stderr."""
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hook": "claude",
            "ai_id": AI_ID,
            "forge_identity": os.environ.get("FORGE_IDENTITY", ""),
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
        path = os.path.join(config.DATA_DIR, "hook_invocations.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


LAST_RETRIEVAL = os.path.join(config.DATA_DIR, "last_retrieval.json")


def get_last_retrieval_path(ai_id=None):
    if not ai_id:
        return LAST_RETRIEVAL
    safe_ai = re.sub(r"[^a-zA-Z0-9_-]", "_", str(ai_id))
    return os.path.join(config.DATA_DIR, f"last_retrieval_{safe_ai}.json")


def write_activity(prompt_preview, results, elapsed_ms):
    """Write activity log + last retrieval snapshot for dashboard."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": SESSION_ID,
        "ai_id": AI_ID,
        "prompt": prompt_preview[:120],
        "hits": len(results),
        "top_score": round(results[0].composite_score, 3) if results else 0,
        "collections": list(set(r.collection for r in results)),
        "elapsed_ms": elapsed_ms,
    }
    try:
        os.makedirs(os.path.dirname(ACTIVITY_LOG), exist_ok=True)
        with open(ACTIVITY_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    # Write full last retrieval snapshot for dashboard
    snapshot = {
        "ts": entry["ts"],
        "prompt": prompt_preview[:200],
        "elapsed_ms": elapsed_ms,
        "ai_id": AI_ID,
        "results": [
            {
                "collection": r.collection,
                "content": r.content,
                "similarity": round(r.similarity, 4),
                "composite_score": round(r.composite_score, 4),
                "score_breakdown": r.score_breakdown,
                "id": r.id[:32],
            }
            for r in results
        ],
    }
    try:
        for path in (
            get_last_retrieval_path(),
            get_last_retrieval_path(AI_ID),
            get_last_retrieval_path(SESSION_ID),
        ):
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
    except Exception:
        pass


def main():
    import time
    t_start = time.monotonic()

    debug_log("Hook invoked")
    try:
        raw = sys.stdin.read()
        debug_log(f"Raw stdin: {raw[:500]}")
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, EOFError) as e:
        debug_log(f"JSON parse error: {e}")
        _log_hook_event("parse_error", elapsed_ms=int((time.monotonic() - t_start) * 1000))
        sys.exit(0)

    # Claude Code sends "prompt", not "user_prompt" (docs are wrong)
    user_prompt = hook_input.get("prompt", "") or hook_input.get("user_prompt", "")
    debug_log(f"Prompt: {user_prompt[:200]}")
    if not user_prompt or len(user_prompt.strip()) < 10:
        debug_log("Prompt too short, skipping")
        _log_hook_event(
            "empty_prompt",
            prompt=user_prompt,
            elapsed_ms=int((time.monotonic() - t_start) * 1000),
            input_keys=hook_input.keys(),
        )
        sys.exit(0)

    if not config.AUTO_QUERY:
        debug_log("Auto-query disabled, skipping")
        _log_hook_event(
            "auto_query_off",
            prompt=user_prompt,
            elapsed_ms=int((time.monotonic() - t_start) * 1000),
            input_keys=hook_input.keys(),
        )
        sys.exit(0)

    # Strip IDE tags from the prompt for cleaner search
    clean_prompt = re.sub(r'<[^>]+>[^<]*</[^>]+>', '', user_prompt).strip()
    if len(clean_prompt) < 10:
        clean_prompt = user_prompt

    debug_log(f"Clean prompt: {clean_prompt[:200]}")

    try:
        from ember_memory.core.search import retrieve
        from ember_memory.core.embeddings.loader import get_embedding_provider
        from ember_memory.core.backends.loader import get_backend_v2

        embedder = get_embedding_provider()
        backend = get_backend_v2()
        debug_log("Backend and embedder initialized")
    except Exception as e:
        debug_log(f"INIT ERROR: {e}")
        _log_hook_error(e)
        _log_hook_event(
            "error",
            prompt=clean_prompt,
            elapsed_ms=int((time.monotonic() - t_start) * 1000),
            input_keys=hook_input.keys(),
        )
        sys.exit(0)

    engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
    os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

    try:
        results = retrieve(
            prompt=clean_prompt,
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
        fallback_used = False
        if not results and config.SIMILARITY_THRESHOLD > 0.45:
            results = retrieve(
                prompt=clean_prompt,
                ai_id=AI_ID,
                workspace=WORKSPACE,
                cwd=os.getcwd(),
                session_id=SESSION_ID,
                backend=backend,
                embedder=embedder,
                limit=config.MAX_HOOK_RESULTS,
                similarity_threshold=0.45,
                engine_db_path=engine_db_path,
            )
            fallback_used = bool(results)
        debug_log(f"retrieve() returned {len(results)} results")
    except Exception as e:
        debug_log(f"RETRIEVE ERROR: {e}")
        _log_hook_error(e)
        _log_hook_event(
            "error",
            prompt=clean_prompt,
            elapsed_ms=int((time.monotonic() - t_start) * 1000),
            input_keys=hook_input.keys(),
        )
        sys.exit(0)

    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    if not results:
        write_activity(clean_prompt, [], elapsed_ms)
        _log_hook_event(
            "no_results",
            prompt=clean_prompt,
            hits=0,
            elapsed_ms=elapsed_ms,
            input_keys=hook_input.keys(),
        )
        debug_log("No results above threshold, exiting")
        sys.exit(0)

    # Format as concise context
    lines = []
    for r in results:
        tags = r.metadata.get("tags", "")
        source = r.metadata.get("source", "")
        header_parts = [f"[{r.collection}]", f"({r.similarity:.0%} match)"]
        if tags:
            header_parts.append(f"tags:{tags}")
        if source:
            header_parts.append(f"from:{source}")
        preview = r.content[:config.MAX_PREVIEW_CHARS]
        if len(r.content) > config.MAX_PREVIEW_CHARS:
            preview += "..."
        lines.append(f"{' '.join(header_parts)}\n{preview}")

    memory_context = "\n---\n".join(lines)
    tag_name = config.CONTEXT_TAG
    memory_text = f"<{tag_name}>\nRelevant memories retrieved automatically ({len(results)} results):\n\n{memory_context}\n</{tag_name}>"

    write_activity(clean_prompt, results, elapsed_ms)
    _log_hook_event(
        "fallback_results" if fallback_used else "results",
        prompt=clean_prompt,
        hits=len(results),
        elapsed_ms=elapsed_ms,
        input_keys=hook_input.keys(),
    )
    debug_log(f"Outputting {len(results)} results ({elapsed_ms}ms)")

    # Plain text on stdout — Claude Code injects exit-0 stdout into context
    print(memory_text, flush=True)

    debug_log("Hook complete")


if __name__ == "__main__":
    main()
