import os
import unittest
from unittest.mock import patch

from db import (
    _StagingGuardConnection,
    verify_database_target,
)


class GuardCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, operation, *args, **kwargs):
        self.executed.append(operation)

    def executemany(self, operation, *args, **kwargs):
        self.executed.append(operation)

    def fetchone(self):
        return self.row

    def close(self):
        pass


class GuardConnection:
    def __init__(self, row):
        self.guard_cursor = GuardCursor(row)
        self.query_cursors = []

    def cursor(self, *args, **kwargs):
        cursor = GuardCursor(self.guard_cursor.row)
        self.query_cursors.append(cursor)
        return cursor


class DatabaseTargetGuardTests(unittest.TestCase):
    def staging_environment(self):
        return {
            "DB_STAGING_GUARD": "true",
            "DB_NAME": "resume_analyzer_restore_test",
            "DB_EXPECTED_PORT": "33309",
            "DB_EXPECTED_DATA_DIR": (
                r"C:\Users\dell\AppData\Local\AIResumeRestore\staging"
                r"-c9d0f709471544f8bab0b9eb1b6e62cf\data"
            ),
            "DB_EXPECTED_SERVER_UUID": "staging-uuid",
        }

    def matching_row(self):
        return (
            "resume_analyzer_restore_test",
            33309,
            r"C:\Users\dell\AppData\Local\AIResumeRestore\staging"
            r"-c9d0f709471544f8bab0b9eb1b6e62cf\data" + os.sep,
            "staging-uuid",
        )

    def test_target_check_accepts_exact_staging_identity(self):
        connection = GuardConnection(self.matching_row())

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            verify_database_target(connection)

        self.assertEqual(
            connection.query_cursors[0].executed,
            ["SELECT DATABASE(), @@port, @@datadir, @@server_uuid"],
        )

    def test_target_check_rejects_wrong_database_or_server(self):
        wrong_rows = [
            ("resume_analyzer", 33309, *self.matching_row()[2:]),
            ("resume_analyzer_restore_test", 3306, *self.matching_row()[2:]),
            (*self.matching_row()[:3], "different-uuid"),
        ]

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            for row in wrong_rows:
                with self.subTest(row=row):
                    with self.assertRaises(RuntimeError):
                        verify_database_target(GuardConnection(row))

    def test_missing_staging_identity_fails_closed(self):
        env = self.staging_environment()
        env.pop("DB_EXPECTED_SERVER_UUID")

        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                verify_database_target(GuardConnection(self.matching_row()))

    def test_guarded_cursor_checks_identity_before_writes_only(self):
        connection = GuardConnection(self.matching_row())
        wrapped = _StagingGuardConnection(connection)
        cursor = wrapped.cursor()

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            with patch("db.verify_database_target") as verify:
                cursor.execute("SELECT id FROM jobs")
                verify.assert_not_called()

                cursor.execute("UPDATE jobs SET status = %s", ("open",))
                verify.assert_called_once_with(connection)

                verify.reset_mock()
                cursor.executemany("INSERT INTO jobs (title) VALUES (%s)", [("x",)])
                verify.assert_called_once_with(connection)

    def test_guard_checks_before_ambiguous_read_prefixed_statements(self):
        connection = GuardConnection(self.matching_row())
        wrapped = _StagingGuardConnection(connection)
        cursor = wrapped.cursor()
        statements = (
            "WITH changed AS (SELECT 1) UPDATE jobs SET status = 'open'",
            "SELECT id FROM jobs; DELETE FROM jobs",
            "SELECT id FROM jobs INTO OUTFILE 'jobs.txt'",
            "SELECT id FROM jobs FOR UPDATE",
            "SELECT id FROM jobs LOCK IN SHARE MODE",
            "SELECT GET_LOCK('job-sync', 0)",
            "SELECT RELEASE_LOCK('job-sync')",
            "EXPLAIN ANALYZE UPDATE jobs SET status = 'open'",
            "/* write hidden behind a comment */ UPDATE jobs SET status = 'open'",
        )

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            for statement in statements:
                with self.subTest(statement=statement):
                    with patch("db.verify_database_target") as verify:
                        cursor.execute(statement)
                        verify.assert_called_once_with(connection)

    def test_identity_mismatch_aborts_write_before_cursor_execution(self):
        connection = GuardConnection(
            ("resume_analyzer", 33309, *self.matching_row()[2:])
        )
        wrapped = _StagingGuardConnection(connection)
        cursor = wrapped.cursor()

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            with patch(
                "db.verify_database_target", side_effect=RuntimeError("mismatch")
            ):
                with self.assertRaises(RuntimeError):
                    cursor.execute("UPDATE jobs SET status = 'open'")

        self.assertEqual(connection.query_cursors[0].executed, [])

    def test_non_string_statement_fails_closed_through_target_check(self):
        connection = GuardConnection(self.matching_row())
        wrapped = _StagingGuardConnection(connection)
        cursor = wrapped.cursor()

        with patch.dict(os.environ, self.staging_environment(), clear=False):
            with patch("db.verify_database_target") as verify:
                cursor.execute(object())
                verify.assert_called_once_with(connection)


if __name__ == "__main__":
    unittest.main()
