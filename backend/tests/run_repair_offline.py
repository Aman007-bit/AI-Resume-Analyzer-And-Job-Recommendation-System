"""Focused repair selection with real network/database boundaries blocked."""
import os
import socket
import sys
import unittest
from unittest.mock import patch


def main(names=None):
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['JWT_SECRET_KEY'] = 'offline-test-signing-key-at-least-32-bytes'
    os.environ['JWT_EXPIRE_MINUTES'] = '60'
    for prefix in ('THE_MUSE', 'ARBEITNOW', 'LEVER', 'GREENHOUSE', 'JOBICY', 'JLA'):
        for use in ('INGESTION', 'RECOMMENDATIONS'):
            os.environ[f'{prefix}_{use}_AUTHORIZED'] = 'false'

    def blocked(*args, **kwargs):
        raise AssertionError('Live database/network access is forbidden in repair tests')

    with patch.object(socket, 'create_connection', blocked), patch('mysql.connector.connect', blocked), patch('requests.sessions.Session.request', blocked), patch('httpx.HTTPTransport.handle_request', blocked), patch('httpx.AsyncHTTPTransport.handle_async_request', blocked):
        default_selection = names is None
        names = names or [
            'tests.test_phase123_acceptance',
            'tests.test_repair_regressions', 'tests.test_db_target_guard',
            'tests.test_job_identity_upsert', 'tests.test_scheduled_job_sync',
            'tests.test_tfidf_recommendation', 'tests.test_recommendation_dedup',
            'tests.test_auth.AuthenticationTests', 'tests.test_auth.HealthEndpointTests',
            'tests.test_auth.ResumeOwnershipTests.test_other_users_resume_is_hidden',
            'tests.test_job_ingestion.JobIngestionTests.test_configured_source_sync_is_repeatable_and_updates_existing_rows',
            'tests.test_job_ingestion.JobIngestionTests.test_repeat_sync_updates_job_and_replaces_provider_skills',
            'tests.test_job_ingestion.JobIngestionTests.test_database_failure_rolls_back_only_failed_listing',
        ]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        from tests.test_resume_processing import ResumeProcessingTests
        for name in (unittest.defaultTestLoader.getTestCaseNames(ResumeProcessingTests) if default_selection else []):
            # This existing test temporarily enables a provider flag.
            if name != 'test_pdf_to_persisted_resume_through_real_recommendation_service':
                suite.addTest(ResumeProcessingTests(name))
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:] or None))
