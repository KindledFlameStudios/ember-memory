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
        expected = {"principal": self.owner, "source_id": self.source, "restore_epoch": "restore-1",
                    "coverage_revision": "coverage-1", "sequence": self.sequence,
                    "query_hash": hashlib.sha256(b"alpha").hexdigest(), "view": "search"}
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
