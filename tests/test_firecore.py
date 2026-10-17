import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from ember_memory.firecore import FireCoreService, PROTOCOL, _signed_cursor, authenticated_request


def record(owner, source, message_id, text, order, revision="rev-1", restore="restore-1"):
    return {
        "owner": owner, "source_id": source, "restore_epoch": restore,
        "message_id": message_id, "session_id": "session-a", "parent_session_id": "",
        "speaker": "user", "source_order": order, "created_at": 100,
        "revision": revision, "body": text, "parts": [{"kind": "text", "text": text}],
    }


class FireCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = FireCoreService(str(Path(self.temp.name) / "index.sqlite"))
        self.owner = "owner-a"
        self.source = "forge-local:synthetic"
        self.records = [
            record(self.owner, self.source, "first", "same alpha text", 0),
            record(self.owner, self.source, "second", "same alpha text", 1),
            record("owner-b", self.source, "secret", "same alpha text", 0),
        ]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-1", self.records[:2])

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def search(self, query="alpha", limit=1, cursor=None, epoch="restore-1", coverage="coverage-1", sequence=None):
        return self.service.search(self.owner, self.source, epoch, coverage,
                                   self.sequence if sequence is None else sequence, query, limit, cursor)

    def test_deterministic_source_order_and_cursor_across_index_rebuild(self):
        first = self.search()
        self.assertEqual(first["results"][0]["message_id"], "first")
        self.assertTrue(first["query_complete"])
        self.assertTrue(first["next_cursor"])
        cursor = first["next_cursor"]
        second = self.search(cursor=cursor)
        self.assertEqual(second["results"][0]["message_id"], "second")
        self.assertEqual(second["results"][0]["source_order"], 1)
        with self.service.db:
            self.service.db.execute("DELETE FROM documents WHERE owner=?", (self.owner,))
            self.service.db.execute("DELETE FROM document_fts WHERE owner=?", (self.owner,))
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-1", self.records[:2])
        self.service.close()
        self.service = FireCoreService(str(Path(self.temp.name) / "index.sqlite"))
        rebuilt = self.search(cursor=cursor)
        self.assertEqual(rebuilt["results"][0]["message_id"], "second")
        self.assertEqual(rebuilt["source_sequence"], first["source_sequence"])

    def test_same_count_index_corruption_is_reconciled_without_sequence_drift(self):
        stable_sequence = self.sequence
        self.service.db.execute(
            "UPDATE documents SET message_id='corrupted-reference' WHERE owner=? AND source_id=? AND message_id='second'",
            (self.owner, self.source),
        )
        self.sequence = self.service.reconcile(
            self.owner, self.source, "restore-1", "coverage-1", self.records[:2]
        )
        self.assertEqual(self.sequence, stable_sequence)
        result = self.search(limit=10)
        self.assertEqual([row["message_id"] for row in result["results"]], ["first", "second"])

    def test_cursor_tamper_scope_and_oversized_offset_fail_closed(self):
        first = self.search()
        cursor = first["next_cursor"]
        payload, signature = cursor.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claims["offset"] = 10**9
        forged_payload = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
        with self.assertRaisesRegex(ValueError, "authentication"):
            self.search(cursor=forged_payload + "." + signature)
        with self.assertRaisesRegex(ValueError, "authentication"):
            self.search(cursor=cursor[:-1] + ("0" if cursor[-1] != "0" else "1"))
        filters = {"session_id": "", "roles": ["assistant", "user"], "after": 0,
                   "before": 0, "exclude_current_session": False, "current_session_id": "",
                   "include_tools": False, "include_summaries": False}
        expected = {"principal": self.owner, "source_id": self.source, "restore_epoch": "restore-1",
                    "coverage_revision": "coverage-1", "sequence": self.sequence,
                    "query_hash": hashlib.sha256(b"alpha").hexdigest(),
                    "filters_hash": hashlib.sha256(json.dumps(filters, sort_keys=True,
                        separators=(",", ":")).encode()).hexdigest(), "view": "search"}
        oversized = _signed_cursor(self.service.cursor_key, expected | {"offset": 10**9})
        with self.assertRaisesRegex(ValueError, "outside the bounded source"):
            self.search(cursor=oversized)
        with self.assertRaisesRegex(ValueError, "scope"):
            self.service.search(self.owner, self.source, "restore-2", "coverage-1", self.sequence, "alpha", 1, cursor)

    def test_source_restore_epoch_and_coverage_revision_advance_lifecycle(self):
        first = self.search()
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-2", "coverage-1", self.records[:2])
        with self.assertRaisesRegex(ValueError, "scope"):
            self.search(cursor=first["next_cursor"], epoch="restore-2", sequence=self.sequence)
        same_content_restored = self.service.open(self.owner, self.source, "restore-2", self.sequence,
                                                  "session-a", "first", "rev-1")
        self.assertEqual(same_content_restored["status"], "ok")
        new_records = [record(self.owner, self.source, "first", "edited alpha text", 0, revision="rev-2", restore="restore-2"),
                       record(self.owner, self.source, "second", "same alpha text", 1, restore="restore-2")]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-2", "coverage-2", new_records)
        changed = self.service.open(self.owner, self.source, "restore-2", self.sequence,
                                    "session-a", "first", "rev-1")
        self.assertEqual(changed["status"], "changed")
        self.assertIsNone(changed["text"])
        opened = self.service.open(self.owner, self.source, "restore-2", self.sequence,
                                   "session-a", "first", "rev-2")
        self.assertEqual(opened["text_convention"], "canonical-message-parts-binary-payloads-omitted-v1")
        self.assertEqual(opened["parts"][0]["text"], "edited alpha text")

    def test_owner_partition_and_literal_edge(self):
        result = self.search("same alpha text", limit=20)
        self.assertEqual([row["message_id"] for row in result["results"]], ["first", "second"])
        self.assertEqual(result["retrieval_route"], "ember_fts5+bm25")
        punctuation = [record(self.owner, self.source, "punct", "version v1.2 C++", 2)]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-3", self.records[:2] + punctuation)
        result = self.search("v1.2 C++", limit=20, coverage="coverage-3", sequence=self.sequence)
        self.assertEqual(result["retrieval_route"], "bounded_literal")
        self.assertEqual([row["message_id"] for row in result["results"]], ["punct"])

    def test_search_groups_results_and_includes_default_preceding_preview(self):
        result = self.search("alpha", limit=20)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["session_id"], "session-a")
        second = next(row for row in result["results"] if row["message_id"] == "second")
        self.assertIn("alpha", second["matched_excerpt"])
        self.assertEqual(second["preceding_preview"]["message_id"], "first")
        self.assertEqual(second["preceding_preview"]["role"], "user")
        self.assertEqual(second["preceding_preview"]["text"], "same alpha text")
        first = next(row for row in result["results"] if row["message_id"] == "first")
        self.assertIsNone(first["preceding_preview"])

    def test_session_paging_cursor_is_authenticated_and_advances(self):
        records = [
            record(self.owner, self.source, f"page-{index}", f"message {index}", index)
            for index in range(4)
        ]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-pages", records)
        first = self.service.page_session(self.owner, self.source, "restore-1", "coverage-pages",
                                          self.sequence, "session-a", 2, None)
        self.assertEqual([item["message_id"] for item in first["messages"]], ["page-0", "page-1"])
        self.assertFalse(first["query_complete"])
        second = self.service.page_session(self.owner, self.source, "restore-1", "coverage-pages",
                                           self.sequence, "session-a", 2, first["next_cursor"])
        self.assertEqual([item["message_id"] for item in second["messages"]], ["page-2", "page-3"])
        self.assertTrue(second["query_complete"])
        with self.assertRaisesRegex(ValueError, "authentication"):
            self.service.page_session(self.owner, self.source, "restore-1", "coverage-pages",
                                      self.sequence, "session-a", 2, first["next_cursor"][:-1] + "x")
        anchored = self.service.page_session(self.owner, self.source, "restore-1", "coverage-pages",
                                             self.sequence, "session-a", 1, None,
                                             start_message_id="page-2")
        self.assertEqual([item["message_id"] for item in anchored["messages"]], ["page-2"])
        self.assertEqual(anchored["start_message_id"], "page-2")
        anchored_next = self.service.page_session(
            self.owner, self.source, "restore-1", "coverage-pages", self.sequence,
            "session-a", 1, anchored["next_cursor"], start_message_id="page-2")
        self.assertEqual([item["message_id"] for item in anchored_next["messages"]], ["page-3"])

    def test_session_page_payload_stays_within_serialized_byte_cap(self):
        body = "alpha " * 30_000
        records = [record(self.owner, self.source, f"large-{index}", body, index)
                   for index in range(4)]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-large", records)
        page = self.service.page_session(self.owner, self.source, "restore-1", "coverage-large",
                                         self.sequence, "session-a", 4, None)
        self.assertLessEqual(page["payload_bytes"], 1_048_576)
        self.assertLess(len(page["messages"]), 4)
        self.assertFalse(page["query_complete"])
        self.assertTrue(page["next_cursor"])

    def test_failed_reconcile_rolls_back_without_losing_prior_index(self):
        self.service.db.execute(
            "CREATE TRIGGER reject_firecore_insert BEFORE INSERT ON documents "
            "BEGIN SELECT RAISE(ABORT, 'synthetic interrupted reconciliation'); END"
        )
        with self.assertRaisesRegex(Exception, "synthetic interrupted reconciliation"):
            self.service.reconcile(
                self.owner, self.source, "restore-1", "coverage-failed",
                [record(self.owner, self.source, "replacement", "replacement alpha", 0)],
            )
        self.service.db.execute("DROP TRIGGER reject_firecore_insert")
        result = self.service.search(self.owner, self.source, "restore-1", "coverage-1",
                                     self.sequence, "alpha", 10, None)
        self.assertEqual([row["message_id"] for row in result["results"]], ["first", "second"])

    def test_delete_reconcile_does_not_resurrect_old_content(self):
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-delete", [])
        result = self.service.search(self.owner, self.source, "restore-1", "coverage-delete",
                                     self.sequence, "alpha", 10, None)
        self.assertEqual(result["results"], [])
        self.assertTrue(result["source_fresh"])

    def test_search_filters_bind_current_session_roles_and_summaries(self):
        current = record(self.owner, self.source, "current", "alpha evidence", 0)
        current["session_id"] = "session-current"
        historical = record(self.owner, self.source, "historical", "alpha evidence", 0)
        historical["session_id"] = "session-history"
        tool = record(self.owner, self.source, "tool", "alpha evidence", 0)
        tool["speaker"] = "tool"
        summary = record(self.owner, self.source, "summary", "alpha evidence", 0)
        summary["is_summary_message"] = True
        records = [current, historical, tool, summary]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-filters", records)
        default = self.service.search(self.owner, self.source, "restore-1", "coverage-filters",
                                      self.sequence, "alpha", 10, None,
                                      exclude_current_session=True, current_session_id="session-current")
        self.assertEqual([row["message_id"] for row in default["results"]], ["historical"])
        expanded = self.service.search(self.owner, self.source, "restore-1", "coverage-filters",
                                       self.sequence, "alpha", 10, None,
                                       exclude_current_session=False, include_tools=True,
                                       include_summaries=True)
        self.assertEqual({row["message_id"] for row in expanded["results"]},
                         {"current", "historical", "tool", "summary"})
        self.assertTrue(any(row["is_summary_message"] for row in expanded["results"]))

    def test_quoted_queries_use_phrase_semantics(self):
        records = [
            record(self.owner, self.source, "phrase-forward", "alpha beta gamma", 0),
            record(self.owner, self.source, "phrase-reversed", "beta alpha gamma", 1),
        ]
        self.sequence = self.service.reconcile(self.owner, self.source, "restore-1", "coverage-phrase", records)
        broad = self.service.search(self.owner, self.source, "restore-1", "coverage-phrase",
                                    self.sequence, "alpha beta", 10, None)
        precise = self.service.search(self.owner, self.source, "restore-1", "coverage-phrase",
                                      self.sequence, '"alpha beta"', 10, None)
        self.assertEqual({row["message_id"] for row in broad["results"]},
                         {"phrase-forward", "phrase-reversed"})
        self.assertEqual([row["message_id"] for row in precise["results"]], ["phrase-forward"])
        self.assertEqual(precise["retrieval_route"], "ember_fts5_phrase")

    def test_authenticated_local_request(self):
        key = b"synthetic-key"
        payload = json.dumps({"protocol": PROTOCOL, "owner": self.owner}).encode()
        signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
        envelope = {"payload": base64.b64encode(payload).decode(), "signature": signature}
        self.assertEqual(authenticated_request(envelope, key.hex())["owner"], self.owner)
        with self.assertRaisesRegex(ValueError, "authentication"):
            authenticated_request(envelope, b"wrong-key".hex())


if __name__ == "__main__":
    unittest.main()
