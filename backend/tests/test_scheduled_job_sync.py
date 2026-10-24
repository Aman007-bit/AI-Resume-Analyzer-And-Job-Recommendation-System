import unittest
from unittest.mock import Mock

from scheduled_job_sync import run_scheduled_sync


class ScheduledJobSyncTests(unittest.TestCase):
    def test_uses_existing_login_then_authenticated_sync_route(self):
        http = Mock()
        http.post.side_effect = [
            Mock(status_code=200, json=lambda: {"access_token": "test-token"}),
            Mock(status_code=200, json=lambda: {
                "processed": 4, "inserted": 1, "updated": 3, "skipped": 0,
                "failures": [], "sources": {"Job Listings API": {"status": "succeeded"}},
            }),
        ]
        code, summary = run_scheduled_sync({
            "SYNC_API_BASE_URL": "http://127.0.0.1:18082",
            "SYNC_ADMIN_EMAIL": "admin@example.com",
            "SYNC_ADMIN_PASSWORD": "secret-do-not-print",
        }, http=http)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(http.post.call_args_list[0].args[0],
                         "http://127.0.0.1:18082/api/auth/login")
        self.assertEqual(http.post.call_args_list[1].args[0],
                         "http://127.0.0.1:18082/api/admin/jobs/sync")
        self.assertEqual(http.post.call_args_list[1].kwargs["headers"],
                         {"Authorization": "Bearer test-token"})
        self.assertNotIn("secret-do-not-print", str(summary))

    def test_missing_credentials_fail_without_network_request(self):
        http = Mock()
        code, summary = run_scheduled_sync({}, http=http)
        self.assertEqual(code, 1)
        self.assertEqual(summary["status"], "configuration_error")
        http.post.assert_not_called()

    def test_admin_auth_failure_does_not_call_sync(self):
        http = Mock()
        http.post.return_value = Mock(status_code=401)
        code, summary = run_scheduled_sync({
            "SYNC_ADMIN_EMAIL": "admin@example.com",
            "SYNC_ADMIN_PASSWORD": "secret-do-not-print",
        }, http=http)
        self.assertEqual(code, 1)
        self.assertEqual(summary["status"], "authentication_failed")
        self.assertEqual(http.post.call_count, 1)

    def test_partial_sync_returns_nonzero_without_retrying_post(self):
        http = Mock()
        http.post.side_effect = [
            Mock(status_code=200, json=lambda: {"access_token": "test-token"}),
            Mock(status_code=200, json=lambda: {
                "processed": 0, "inserted": 0, "updated": 0, "skipped": 0,
                "failures": [{"source": "JLA"}], "sources": {},
            }),
        ]
        code, summary = run_scheduled_sync({
            "SYNC_ADMIN_EMAIL": "admin@example.com",
            "SYNC_ADMIN_PASSWORD": "secret-do-not-print",
        }, http=http)
        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(http.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
