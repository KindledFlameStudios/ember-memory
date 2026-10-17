#!/usr/bin/env python3
"""Measure bounded FireCore operations using a disposable synthetic corpus."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ember_memory.firecore import FireCoreService, MAX_RECORDS


def timed(call):
    started = time.perf_counter()
    value = call()
    return value, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=20_000)
    args = parser.parse_args()
    if not 1 <= args.records <= MAX_RECORDS:
        parser.error(f"--records must be from 1 to {MAX_RECORDS}")
    owner, source, session_id = "synthetic-owner", "synthetic-source", "synthetic-session"
    records = []
    for order in range(args.records):
        body = ("duplicate alpha evidence punctuation C++ v1.2" if order % 17 == 0
                else f"alpha corpus row {order} words equal_timestamp")
        records.append({
            "owner": owner, "source_id": source, "restore_epoch": "restore-1",
            "message_id": f"message-{order:06d}", "session_id": session_id,
            "parent_session_id": "synthetic-parent", "speaker": "user",
            "source_order": order, "created_at": 1_800_000_000,
            "revision": f"revision-{order:06d}", "body": body,
            "parts": [{"kind": "text", "text": body}],
        })
    transport_bytes = len(json.dumps({
        "source_id": source, "restore_epoch": "restore-1",
        "coverage_revision": "coverage-1", "complete": True, "records": records,
    }, separators=(",", ":")).encode())
    with tempfile.TemporaryDirectory(prefix="firecore-scale-") as temp:
        service = FireCoreService(str(Path(temp) / "index.sqlite"))
        _, cold_reconcile_ms = timed(lambda: service.reconcile(
            owner, source, "restore-1", "coverage-1", records
        ))
        sequence, warm_reconcile_ms = timed(lambda: service.reconcile(
            owner, source, "restore-1", "coverage-1", records
        ))
        tracemalloc.start()
        result, cold_query_ms = timed(lambda: service.search(
            owner, source, "restore-1", "coverage-1", sequence, "alpha", 20, None
        ))
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        result_warm, warm_query_ms = timed(lambda: service.search(
            owner, source, "restore-1", "coverage-1", sequence, "alpha", 20, None
        ))
        page, page_ms = timed(lambda: service.page_session(
            owner, source, "restore-1", "coverage-1", sequence,
            session_id, 50, None
        ))
        tracemalloc.stop()
        payload_bytes = len(json.dumps(result, separators=(",", ":")).encode())
        assert result["query_complete"] and len(result["results"]) == 20
        assert result["next_cursor"] and result["results"][1]["preceding_preview"]
        assert len(page["messages"]) == min(50, args.records)
        assert page["source_fresh"]
        print(json.dumps({
            "records": args.records,
            "synthetic_transport_bytes": transport_bytes,
            "cold_reconcile_ms": round(cold_reconcile_ms, 2),
            "unchanged_reconcile_ms": round(warm_reconcile_ms, 2),
            "cold_search_ms": round(cold_query_ms, 2),
            "warm_search_ms": round(warm_query_ms, 2),
            "session_page_ms": round(page_ms, 2),
            "search_payload_bytes": payload_bytes,
            "tracemalloc_peak_search_bytes": peak_bytes,
            "search_results": len(result_warm["results"]),
            "page_messages": len(page["messages"]),
            "page_complete": page["query_complete"],
            "query_complete": result_warm["query_complete"],
            "source_fresh": result_warm["source_fresh"],
            "cursor_issued": bool(result["next_cursor"]),
        }, sort_keys=True))
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
