"""Ember-owned headless lexical archive service used by the FireCore prototype.

This module intentionally imports only Ember's pure-Python lexical scorer and
stdlib SQLite/stdio facilities. It does not load controllers, vector backends,
providers, hooks, or network listeners.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from ember_memory.core.bm25 import BM25, tokenize

PROTOCOL = "ember.firecore.local/1"
MAX_QUERY = 512
MAX_LIMIT = 20
MAX_RECORDS = 50_000
MAX_BODY = 256_000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _signed_cursor(key: bytes, claims: dict[str, Any]) -> str:
    payload = base64.urlsafe_b64encode(_canonical(claims)).decode().rstrip("=")
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _read_cursor(key: bytes, value: str, expected: dict[str, Any]) -> int:
    try:
        payload, supplied = value.split(".", 1)
        signed = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signed, supplied):
            raise ValueError("cursor authentication failed")
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("cursor authentication failed or cursor is invalid") from exc
    for field, expected_value in expected.items():
        if claims.get(field) != expected_value:
            raise ValueError("continuation cursor scope changed")
    offset = claims.get("offset")
    if not isinstance(offset, int) or offset < 0 or offset > MAX_RECORDS:
        raise ValueError("continuation cursor offset is outside the bounded source")
    return offset


class FireCoreService:
    """Disposable lexical index with durable source lifecycle and cursor key."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS source_state(
              owner TEXT NOT NULL, source_id TEXT NOT NULL, restore_epoch TEXT NOT NULL,
              coverage_revision TEXT NOT NULL, sequence INTEGER NOT NULL,
              PRIMARY KEY(owner,source_id));
            CREATE TABLE IF NOT EXISTS documents(
              owner TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
              message_id TEXT NOT NULL, parent_session_id TEXT NOT NULL, speaker TEXT NOT NULL,
              source_order INTEGER NOT NULL, created_at INTEGER NOT NULL, restore_epoch TEXT NOT NULL,
              revision TEXT NOT NULL, body TEXT NOT NULL, parts TEXT NOT NULL,
              PRIMARY KEY(owner,source_id,message_id));
            CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
              owner UNINDEXED, source_id UNINDEXED, message_id UNINDEXED, body,
              tokenize='unicode61 remove_diacritics 2');
        """)
        row = self.db.execute("SELECT value FROM meta WHERE key='cursor_key'").fetchone()
        if row is None:
            key = os.urandom(32)
            with self.db:
                self.db.execute("INSERT INTO meta(key,value) VALUES('cursor_key',?)", (key,))
            self.cursor_key = key
        else:
            self.cursor_key = bytes(row[0])

    def close(self) -> None:
        self.db.close()

    def _validated_snapshot(self, request: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]]]:
        snapshot = request.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
            raise ValueError("complete canonical snapshot required")
        source_id = snapshot.get("source_id")
        restore_epoch = snapshot.get("restore_epoch")
        coverage_revision = snapshot.get("coverage_revision")
        records = snapshot.get("records")
        if not all(isinstance(x, str) and x for x in (source_id, restore_epoch, coverage_revision)):
            raise ValueError("stable source, restore epoch, and coverage revision required")
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValueError("source inventory exceeds its bounded completeness contract")
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or record.get("owner") != request["owner"]:
                raise ValueError("snapshot owner mismatch")
            if record.get("source_id") != source_id or record.get("restore_epoch") != restore_epoch:
                raise ValueError("record source lifecycle mismatch")
            message_id = record.get("message_id")
            if not isinstance(message_id, str) or not message_id or message_id in seen:
                raise ValueError("duplicate or invalid canonical source reference")
            seen.add(message_id)
            if not isinstance(record.get("source_order"), int) or record["source_order"] < 0:
                raise ValueError("canonical source order is required")
            if not isinstance(record.get("body"), str) or len(record["body"]) > MAX_BODY:
                raise ValueError("message body exceeds bounded lexical projection")
        return source_id, restore_epoch, coverage_revision, records

    def reconcile(self, owner: str, source_id: str, restore_epoch: str,
                  coverage_revision: str, records: list[dict[str, Any]]) -> int:
        if not owner or not source_id or not restore_epoch or not coverage_revision:
            raise ValueError("source principal and lifecycle revisions are required")
        with self.db:
            current = self.db.execute(
                "SELECT restore_epoch,coverage_revision FROM source_state WHERE owner=? AND source_id=?",
                (owner, source_id),
            ).fetchone()
            sequence = 1
            if current is not None:
                sequence = self.db.execute(
                    "SELECT sequence FROM source_state WHERE owner=? AND source_id=?", (owner, source_id)
                ).fetchone()[0]
                if current[0] != restore_epoch or current[1] != coverage_revision:
                    sequence += 1
            self.db.execute("DELETE FROM documents WHERE owner=? AND source_id=?", (owner, source_id))
            self.db.execute("DELETE FROM document_fts WHERE owner=? AND source_id=?", (owner, source_id))
            self.db.executemany(
                "INSERT INTO documents(owner,source_id,session_id,message_id,parent_session_id,speaker,source_order,created_at,restore_epoch,revision,body,parts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [(owner, source_id, r["session_id"], r["message_id"], r.get("parent_session_id", ""),
                  r["speaker"], r["source_order"], r["created_at"], restore_epoch, r["revision"], r["body"],
                  json.dumps(r["parts"], separators=(",", ":"))) for r in records],
            )
            self.db.executemany(
                "INSERT INTO document_fts(owner,source_id,message_id,body) VALUES(?,?,?,?)",
                [(owner, source_id, r["message_id"], r["body"]) for r in records if r["body"]],
            )
            self.db.execute(
                "INSERT INTO source_state(owner,source_id,restore_epoch,coverage_revision,sequence) VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,source_id) DO UPDATE SET restore_epoch=excluded.restore_epoch,coverage_revision=excluded.coverage_revision,sequence=excluded.sequence",
                (owner, source_id, restore_epoch, coverage_revision, sequence),
            )
        return sequence

    def search(self, owner: str, source_id: str, restore_epoch: str, coverage_revision: str,
               sequence: int, query: str, limit: int, cursor: str | None) -> dict[str, Any]:
        if not query or len(query) > MAX_QUERY:
            raise ValueError("query must contain 1..512 characters")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError("result limit must be from 1 to 20")
        expected = {"principal": owner, "source_id": source_id, "restore_epoch": restore_epoch,
                    "coverage_revision": coverage_revision, "sequence": sequence,
                    "query_hash": hashlib.sha256(query.encode()).hexdigest(), "view": "search"}
        offset = _read_cursor(self.cursor_key, cursor, expected) if cursor else 0
        rows = self.db.execute(
            "SELECT message_id,session_id,parent_session_id,speaker,source_order,created_at,revision,body "
            "FROM documents WHERE owner=? AND source_id=? ORDER BY source_order,message_id",
            (owner, source_id),
        ).fetchall()
        if len(rows) > MAX_RECORDS:
            raise ValueError("indexed corpus exceeds the bounded query contract")
        scorer = BM25()
        scorer.index([row["body"] for row in rows])
        terms = tokenize(query)
        literal = not terms or not query.isascii() or bool(re.search(r"[^a-zA-Z0-9\s]", query)) or any(len(term) < 2 for term in terms)
        if literal:
            candidates = [i for i, row in enumerate(rows) if query.casefold() in row["body"].casefold()]
            route = "bounded_literal"
        else:
            match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
            fts_rows = self.db.execute(
                "SELECT message_id FROM document_fts WHERE owner=? AND source_id=? AND document_fts MATCH ?",
                (owner, source_id, match),
            ).fetchall()
            candidate_ids = {row["message_id"] for row in fts_rows}
            candidates = [i for i, row in enumerate(rows) if row["message_id"] in candidate_ids]
            route = "ember_fts5+bm25"
        ranked = [(scorer.score(query, i), rows[i]) for i in candidates]
        ranked.sort(key=lambda item: (-item[0], item[1]["created_at"], item[1]["source_order"], item[1]["message_id"]))
        page = ranked[offset:offset + limit + 1]
        more = len(page) > limit
        page = page[:limit]
        next_cursor = None
        if more:
            next_cursor = _signed_cursor(self.cursor_key, expected | {"offset": offset + limit})
        results = []
        for score, row in page:
            item = dict(row)
            item.pop("body", None)
            item["score"] = score
            item["source_id"] = source_id
            item["restore_epoch"] = restore_epoch
            item["coverage_revision"] = coverage_revision
            item["source_sequence"] = sequence
            results.append(item)
        return {"results": results, "next_cursor": next_cursor, "query_complete": True,
                "query_status": "ok", "source_fresh": True,
                "source_id": source_id, "restore_epoch": restore_epoch,
                "coverage_revision": coverage_revision, "source_sequence": sequence,
                "retrieval_route": route}

    def open(self, owner: str, source_id: str, restore_epoch: str, sequence: int,
             session_id: str, message_id: str, expected_revision: str) -> dict[str, Any]:
        state = self.db.execute("SELECT restore_epoch,coverage_revision,sequence FROM source_state WHERE owner=? AND source_id=?",
                                (owner, source_id)).fetchone()
        if state is None or state[0] != restore_epoch or state[2] != sequence:
            return {"status": "changed", "text": None}
        row = self.db.execute("SELECT * FROM documents WHERE owner=? AND source_id=? AND session_id=? AND message_id=?",
                              (owner, source_id, session_id, message_id)).fetchone()
        if row is None or row["revision"] != expected_revision:
            return {"status": "changed", "text": None}
        return {"status": "ok", "source_id": source_id, "restore_epoch": restore_epoch,
                "coverage_revision": state[1], "source_sequence": sequence, "session_id": session_id, "message_id": message_id,
                "speaker": row["speaker"], "created_at": row["created_at"],
                "revision": row["revision"], "parts": json.loads(row["parts"]),
                "text_convention": "canonical-message-parts-binary-payloads-omitted-v1"}


def authenticated_request(envelope: dict[str, str], token_hex: str) -> dict[str, Any]:
    try:
        key = bytes.fromhex(token_hex)
        payload = base64.b64decode(envelope["payload"], validate=True)
        signature = envelope["signature"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid authenticated envelope") from exc
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not key or not hmac.compare_digest(expected, signature):
        raise ValueError("caller authentication failed")
    request = json.loads(payload)
    if not isinstance(request, dict) or request.get("protocol") != PROTOCOL:
        raise ValueError("unsupported protocol")
    owner = request.get("owner")
    if not isinstance(owner, str) or not owner:
        raise ValueError("trusted runtime principal required")
    return request


def main() -> int:
    try:
        envelope = json.load(sys.stdin)
        request = authenticated_request(envelope, os.environ.get("FIRECORE_CALLER_TOKEN", ""))
        path = os.environ.get("FIRECORE_INDEX_PATH", "")
        if not path:
            raise ValueError("trusted index path required")
        service = FireCoreService(path)
        try:
            owner = request["owner"]
            source_id, restore_epoch, coverage_revision, records = service._validated_snapshot(request)
            sequence = service.reconcile(owner, source_id, restore_epoch, coverage_revision, records)
            operation = request.get("operation")
            if operation == "search":
                result = service.search(owner, source_id, restore_epoch, coverage_revision, sequence,
                                        request.get("query", ""), request.get("limit", 10), request.get("cursor"))
            elif operation == "open":
                result = service.open(owner, source_id, restore_epoch, sequence, request.get("session_id", ""),
                                     request.get("message_id", ""), request.get("expected_revision", ""))
            else:
                raise ValueError("unsupported operation")
        finally:
            service.close()
        json.dump({"ok": True, "response": result}, sys.stdout, separators=(",", ":"))
        return 0
    except Exception as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, separators=(",", ":"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
