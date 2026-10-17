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

from ember_memory.core.bm25 import tokenize

PROTOCOL = "ember.firecore.local/1"
MAX_QUERY = 512
MAX_LIMIT = 20
MAX_RECORDS = 50_000
MAX_BODY = 256_000
MAX_PAGE_BYTES = 1_048_576


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
        self._reconcile_test_hook = None
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS source_state(
              owner TEXT NOT NULL, source_id TEXT NOT NULL, restore_epoch TEXT NOT NULL,
              coverage_revision TEXT NOT NULL, sequence INTEGER NOT NULL,
              PRIMARY KEY(owner,source_id));
            CREATE TABLE IF NOT EXISTS indexed_sessions(
              owner TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
              source_revision INTEGER NOT NULL, metadata TEXT NOT NULL,
              PRIMARY KEY(owner,source_id,session_id));
            CREATE TABLE IF NOT EXISTS documents(
              owner TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
              message_id TEXT NOT NULL, parent_session_id TEXT NOT NULL, speaker TEXT NOT NULL,
              source_order INTEGER NOT NULL, created_at INTEGER NOT NULL, restore_epoch TEXT NOT NULL,
              revision TEXT NOT NULL, body TEXT NOT NULL, parts TEXT NOT NULL,
              is_summary_message INTEGER NOT NULL DEFAULT 0,
              source_revision INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(owner,source_id,message_id));
            CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
              owner UNINDEXED, source_id UNINDEXED, message_id UNINDEXED, body,
              tokenize='unicode61 remove_diacritics 2');
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(documents)")}
        if "is_summary_message" not in columns:
            self.db.execute("ALTER TABLE documents ADD COLUMN is_summary_message INTEGER NOT NULL DEFAULT 0")
        if "source_revision" not in columns:
            self.db.execute("ALTER TABLE documents ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0")
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

    def _validated_snapshot(self, request: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        snapshot = request.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
            raise ValueError("complete canonical snapshot required")
        source_id = snapshot.get("source_id")
        restore_epoch = snapshot.get("restore_epoch")
        coverage_revision = snapshot.get("coverage_revision")
        records = snapshot.get("records")
        sessions = snapshot.get("sessions")
        changed_sessions = snapshot.get("changed_sessions")
        if not all(isinstance(x, str) and x for x in (source_id, restore_epoch, coverage_revision)):
            raise ValueError("stable source, restore epoch, and coverage revision required")
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValueError("changed-session inventory exceeds its bounded completeness contract")
        if not isinstance(sessions, list) or len(sessions) > MAX_RECORDS or not isinstance(changed_sessions, list):
            raise ValueError("complete session revision manifest is required")
        session_ids = [item.get("session_id") for item in sessions if isinstance(item, dict)]
        if len(session_ids) != len(sessions) or len(set(session_ids)) != len(session_ids) or not all(isinstance(value, str) and value for value in session_ids):
            raise ValueError("duplicate or invalid session revision manifest")
        if len(set(changed_sessions)) != len(changed_sessions) or not set(changed_sessions).issubset(session_ids):
            raise ValueError("changed sessions are not covered by the complete manifest")
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or record.get("owner") != request["owner"]:
                raise ValueError("snapshot owner mismatch")
            if record.get("source_id") != source_id or record.get("restore_epoch") != restore_epoch:
                raise ValueError("record source lifecycle mismatch")
            if record.get("session_id") not in changed_sessions or not isinstance(record.get("source_revision"), int):
                raise ValueError("record is not bound to a changed session revision")
            message_id = record.get("message_id")
            if not isinstance(message_id, str) or not message_id or message_id in seen:
                raise ValueError("duplicate or invalid canonical source reference")
            seen.add(message_id)
            if not isinstance(record.get("source_order"), int) or record["source_order"] < 0:
                raise ValueError("canonical source order is required")
            if not isinstance(record.get("body"), str) or len(record["body"].encode("utf-8")) > MAX_BODY:
                raise ValueError("message body exceeds bounded lexical projection")
            parts = record.get("parts")
            if not isinstance(parts, list) or len(json.dumps(parts, separators=(",", ":")).encode("utf-8")) > MAX_BODY:
                raise ValueError("message parts exceed bounded context projection")
        return source_id, restore_epoch, coverage_revision, records, sessions, changed_sessions

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
                if current[0] == restore_epoch and current[1] == coverage_revision:
                    indexed_rows = self.db.execute(
                        "SELECT message_id,session_id,parent_session_id,speaker,source_order,created_at,revision,is_summary_message "
                        "FROM documents WHERE owner=? AND source_id=? ORDER BY session_id,source_order,message_id",
                        (owner, source_id),
                    ).fetchall()
                    expected_manifest = hashlib.sha256()
                    for record in sorted(records, key=lambda item: (item["session_id"], item["source_order"], item["message_id"])):
                        expected_manifest.update(_canonical([
                            record["message_id"], record["session_id"], record.get("parent_session_id", ""),
                            record["speaker"], record["source_order"], record["created_at"], record["revision"],
                            int(bool(record.get("is_summary_message", False))),
                        ]))
                    indexed_manifest = hashlib.sha256()
                    for row in indexed_rows:
                        indexed_manifest.update(_canonical(list(row)))
                    indexed_fts = self.db.execute(
                        "SELECT COUNT(*) FROM document_fts WHERE owner=? AND source_id=?", (owner, source_id)
                    ).fetchone()[0]
                    expected_fts = sum(1 for record in records if record["body"])
                    if len(indexed_rows) == len(records) and indexed_manifest.digest() == expected_manifest.digest() and indexed_fts == expected_fts:
                        return sequence
                else:
                    sequence += 1
            self.db.execute("DELETE FROM documents WHERE owner=? AND source_id=?", (owner, source_id))
            self.db.execute("DELETE FROM document_fts WHERE owner=? AND source_id=?", (owner, source_id))
            self.db.executemany(
                "INSERT INTO documents(owner,source_id,session_id,message_id,parent_session_id,speaker,source_order,created_at,restore_epoch,revision,body,parts,is_summary_message,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(owner, source_id, r["session_id"], r["message_id"], r.get("parent_session_id", ""),
                  r["speaker"], r["source_order"], r["created_at"], restore_epoch, r["revision"], r["body"],
                  json.dumps(r["parts"], separators=(",", ":")), int(bool(r.get("is_summary_message", False))),
                  int(r.get("source_revision", 0))) for r in records],
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

    def reconcile_incremental(self, owner: str, source_id: str, restore_epoch: str,
                               coverage_revision: str, sessions: list[dict[str, Any]],
                               changed_sessions: list[str], records: list[dict[str, Any]]) -> int:
        if not owner or not source_id or not restore_epoch or not coverage_revision:
            raise ValueError("source principal and lifecycle revisions are required")
        if len(sessions) > MAX_RECORDS or len(changed_sessions) > len(sessions):
            raise ValueError("complete source manifest exceeds bounded limits")
        session_map: dict[str, dict[str, Any]] = {}
        for item in sessions:
            if not isinstance(item, dict):
                raise ValueError("invalid canonical session manifest")
            session_id = item.get("session_id")
            revision = item.get("source_revision")
            if not isinstance(session_id, str) or not session_id or session_id in session_map or not isinstance(revision, int):
                raise ValueError("duplicate or invalid canonical session manifest entry")
            session_map[session_id] = item
        changed = set(changed_sessions)
        if len(changed) != len(changed_sessions) or not changed.issubset(session_map):
            raise ValueError("changed session set is not covered by complete manifest")
        seen: set[str] = set()
        grouped: dict[str, list[dict[str, Any]]] = {session_id: [] for session_id in changed}
        for record in records:
            if record.get("owner") != owner or record.get("source_id") != source_id or record.get("restore_epoch") != restore_epoch:
                raise ValueError("record source lifecycle mismatch")
            session_id = record.get("session_id")
            if session_id not in changed or record.get("source_revision") != session_map[session_id]["source_revision"]:
                raise ValueError("changed record is not bound to its manifest revision")
            message_id = record.get("message_id")
            if not isinstance(message_id, str) or not message_id or message_id in seen:
                raise ValueError("duplicate or invalid canonical message reference")
            seen.add(message_id)
            if not isinstance(record.get("source_order"), int) or record["source_order"] < 0:
                raise ValueError("canonical source order is required")
            if not isinstance(record.get("body"), str) or len(record["body"].encode("utf-8")) > MAX_BODY:
                raise ValueError("message body exceeds bounded lexical projection")
            grouped[session_id].append(record)
        with self.db:
            current = self.db.execute(
                "SELECT restore_epoch,coverage_revision,sequence FROM source_state WHERE owner=? AND source_id=?",
                (owner, source_id),
            ).fetchone()
            sequence = 1 if current is None else current[2]
            if current is not None and (current[0] != restore_epoch or current[1] != coverage_revision):
                sequence += 1
            existing = {row[0]: (row[1], row[2]) for row in self.db.execute(
                "SELECT session_id,source_revision,metadata FROM indexed_sessions WHERE owner=? AND source_id=?",
                (owner, source_id),
            )}
            required_changes = set(changed)
            for session_id, item in session_map.items():
                metadata = _canonical(item).decode("utf-8")
                prior = existing.get(session_id)
                if current is None or current[0] != restore_epoch or prior is None or prior != (item["source_revision"], metadata):
                    required_changes.add(session_id)
            if current is not None and current[0] == restore_epoch and current[1] == coverage_revision:
                for session_id, item in session_map.items():
                    metadata = _canonical(item).decode("utf-8")
                    prior = existing.get(session_id)
                    if prior is None or prior != (item["source_revision"], metadata):
                        required_changes.add(session_id)
            if not required_changes.issubset(changed):
                raise ValueError("full session reconciliation required after index loss or revision mismatch")
            if current is None or current[0] != restore_epoch:
                if set(changed) != set(session_map):
                    raise ValueError("full session reconciliation required for a new source epoch")
            changed = required_changes
            self.db.execute("DELETE FROM indexed_sessions WHERE owner=? AND source_id=?", (owner, source_id))
            self.db.executemany(
                "INSERT INTO indexed_sessions(owner,source_id,session_id,source_revision,metadata) VALUES(?,?,?,?,?)",
                [(owner, source_id, item["session_id"], item["source_revision"], _canonical(item).decode("utf-8")) for item in sessions],
            )
            removed = set(existing) - set(session_map)
            for session_id in removed:
                self.db.execute("DELETE FROM document_fts WHERE owner=? AND source_id=? AND message_id IN (SELECT message_id FROM documents WHERE owner=? AND source_id=? AND session_id=?)", (owner, source_id, owner, source_id, session_id))
                self.db.execute("DELETE FROM documents WHERE owner=? AND source_id=? AND session_id=?", (owner, source_id, session_id))
            for session_id in changed:
                self.db.execute("DELETE FROM document_fts WHERE owner=? AND source_id=? AND message_id IN (SELECT message_id FROM documents WHERE owner=? AND source_id=? AND session_id=?)", (owner, source_id, owner, source_id, session_id))
                self.db.execute("DELETE FROM documents WHERE owner=? AND source_id=? AND session_id=?", (owner, source_id, session_id))
                if self._reconcile_test_hook is not None:
                    self._reconcile_test_hook(session_id)
                session_records = grouped.get(session_id, [])
                self.db.executemany(
                    "INSERT INTO documents(owner,source_id,session_id,message_id,parent_session_id,speaker,source_order,created_at,restore_epoch,revision,body,parts,is_summary_message,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(owner, source_id, r["session_id"], r["message_id"], r.get("parent_session_id", ""),
                      r["speaker"], r["source_order"], r["created_at"], restore_epoch, r["revision"], r["body"],
                      json.dumps(r["parts"], separators=(",", ":")), int(bool(r.get("is_summary_message", False))),
                      int(r["source_revision"])) for r in session_records],
                )
                self.db.executemany(
                    "INSERT INTO document_fts(owner,source_id,message_id,body) VALUES(?,?,?,?)",
                    [(owner, source_id, r["message_id"], r["body"]) for r in session_records if r["body"]],
                )
            self.db.execute(
                "INSERT INTO source_state(owner,source_id,restore_epoch,coverage_revision,sequence) VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,source_id) DO UPDATE SET restore_epoch=excluded.restore_epoch,coverage_revision=excluded.coverage_revision,sequence=excluded.sequence",
                (owner, source_id, restore_epoch, coverage_revision, sequence),
            )
        return sequence

    def page_session(self, owner: str, source_id: str, restore_epoch: str,
                     coverage_revision: str, sequence: int, session_id: str,
                     limit: int, cursor: str | None,
                     start_message_id: str | None = None) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        if not 1 <= limit <= 50:
            raise ValueError("page limit must be from 1 to 50")
        expected = {"principal": owner, "source_id": source_id,
                    "restore_epoch": restore_epoch, "coverage_revision": coverage_revision,
                    "sequence": sequence, "session_id": session_id,
                    "start_message_id": start_message_id or "", "view": "session"}
        if cursor:
            offset = _read_cursor(self.cursor_key, cursor, expected)
        elif start_message_id:
            anchor = self.db.execute(
                "SELECT source_order FROM documents WHERE owner=? AND source_id=? AND session_id=? AND message_id=?",
                (owner, source_id, session_id, start_message_id),
            ).fetchone()
            if anchor is None:
                return {"status": "changed", "messages": [], "next_cursor": None,
                        "query_complete": False, "source_fresh": True}
            offset = self.db.execute(
                "SELECT COUNT(*) FROM documents WHERE owner=? AND source_id=? AND session_id=? AND source_order<?",
                (owner, source_id, session_id, anchor[0]),
            ).fetchone()[0]
        else:
            offset = 0
        state = self.db.execute(
            "SELECT restore_epoch,coverage_revision,sequence FROM source_state WHERE owner=? AND source_id=?",
            (owner, source_id),
        ).fetchone()
        if state is None or tuple(state) != (restore_epoch, coverage_revision, sequence):
            return {"status": "changed", "messages": [], "next_cursor": None,
                    "query_complete": False, "source_fresh": False}
        rows = self.db.execute(
            "SELECT message_id,session_id,parent_session_id,speaker,source_order,created_at,revision,body,parts "
            "FROM documents WHERE owner=? AND source_id=? AND session_id=? "
            "ORDER BY source_order,message_id LIMIT ? OFFSET ?",
            (owner, source_id, session_id, limit + 1, offset),
        ).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        messages = []
        byte_count = 0
        for row in rows:
            item = dict(row)
            item["parts"] = json.loads(item["parts"])
            item_bytes = len(json.dumps(item, separators=(",", ":")).encode("utf-8"))
            if byte_count + item_bytes > MAX_PAGE_BYTES:
                more = True
                break
            byte_count += item_bytes
            messages.append(item)
        next_cursor = None
        if more:
            next_cursor = _signed_cursor(self.cursor_key, expected | {"offset": offset + len(messages)})
        return {"status": "ok", "messages": messages, "next_cursor": next_cursor,
                "payload_bytes": byte_count, "start_message_id": start_message_id or "",
                "query_complete": not more, "source_fresh": True,
                "source_id": source_id, "restore_epoch": restore_epoch,
                "coverage_revision": coverage_revision, "source_sequence": sequence}

    def search(self, owner: str, source_id: str, restore_epoch: str, coverage_revision: str,
               sequence: int, query: str, limit: int, cursor: str | None,
               session_id: str | None = None, roles: list[str] | None = None,
               after: int | None = None, before: int | None = None,
               exclude_current_session: bool = False, current_session_id: str = "",
               include_tools: bool = False, include_summaries: bool = False) -> dict[str, Any]:
        if not query or len(query) > MAX_QUERY:
            raise ValueError("query must contain 1..512 characters")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError("result limit must be from 1 to 20")
        selected_roles = sorted(set(roles)) if roles else (["assistant", "tool", "user"] if include_tools else ["assistant", "user"])
        filters = {"session_id": session_id or "", "roles": selected_roles, "after": after or 0,
                   "before": before or 0, "exclude_current_session": bool(exclude_current_session),
                   "current_session_id": current_session_id, "include_tools": bool(include_tools),
                   "include_summaries": bool(include_summaries)}
        expected = {"principal": owner, "source_id": source_id, "restore_epoch": restore_epoch,
                    "coverage_revision": coverage_revision, "sequence": sequence,
                    "query_hash": hashlib.sha256(query.encode()).hexdigest(),
                    "filters_hash": hashlib.sha256(_canonical(filters)).hexdigest(), "view": "search"}
        offset = _read_cursor(self.cursor_key, cursor, expected) if cursor else 0
        filter_sql = []
        filter_params: list[Any] = []
        if session_id:
            filter_sql.append("d.session_id=?")
            filter_params.append(session_id)
        if selected_roles:
            filter_sql.append("d.speaker IN (" + ",".join("?" for _ in selected_roles) + ")")
            filter_params.extend(selected_roles)
        if after:
            filter_sql.append("d.created_at>=?")
            filter_params.append(after)
        if before:
            filter_sql.append("d.created_at<?")
            filter_params.append(before)
        if exclude_current_session and current_session_id:
            filter_sql.append("d.session_id<>?")
            filter_params.append(current_session_id)
        if not include_summaries:
            filter_sql.append("d.is_summary_message=0")
        filter_clause = "".join(" AND " + condition for condition in filter_sql)
        phrase = len(query) >= 2 and query.startswith('"') and query.endswith('"')
        search_query = query[1:-1] if phrase else query
        terms = tokenize(search_query)
        literal = not terms or (not phrase and (not search_query.isascii() or bool(re.search(r"[^a-zA-Z0-9\s]", search_query)) or any(len(term) < 2 for term in terms)))
        if literal:
            page = self.db.execute(
                "SELECT d.message_id,d.session_id,d.parent_session_id,d.speaker,d.source_order,d.created_at,d.revision,d.body,d.is_summary_message,d.source_revision,0.0 AS score "
                "FROM documents d WHERE d.owner=? AND d.source_id=? " + filter_clause + " AND instr(lower(d.body),lower(?))>0 "
                "ORDER BY d.created_at,d.source_order,d.message_id LIMIT ? OFFSET ?",
                (owner, source_id, *filter_params, search_query, limit + 1, offset),
            ).fetchall()
            route = "bounded_literal"
        else:
            match = '"' + " ".join(terms) + '"' if phrase else " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
            page = self.db.execute(
                "SELECT d.message_id,d.session_id,d.parent_session_id,d.speaker,d.source_order,d.created_at,d.revision,d.body,d.is_summary_message,d.source_revision,bm25(document_fts) AS score "
                "FROM document_fts JOIN documents d ON d.owner=document_fts.owner AND d.source_id=document_fts.source_id AND d.message_id=document_fts.message_id "
                "WHERE document_fts.owner=? AND document_fts.source_id=? AND document_fts MATCH ? " + filter_clause + " "
                "ORDER BY score,d.created_at,d.source_order,d.message_id LIMIT ? OFFSET ?",
                (owner, source_id, match, *filter_params, limit + 1, offset),
            ).fetchall()
            route = "ember_fts5_phrase" if phrase else "ember_fts5+bm25"
        more = len(page) > limit
        page = page[:limit]
        next_cursor = None
        if more:
            next_cursor = _signed_cursor(self.cursor_key, expected | {"offset": offset + limit})
        by_session_order = {}
        for row in page:
            preceding = self.db.execute(
                "SELECT message_id,speaker,body FROM documents WHERE owner=? AND source_id=? AND session_id=? AND source_order<? ORDER BY source_order DESC,message_id DESC LIMIT 1",
                (owner, source_id, row["session_id"], row["source_order"]),
            ).fetchone()
            by_session_order[row["message_id"]] = preceding
        results = []
        for row in page:
            item = dict(row)
            item["is_summary_message"] = bool(item.get("is_summary_message", False))
            score = item.pop("score", 0.0)
            body = item.pop("body", "")
            excerpt_query = search_query if literal or phrase else terms[0]
            excerpt_match = re.search(re.escape(excerpt_query), body, re.IGNORECASE)
            if excerpt_match:
                excerpt_start = max(0, excerpt_match.start() - 80)
                excerpt_end = min(len(body), excerpt_match.end() + 80)
                item["matched_excerpt"] = ("…" if excerpt_start else "") + body[excerpt_start:excerpt_end] + ("…" if excerpt_end < len(body) else "")
            else:
                item["matched_excerpt"] = body[:160]
            preceding = by_session_order.get(row["message_id"])
            item["preceding_preview"] = None
            if preceding is not None:
                item["preceding_preview"] = {
                    "message_id": preceding["message_id"],
                    "role": preceding["speaker"],
                    "text": preceding["body"][:100],
                }
            item["score"] = score
            item["source_id"] = source_id
            item["restore_epoch"] = restore_epoch
            item["coverage_revision"] = coverage_revision
            item["source_sequence"] = sequence
            results.append(item)
        groups_by_session: dict[str, dict[str, Any]] = {}
        for item in results:
            group = groups_by_session.setdefault(item["session_id"], {
                "session_id": item["session_id"],
                "parent_session_id": item["parent_session_id"],
                "results": [],
            })
            group["results"].append(item)
        return {"results": results, "groups": list(groups_by_session.values()),
                "next_cursor": next_cursor, "query_complete": True,
                "query_status": "ok", "source_fresh": True,
                "source_id": source_id, "restore_epoch": restore_epoch,
                "coverage_revision": coverage_revision, "source_sequence": sequence,
                "retrieval_route": route}

    def open(self, owner: str, source_id: str, restore_epoch: str, sequence: int,
             session_id: str, message_id: str, expected_revision: str,
             before: int = 0, after: int = 0) -> dict[str, Any]:
        state = self.db.execute("SELECT restore_epoch,coverage_revision,sequence FROM source_state WHERE owner=? AND source_id=?",
                                (owner, source_id)).fetchone()
        if state is None or state[0] != restore_epoch or state[2] != sequence:
            return {"status": "changed", "text": None}
        row = self.db.execute("SELECT * FROM documents WHERE owner=? AND source_id=? AND session_id=? AND message_id=?",
                              (owner, source_id, session_id, message_id)).fetchone()
        if row is None or row["revision"] != expected_revision:
            return {"status": "changed", "text": None}
        if not 0 <= before <= 20 or not 0 <= after <= 20:
            raise ValueError("before and after must be from 0 to 20")
        result = {"status": "ok", "source_id": source_id, "restore_epoch": restore_epoch,
                  "coverage_revision": state[1], "source_sequence": sequence, "session_id": session_id, "message_id": message_id,
                  "speaker": row["speaker"], "created_at": row["created_at"],
                  "revision": row["revision"], "parts": json.loads(row["parts"]),
                  "source_revision": row["source_revision"],
                  "text_convention": "canonical-message-parts-binary-payloads-omitted-v1"}
        if before or after:
            rows = self.db.execute(
                "SELECT message_id,session_id,parent_session_id,speaker,source_order,created_at,revision,body,parts,source_revision "
                "FROM documents WHERE owner=? AND source_id=? AND session_id=? AND source_order BETWEEN ? AND ? "
                "ORDER BY source_order,message_id",
                (owner, source_id, session_id, max(0, row["source_order"] - before), row["source_order"] + after),
            ).fetchall()
            messages = []
            payload_bytes = 0
            continuation = None
            for neighbor in rows:
                item = dict(neighbor)
                item["parts"] = json.loads(item["parts"])
                encoded = _canonical(item)
                if payload_bytes + len(encoded) > MAX_PAGE_BYTES:
                    continuation = item["message_id"]
                    break
                payload_bytes += len(encoded)
                messages.append(item)
            result.update({"messages": messages, "context_complete": continuation is None,
                           "context_payload_bytes": payload_bytes})
            if continuation is not None:
                result["context_continuation"] = {"start_message_id": continuation}
        return result


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
            source_id, restore_epoch, coverage_revision, records, sessions, changed_sessions = service._validated_snapshot(request)
            sequence = service.reconcile_incremental(owner, source_id, restore_epoch, coverage_revision,
                                                     sessions, changed_sessions, records)
            operation = request.get("operation")
            if operation == "search":
                result = service.search(
                    owner, source_id, restore_epoch, coverage_revision, sequence,
                    request.get("query", ""), request.get("limit", 10), request.get("cursor"),
                    request.get("session_filter"), request.get("roles"), request.get("after"),
                    request.get("before"), request.get("exclude_current_session", True),
                    request.get("current_session_id", ""), request.get("include_tools", False),
                    request.get("include_summaries", False),
                )
            elif operation == "open":
                result = service.open(owner, source_id, restore_epoch, sequence, request.get("session_id", ""),
                                     request.get("message_id", ""), request.get("expected_revision", ""),
                                     request.get("before", 0), request.get("after", 0))
            elif operation == "page":
                result = service.page_session(owner, source_id, restore_epoch, coverage_revision, sequence,
                                              request.get("session_id", ""), request.get("limit", 20),
                                              request.get("cursor"), request.get("start_message_id"))
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
