import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ember_memory.firecore import FireCoreService


def session(session_id, revision, title=None):
    return {
        "session_id": session_id,
        "source_revision": revision,
        "parent_session_id": "",
        "title": title or session_id,
        "created_at": 100,
        "updated_at": 100,
        "message_count": 0,
        "generation": "",
        "generation_revision": 0,
    }


def record(owner, source, epoch, session_id, message_id, text, order, source_revision):
    return {
        "owner": owner,
        "source_id": source,
        "restore_epoch": epoch,
        "source_revision": source_revision,
        "message_id": message_id,
        "session_id": session_id,
        "parent_session_id": "",
        "speaker": "user",
        "source_order": order,
        "created_at": 100 + order,
        "revision": f"rev-{message_id}",
        "body": text,
        "parts": [{"kind": "text", "text": text}],
        "is_summary_message": False,
    }


class IncrementalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "index.sqlite")
        self.owner = "owner-a"
        self.source = "forge-local:incremental"
        self.epoch = "restore-1"
        self.service = FireCoreService(self.path)

    def tearDown(self):
        try:
            self.service.close()
        except Exception:
            pass
        self.temp.cleanup()

    def test_changed_session_delta_and_removed_session_reconcile_atomically(self):
        sessions = [session("s1", 1), session("s2", 1)]
        initial = [
            record(self.owner, self.source, self.epoch, "s1", "a", "old alpha", 0, 1),
            record(self.owner, self.source, self.epoch, "s1", "b", "deleted alpha", 1, 1),
            record(self.owner, self.source, self.epoch, "s2", "c", "stable beta", 0, 1),
        ]
        first_sequence = self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-1", sessions,
            ["s1", "s2"], initial,
        )
        new_sessions = [session("s1", 2), session("s2", 1)]
        delta = [record(self.owner, self.source, self.epoch, "s1", "a", "edited gamma", 0, 2)]
        second_sequence = self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-2", new_sessions,
            ["s1"], delta,
        )
        self.assertGreater(second_sequence, first_sequence)
        alpha = self.service.search(
            self.owner, self.source, self.epoch, "coverage-2", second_sequence, "alpha", 10, None,
            exclude_current_session=False,
        )
        self.assertEqual(alpha["results"], [])
        gamma = self.service.search(
            self.owner, self.source, self.epoch, "coverage-2", second_sequence, "gamma", 10, None,
            exclude_current_session=False,
        )
        self.assertEqual([row["message_id"] for row in gamma["results"]], ["a"])
        without_s2 = self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-3", [session("s1", 2)], [], [],
        )
        stable = self.service.search(
            self.owner, self.source, self.epoch, "coverage-3", without_s2, "beta", 10, None,
            exclude_current_session=False,
        )
        self.assertEqual(stable["results"], [])

    def test_omitted_changed_session_fails_closed(self):
        sessions = [session("s1", 2)]
        with self.assertRaisesRegex(ValueError, "full session reconciliation required"):
            self.service.reconcile_incremental(
                self.owner, self.source, self.epoch, "coverage-omitted", sessions, [],
                [],
            )

    def test_killed_subprocess_mid_transaction_rolls_back_and_full_retry_recovers(self):
        sessions = [session("s1", 1)]
        seed = [record(self.owner, self.source, self.epoch, "s1", "a", "old alpha", 0, 1)]
        self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-1", sessions, ["s1"], seed
        )
        self.service.close()
        marker = Path(self.temp.name) / "inside-transaction"
        child = r'''
import sys, time
from pathlib import Path
from ember_memory.firecore import FireCoreService
path, marker = sys.argv[1:]
service = FireCoreService(path)
def pause(session_id):
    Path(marker).write_text(session_id, encoding="utf-8")
    while True:
        time.sleep(1)
service._reconcile_test_hook = pause
record = {"owner":"owner-a","source_id":"forge-local:incremental","restore_epoch":"restore-1",
          "source_revision":2,"message_id":"a","session_id":"s1","parent_session_id":"",
          "speaker":"user","source_order":0,"created_at":100,"revision":"rev-a2",
          "body":"new gamma","parts":[{"kind":"text","text":"new gamma"}],"is_summary_message":False}
service.reconcile_incremental("owner-a","forge-local:incremental","restore-1","coverage-2",
    [{"session_id":"s1","source_revision":2,"parent_session_id":"","title":"s1","created_at":100,
      "updated_at":100,"message_count":1,"generation":"","generation_revision":0}],
    ["s1"], [record])
'''
        process = subprocess.Popen([sys.executable, "-c", child, self.path, str(marker)])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not marker.exists() and process.poll() is None:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), "subprocess did not reach the in-transaction checkpoint")
        process.terminate()
        process.wait(timeout=10)

        self.service = FireCoreService(self.path)
        sequence = self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-1", sessions, ["s1"], seed
        )
        old = self.service.search(
            self.owner, self.source, self.epoch, "coverage-1", sequence, "alpha", 10, None,
            exclude_current_session=False,
        )
        self.assertEqual([row["message_id"] for row in old["results"]], ["a"])
        self.assertEqual(old["results"][0]["matched_excerpt"], "old alpha")
        newer = [session("s1", 2)]
        recovered = self.service.reconcile_incremental(
            self.owner, self.source, self.epoch, "coverage-2", newer, ["s1"],
            [record(self.owner, self.source, self.epoch, "s1", "a", "new gamma", 0, 2)],
        )
        self.assertEqual(self.service.search(
            self.owner, self.source, self.epoch, "coverage-2", recovered, "alpha", 10, None,
            exclude_current_session=False,
        )["results"], [])
        self.assertEqual([row["message_id"] for row in self.service.search(
            self.owner, self.source, self.epoch, "coverage-2", recovered, "gamma", 10, None,
            exclude_current_session=False,
        )["results"]], ["a"])


if __name__ == "__main__":
    unittest.main()
