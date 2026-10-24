import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes-long")

from services import job_ingestion_service as jis


class RecordingCursor:
    def __init__(self, existing=None):
        self.existing = existing
        self.statements = []
        self.lastrowid = 101
        self._result = None
        self._skill_lastrowid = 500
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.statements.append((normalized, params))
        upper = normalized.upper()
        if upper.startswith("SELECT ID FROM JOBS"):
            self._result = self.existing
        elif "INSERT INTO SKILLS" in upper:
            self._skill_lastrowid += 1
            self.lastrowid = self._skill_lastrowid
            self._result = None
        else:
            self._result = None

    def fetchone(self):
        return self._result

    def close(self):
        self.closed = True


def _sample_job(**overrides):
    job = {
        "title": "Backend Engineer",
        "company": "Example Co",
        "location": "Remote",
        "work_mode": "remote",
        "description": "Build APIs with Python",
        "requirements": "Python, FastAPI",
        "source_url": "https://example.com/jobs/1",
        "posted_at": datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        "source_job_id": "abc-123",
        "status": "open",
        "expires_at": None,
        "skills": ["Python"],
    }
    job.update(overrides)
    return job


class SourceIdentityValidationTests(unittest.TestCase):
    def test_source_id_rejects_none(self):
        with self.assertRaises(ValueError):
            jis._source_id(None)

    def test_source_id_rejects_blank(self):
        with self.assertRaises(ValueError):
            jis._source_id("   ")

    def test_source_id_strips_and_returns(self):
        self.assertEqual(jis._source_id("  job-42  "), "job-42")

    def test_sync_job_rejects_missing_source_job_id(self):
        cursor = RecordingCursor()
        job = _sample_job()
        del job["source_job_id"]
        with self.assertRaises(ValueError):
            jis._sync_job(cursor, job, source_name="remotive")
        self.assertEqual(cursor.statements, [])

    def test_sync_job_rejects_blank_source_job_id(self):
        cursor = RecordingCursor()
        with self.assertRaises(ValueError):
            jis._sync_job(cursor, _sample_job(source_job_id="  "), source_name="remotive")
        self.assertEqual(cursor.statements, [])

    def test_sync_job_rejects_blank_source_name(self):
        cursor = RecordingCursor()
        with self.assertRaises(ValueError):
            jis._sync_job(cursor, _sample_job(), source_name="  ")
        self.assertEqual(cursor.statements, [])

    def test_sync_job_inserts_when_identity_is_new(self):
        cursor = RecordingCursor(existing=None)
        job = _sample_job(source_job_id="  new-1  ")
        outcome = jis._sync_job(cursor, job, source_name=" remotive ")
        self.assertEqual(outcome, "inserted")
        select = cursor.statements[0]
        self.assertIn("SELECT id FROM jobs", select[0])
        self.assertEqual(select[1], ("remotive", "new-1"))
        insert = next(s for s in cursor.statements if s[0].upper().startswith("INSERT INTO JOBS"))
        self.assertEqual(insert[1][8], "remotive")
        self.assertEqual(insert[1][9], "new-1")

    def test_sync_job_updates_when_identity_exists(self):
        cursor = RecordingCursor(existing={"id": 7})
        outcome = jis._sync_job(cursor, _sample_job(title="Updated"), source_name="remotive")
        self.assertEqual(outcome, "updated")
        self.assertTrue(any(s[0].upper().startswith("UPDATE JOBS") for s in cursor.statements))
        self.assertFalse(any(s[0].upper().startswith("INSERT INTO JOBS") for s in cursor.statements))

    def test_repeated_sync_with_same_identity_does_not_insert_twice(self):
        class StatefulCursor(RecordingCursor):
            def __init__(self):
                super().__init__(existing=None)
                self.store = {}
                self._next_id = 50

            def execute(self, query, params=None):
                normalized = " ".join(query.split())
                self.statements.append((normalized, params))
                upper = normalized.upper()
                if upper.startswith("SELECT ID FROM JOBS"):
                    row = self.store.get((params[0], params[1]))
                    self._result = {"id": row["id"]} if row else None
                elif upper.startswith("INSERT INTO JOBS"):
                    job_id = self._next_id
                    self._next_id += 1
                    self.store[(params[8], params[9])] = {"id": job_id, "title": params[0]}
                    self.lastrowid = job_id
                    self._result = None
                elif upper.startswith("UPDATE JOBS"):
                    job_id = params[-1]
                    for row in self.store.values():
                        if row["id"] == job_id:
                            row["title"] = params[0]
                    self._result = None
                elif "INSERT INTO SKILLS" in upper:
                    self.lastrowid = 900
                    self._result = None
                else:
                    self._result = None

        cursor = StatefulCursor()
        first = jis._sync_job(cursor, _sample_job(title="One"), source_name="remotive")
        second = jis._sync_job(cursor, _sample_job(title="Two"), source_name="remotive")
        self.assertEqual(first, "inserted")
        self.assertEqual(second, "updated")
        self.assertEqual(len(cursor.store), 1)
        only = next(iter(cursor.store.values()))
        self.assertEqual(only["title"], "Two")


if __name__ == "__main__":
    unittest.main()
