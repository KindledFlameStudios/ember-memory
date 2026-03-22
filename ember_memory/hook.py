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
from ember_memory.backends import get_backend

LOG_FILE = os.path.join(config.DATA_DIR, "hook_debug.log")
ACTIVITY_LOG = os.path.join(config.DATA_DIR, "activity.jsonl")

# Session ID: derive from parent PID so each Claude Code instance gets a stable ID
SESSION_ID = f"cc-{os.getppid()}"


def debug_log(msg):
    if not config.HOOK_DEBUG:
        return
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def write_activity(prompt_preview, results, elapsed_ms):
    """Write one JSONL line to the activity log — always on, lightweight."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": SESSION_ID,
        "prompt": prompt_preview[:120],
        "hits": len(results),
        "top_score": round(results[0]["similarity"], 3) if results else 0,
        "collections": list(set(r["collection"] for r in results)),
        "elapsed_ms": elapsed_ms,
    }
    try:
        os.makedirs(os.path.dirname(ACTIVITY_LOG), exist_ok=True)
        with open(ACTIVITY_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let logging break the hook


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
        backend = get_backend(
            backend=config.BACKEND,
            data_dir=config.DATA_DIR,
            embedding_provider=config.EMBEDDING_PROVIDER,
            embedding_model=config.EMBEDDING_MODEL,
            ollama_url=config.OLLAMA_URL,
        )
        debug_log("Backend initialized")
    except Exception as e:
        debug_log(f"BACKEND INIT ERROR: {e}")
        sys.exit(0)

    try:
        collections = backend.list_collections()
        debug_log(f"Collections found: {len(collections)}")
    except Exception as e:
        debug_log(f"LIST COLLECTIONS ERROR: {e}")
        sys.exit(0)

    if not collections:
        debug_log("No collections found")
        sys.exit(0)

    all_results = []

    for col_info in collections:
        col_name = col_info["name"]
        try:
            debug_log(f"Querying collection: {col_name}")
            results = backend.search(clean_prompt, col_name, config.MAX_HOOK_RESULTS)

            for r in results:
                similarity = 1 - r["distance"] if r.get("distance") is not None else 0
                if similarity >= config.SIMILARITY_THRESHOLD:
                    all_results.append({
                        "similarity": similarity,
                        "content": r["content"],
                        "collection": col_name,
                        "tags": r["metadata"].get("tags", ""),
                        "source": r["metadata"].get("source", ""),
                    })

            debug_log(f"  {col_name}: queried OK, {len(results)} results")
        except Exception as e:
            debug_log(f"  {col_name} QUERY ERROR: {e}")
            continue

    debug_log(f"Total results above threshold: {len(all_results)}")

    if not all_results:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        write_activity(clean_prompt, [], elapsed_ms)
        debug_log("No results above threshold, exiting")
        sys.exit(0)

    # Sort by similarity, take top results
    all_results.sort(key=lambda x: x["similarity"], reverse=True)
    all_results = all_results[:config.MAX_HOOK_RESULTS]

    # Format as concise context
    lines = []
    for r in all_results:
        header_parts = [f"[{r['collection']}]", f"({r['similarity']:.0%} match)"]
        if r["tags"]:
            header_parts.append(f"tags:{r['tags']}")
        if r["source"]:
            header_parts.append(f"from:{r['source']}")
        preview = r["content"][:config.MAX_PREVIEW_CHARS]
        if len(r["content"]) > config.MAX_PREVIEW_CHARS:
            preview += "..."
        lines.append(f"{' '.join(header_parts)}\n{preview}")

    memory_context = "\n---\n".join(lines)
    tag_name = os.environ.get("EMBER_CONTEXT_TAG", "ember-memory")
    memory_text = f"<{tag_name}>\nRelevant memories retrieved automatically ({len(all_results)} results):\n\n{memory_context}\n</{tag_name}>"

    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    write_activity(clean_prompt, all_results, elapsed_ms)
    debug_log(f"Outputting {len(all_results)} results ({elapsed_ms}ms)")

    # Plain text on stdout — Claude Code injects exit-0 stdout into context
    print(memory_text, flush=True)

    debug_log("Hook complete")


if __name__ == "__main__":
    main()
