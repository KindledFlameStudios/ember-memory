"""Universal auto-retrieval adapter for any CLI tool.

Usage:
    echo "your prompt here" | python -m ember_memory.hook_universal

    # Or with a pipe:
    your_cli --pre-hook "python -m ember_memory.hook_universal"

Reads a prompt from stdin (plain text or JSON with a "prompt" field),
retrieves relevant memories, and prints formatted context to stdout.

Any CLI that can run a command and capture stdout can use this for
automatic memory retrieval. Zero integration work needed.

Environment variables:
    EMBER_AI_ID       — AI namespace (default: "shared"). Set to "*" to see all collections.
    EMBER_WORKSPACE   — Workspace filter (optional)
    EMBER_MAX_RESULTS — Max results (default: from config)
"""

import json
import os
import sys
import time

# Add package root to path
_package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)


def _stable_session_id(prefix="auto"):
    """Walk up process tree to find stable parent."""
    try:
        pid = os.getppid()
        with open(f"/proc/{pid}/stat") as f:
            grandparent = f.read().split(")")[-1].split()[1]
        return f"{prefix}-{grandparent}"
    except Exception:
        return f"{prefix}-{os.getppid()}"


def main():
    t_start = time.monotonic()

    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return

        # Accept plain text or JSON with a "prompt" field
        prompt = raw
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                prompt = data.get("prompt") or data.get("message") or data.get("query") or raw
        except (json.JSONDecodeError, TypeError):
            pass

        if not prompt or len(prompt.strip()) < 3:
            return

        from ember_memory import config
        from ember_memory.core.search import retrieve
        from ember_memory.core.backends.loader import get_backend_v2
        from ember_memory.core.embeddings.loader import get_embedding_provider

        ai_id = os.environ.get("EMBER_AI_ID", "shared")
        workspace = os.environ.get("EMBER_WORKSPACE", "") or None
        session_id = _stable_session_id(ai_id)

        backend = get_backend_v2()
        embedder = get_embedding_provider()
        engine_db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
        os.makedirs(os.path.dirname(engine_db_path), exist_ok=True)

        results = retrieve(
            prompt=prompt,
            ai_id=ai_id,
            workspace=workspace,
            cwd=os.getcwd(),
            session_id=session_id,
            backend=backend,
            embedder=embedder,
            limit=config.MAX_HOOK_RESULTS,
            similarity_threshold=config.SIMILARITY_THRESHOLD,
            engine_db_path=engine_db_path,
        )

        if not results:
            return

        # Format output
        lines = []
        for r in results:
            source = r.metadata.get("source", "")
            header = f"[{r.collection}] ({r.similarity:.0%} match)"
            if source:
                header += f" from:{source}"
            preview = r.content[:config.MAX_PREVIEW_CHARS]
            if len(r.content) > config.MAX_PREVIEW_CHARS:
                preview += "..."
            lines.append(f"{header}\n{preview}")

        tag = config.CONTEXT_TAG
        output = f"<{tag}>\n" + "\n---\n".join(lines) + f"\n</{tag}>"
        print(output)

        # Write activity log
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        try:
            from datetime import datetime, timezone
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session": session_id,
                "ai_id": ai_id,
                "prompt": prompt[:120],
                "hits": len(results),
                "top_score": round(results[0].composite_score, 3) if results else 0,
                "collections": list(set(r.collection for r in results)),
                "elapsed_ms": elapsed_ms,
            }
            log_path = os.path.join(config.DATA_DIR, "activity.jsonl")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

            # Write retrieval snapshots
            snapshot = {
                "ts": entry["ts"],
                "prompt": prompt[:200],
                "elapsed_ms": elapsed_ms,
                "ai_id": ai_id,
                "results": [
                    {
                        "collection": r.collection,
                        "content": r.content,
                        "similarity": round(r.similarity, 4),
                        "composite_score": round(r.composite_score, 4),
                        "score_breakdown": getattr(r, "score_breakdown", {}),
                        "id": r.id[:32],
                    }
                    for r in results
                ],
            }
            for path in (
                os.path.join(config.DATA_DIR, "last_retrieval.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{ai_id}.json"),
                os.path.join(config.DATA_DIR, f"last_retrieval_{session_id}.json"),
            ):
                with open(path, "w") as f:
                    json.dump(snapshot, f, indent=2)
        except Exception:
            pass

    except Exception:
        pass  # Never crash the host CLI


if __name__ == "__main__":
    main()
