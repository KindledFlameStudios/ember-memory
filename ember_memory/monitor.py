"""
Ember Memory — Activity Monitor
Watch memory retrievals in real-time across all Claude Code sessions.

Usage:
    python -m ember_memory.monitor              # Live tail (default)
    python -m ember_memory.monitor --last 20    # Show last 20 retrievals
    python -m ember_memory.monitor --session cc-12345  # Filter by session
    python -m ember_memory.monitor --stats      # Summary statistics
"""

import json
import os
import sys
import time
from datetime import datetime

from ember_memory import config

ACTIVITY_LOG = os.path.join(config.DATA_DIR, "activity.jsonl")

# ── ANSI Colors ──────────────────────────────────────────────────────────────

AMBER = "\033[38;5;214m"
GREEN = "\033[38;5;78m"
DIM = "\033[38;5;245m"
RED = "\033[38;5;203m"
CYAN = "\033[38;5;117m"
BOLD = "\033[1m"
RESET = "\033[0m"


def format_entry(entry):
    """Format a single activity log entry for display."""
    ts = entry.get("ts", "")
    try:
        dt = datetime.fromisoformat(ts)
        time_str = dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        time_str = "??:??:??"

    session = entry.get("session", "unknown")
    prompt = entry.get("prompt", "")
    hits = entry.get("hits", 0)
    top_score = entry.get("top_score", 0)
    collections = entry.get("collections", [])
    elapsed = entry.get("elapsed_ms", 0)

    # Color the score based on quality
    if top_score >= 0.65:
        score_color = GREEN
    elif top_score >= 0.45:
        score_color = AMBER
    else:
        score_color = RED

    # Build the display line
    line_parts = [
        f"{DIM}{time_str}{RESET}",
        f"{CYAN}{session}{RESET}",
    ]

    if hits == 0:
        line_parts.append(f"{DIM}no matches{RESET}")
    else:
        line_parts.append(f"{score_color}{hits} hits (top: {top_score:.0%}){RESET}")
        col_str = ", ".join(collections)
        line_parts.append(f"{AMBER}{col_str}{RESET}")

    line_parts.append(f"{DIM}{elapsed}ms{RESET}")

    header = "  ".join(line_parts)
    prompt_display = f"  {DIM}\"{prompt}\"{RESET}" if prompt else ""

    return f"{header}\n{prompt_display}" if prompt_display else header


def read_entries(path, limit=None, session_filter=None):
    """Read entries from the activity log."""
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if session_filter and entry.get("session") != session_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    if limit:
        entries = entries[-limit:]

    return entries


def cmd_tail(session_filter=None):
    """Live-tail the activity log."""
    print(f"{BOLD}{AMBER}Ember Memory Monitor{RESET}")
    print(f"{DIM}Watching: {ACTIVITY_LOG}{RESET}")
    if session_filter:
        print(f"{DIM}Filtering: {session_filter}{RESET}")
    print(f"{DIM}Press Ctrl+C to stop{RESET}")
    print()

    # Show last 5 entries for context
    existing = read_entries(ACTIVITY_LOG, limit=5, session_filter=session_filter)
    if existing:
        print(f"{DIM}--- Recent activity ---{RESET}")
        for entry in existing:
            print(format_entry(entry))
            print()
        print(f"{DIM}--- Live ---{RESET}")
        print()

    # Tail the file
    try:
        if not os.path.exists(ACTIVITY_LOG):
            os.makedirs(os.path.dirname(ACTIVITY_LOG), exist_ok=True)
            open(ACTIVITY_LOG, 'a').close()

        with open(ACTIVITY_LOG, 'r') as f:
            # Seek to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if session_filter and entry.get("session") != session_filter:
                                continue
                            print(format_entry(entry))
                            print()
                        except json.JSONDecodeError:
                            pass
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        print(f"\n{DIM}Monitor stopped.{RESET}")


def cmd_last(n, session_filter=None):
    """Show last N retrievals."""
    entries = read_entries(ACTIVITY_LOG, limit=n, session_filter=session_filter)
    if not entries:
        print(f"{DIM}No activity recorded yet.{RESET}")
        return

    print(f"{BOLD}{AMBER}Ember Memory — Last {len(entries)} Retrievals{RESET}")
    if session_filter:
        print(f"{DIM}Filtered: {session_filter}{RESET}")
    print()

    for entry in entries:
        print(format_entry(entry))
        print()


def cmd_stats():
    """Show summary statistics."""
    entries = read_entries(ACTIVITY_LOG)
    if not entries:
        print(f"{DIM}No activity recorded yet.{RESET}")
        return

    total = len(entries)
    hits = sum(1 for e in entries if e.get("hits", 0) > 0)
    misses = total - hits
    sessions = set(e.get("session", "") for e in entries)
    avg_elapsed = sum(e.get("elapsed_ms", 0) for e in entries) / total if total else 0
    avg_score = (
        sum(e.get("top_score", 0) for e in entries if e.get("hits", 0) > 0) / hits
        if hits else 0
    )

    # Collection frequency
    col_counts = {}
    for e in entries:
        for c in e.get("collections", []):
            col_counts[c] = col_counts.get(c, 0) + 1

    print(f"{BOLD}{AMBER}Ember Memory — Activity Stats{RESET}")
    print()
    print(f"  Total retrievals:   {BOLD}{total}{RESET}")
    print(f"  With results:       {GREEN}{hits}{RESET} ({hits * 100 // total}%)")
    print(f"  No matches:         {DIM}{misses}{RESET}")
    print(f"  Unique sessions:    {CYAN}{len(sessions)}{RESET}")
    print(f"  Avg latency:        {avg_elapsed:.0f}ms")
    print(f"  Avg top score:      {avg_score:.0%}")
    print()

    if col_counts:
        print(f"  {BOLD}Collection hits:{RESET}")
        for name, count in sorted(col_counts.items(), key=lambda x: -x[1]):
            bar_len = min(count * 2, 40)
            bar = "\u2588" * bar_len
            print(f"    {AMBER}{name:25s}{RESET} {bar} {count}")
    print()

    if len(sessions) > 1:
        print(f"  {BOLD}Sessions:{RESET}")
        for s in sorted(sessions):
            s_count = sum(1 for e in entries if e.get("session") == s)
            print(f"    {CYAN}{s}{RESET}  {s_count} retrievals")


def main():
    args = sys.argv[1:]
    session_filter = None

    # Parse --session flag
    if "--session" in args:
        idx = args.index("--session")
        if idx + 1 < len(args):
            session_filter = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if "--stats" in args:
        cmd_stats()
    elif "--last" in args:
        idx = args.index("--last")
        n = int(args[idx + 1]) if idx + 1 < len(args) else 20
        cmd_last(n, session_filter)
    else:
        cmd_tail(session_filter)


if __name__ == "__main__":
    main()
