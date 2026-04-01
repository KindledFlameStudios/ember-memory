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

# Ensure the ember_memory package is importable when run as a standalone script
_package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

# Suppress Chroma telemetry noise on stderr
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

from ember_memory import config
from ember_memory.core.search import retrieve
from ember_memory.core.embeddings.loader import get_embedding_provider
from ember_memory.core.backends.loader import get_backend_v2

LOG_FILE = os.path.join(config.DATA_DIR, "hook_debug.log")
ACTIVITY_LOG = os.path.join(config.DATA_DIR, "activity.jsonl")

# Session ID: derive from parent PID so each Claude Code instance gets a stable ID
SESSION_ID = f"cc-{os.getppid()}"

# AI namespace — controls which collections are visible during retrieval
AI_ID = os.environ.get("EMBER_AI_ID", "claude")
WORKSPACE = os.environ.get("EMBER_WORKSPACE", "")


def debug_log(msg):
    if not config.HOOK_DEBUG:
        return
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


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
        for path in (get_last_retrieval_path(), get_last_retrieval_path(AI_ID)):
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
        sys.exit(0)

    # Claude Code sends "prompt", not "user_prompt" (docs are wrong)
    user_prompt = hook_input.get("prompt", "") or hook_input.get("user_prompt", "")
    debug_log(f"Prompt: {user_prompt[:200]}")
    if not user_prompt or len(user_prompt.strip()) < 10:
        debug_log("Prompt too short, skipping")
        sys.exit(0)

    # Strip IDE tags from the prompt for cleaner search
    clean_prompt = re.sub(r'<[^>]+>[^<]*</[^>]+>', '', user_prompt).strip()
    if len(clean_prompt) < 10:
        clean_prompt = user_prompt

    debug_log(f"Clean prompt: {clean_prompt[:200]}")

    try:
        embedder = get_embedding_provider()
        backend = get_backend_v2()
        debug_log("Backend and embedder initialized")
    except Exception as e:
        debug_log(f"INIT ERROR: {e}")
        sys.exit(0)

    engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
    os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

    try:
        results = retrieve(
            prompt=clean_prompt,
            ai_id=AI_ID,
            workspace=WORKSPACE,
            backend=backend,
            embedder=embedder,
            limit=config.MAX_HOOK_RESULTS,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
            engine_db_path=engine_db_path,
        )
        debug_log(f"retrieve() returned {len(results)} results")
    except Exception as e:
        debug_log(f"RETRIEVE ERROR: {e}")
        sys.exit(0)

    if not results:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        write_activity(clean_prompt, [], elapsed_ms)
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

    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    write_activity(clean_prompt, results, elapsed_ms)
    debug_log(f"Outputting {len(results)} results ({elapsed_ms}ms)")

    # Plain text on stdout — Claude Code injects exit-0 stdout into context
    print(memory_text, flush=True)

    debug_log("Hook complete")


if __name__ == "__main__":
    main()
