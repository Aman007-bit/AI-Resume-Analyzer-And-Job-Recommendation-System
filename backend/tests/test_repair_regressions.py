"""Focused offline repair regressions. All persistence boundaries are mocked."""
import os
import unittest
from unittest.mock import Mock, patch

import db
from fastapi import HTTPException
from routers import auth_routes


class ConfigurationRepairTests(unittest.TestCase):
    def environment(self):
        return {
            'DB_STAGING_GUARD': 'true', 'DB_HOST': '127.0.0.1',
            'DB_PORT': '33309', 'DB_EXPECTED_PORT': '33309',
            'DB_NAME': 'resume_analyzer_restore_test',
            'DB_EXPECTED_DATA_DIR': os.path.abspath('offline-fixture-data'),
            'DB_EXPECTED_SERVER_UUID': 'offline-fixture-uuid',
            'DB_USER': 'offline-user', 'DB_PASSWORD': 'offline-only',
        }

    def test_missing_or_unsafe_settings_never_call_connector(self):
        variants = [{}, {'DB_HOST': 'localhost'}, {'DB_PORT': '3306'},
                    {'DB_PORT': '33308'}, {'DB_NAME': 'resume_analyzer'},
                    {'DB_STAGING_GUARD': 'false'}, {'DB_EXPECTED_PORT': '33308'},
                    {'DB_EXPECTED_SERVER_UUID': ''}, {'DB_EXPECTED_DATA_DIR': 'relative'}]
        for overrides in variants:
            env = self.environment() if overrides else {}
            env.update(overrides)
            with self.subTest(case=list(overrides)), patch.dict(os.environ, env, clear=True), patch('db.mysql.connector.connect') as connect:
                self.assertIsNone(db.get_db_connection())
                connect.assert_not_called()

    def test_identity_mismatch_closes_connection(self):
        connection = Mock()
        connection.cursor.return_value.fetchone.return_value = ('wrong-database', 33309, 'wrong', 'wrong')
        with patch.dict(os.environ, self.environment(), clear=True), patch('db.mysql.connector.connect', return_value=connection):
            self.assertIsNone(db.get_db_connection())
        connection.close.assert_called_once()

    def test_matching_identity_returns_guarded_connection(self):
        env = self.environment()
        connection = Mock()
        connection.cursor.return_value.fetchone.return_value = (env['DB_NAME'], 33309, env['DB_EXPECTED_DATA_DIR'], env['DB_EXPECTED_SERVER_UUID'])
        with patch.dict(os.environ, env, clear=True), patch('db.mysql.connector.connect', return_value=connection) as connect:
            self.assertIsInstance(db.get_db_connection(), db._StagingGuardConnection)
        self.assertEqual(connect.call_args.kwargs['port'], 33309)

    def test_invalid_jwt_settings_prevent_registration(self):
        payload = auth_routes.RegistrationRequest(name='Offline', email='offline@example.com', password='offline-password')
        for env in ({'JWT_SECRET_KEY': ''}, {'JWT_SECRET_KEY': 'x' * 32, 'JWT_EXPIRE_MINUTES': 'invalid'}):
            with patch.dict(os.environ, env, clear=True), patch.object(auth_routes, 'register_user') as register:
                with self.assertRaises(HTTPException) as error:
                    auth_routes.register(payload)
                self.assertEqual(error.exception.status_code, 503)
                register.assert_not_called()

    def test_valid_jwt_settings_preserve_registration_response(self):
        user = {'id': 1, 'name': 'Offline', 'email': 'offline@example.com'}
        payload = auth_routes.RegistrationRequest(name=user['name'], email=user['email'], password='offline-password')
        with patch.dict(os.environ, {'JWT_SECRET_KEY': 'x' * 32}, clear=True), patch.object(auth_routes, 'register_user', return_value=user), patch.object(auth_routes, 'create_access_token', return_value='offline-token'):
            self.assertEqual(auth_routes.register(payload), {'access_token': 'offline-token', 'user': user})


class SkillAndRecommendationRepairTests(unittest.TestCase):
    def normalized(self, description, authorized=True):
        from services import job_ingestion_service as ingestion
        return ingestion._normalized_source_job('fixture', 'https://example.com/job', 'Engineer', 'Example', None, description, None, extract_skill_terms=authorized)

    def test_authoritative_empty_skills_clear_mappings_and_requirements(self):
        from services import job_ingestion_service as ingestion
        from tests.test_job_identity_upsert import RecordingCursor
        job = self.normalized('Manage inventory')
        self.assertEqual(job['skills'], [])
        cursor = RecordingCursor(existing={'id': 7})
        ingestion._sync_job(cursor, job, source_name='USAJOBS')
        self.assertIn(('DELETE FROM job_skills WHERE job_id = %s', (7,)), cursor.statements)
        self.assertIn(('UPDATE jobs SET requirements = NULL WHERE id = %s', (7,)), cursor.statements)

    def test_missing_blank_and_unauthorized_data_preserve_skills(self):
        from services import job_ingestion_service as ingestion
        from tests.test_job_identity_upsert import RecordingCursor
        for description, authorized in ((None, True), ('', True), ('   ', True), ('Python', False)):
            with self.subTest(description=description, authorized=authorized):
                job = self.normalized(description, authorized)
                self.assertIsNone(job['skills'])
                cursor = RecordingCursor(existing={'id': 7})
                ingestion._sync_job(cursor, job, source_name='USAJOBS')
                self.assertFalse(any('DELETE FROM job_skills' in sql for sql, _ in cursor.statements))

    def test_new_recognized_skills_replace_mappings(self):
        from services import job_ingestion_service as ingestion
        from tests.test_job_identity_upsert import RecordingCursor
        job = self.normalized('Python')
        self.assertEqual(job['skills'], ['Python'])
        cursor = RecordingCursor(existing={'id': 7})
        ingestion._sync_job(cursor, job, source_name='USAJOBS')
        self.assertTrue(any('INSERT IGNORE INTO job_skills' in sql for sql, _ in cursor.statements))

    def recommendations(self, rows):
        from services import recommendation_service as recommendations
        from tests.test_auth import FakeCursor, FakeConnection
        cursor = FakeCursor(rows=[{'user_id': 1, 'extracted_text': 'Python'}], collections=[[{'id': 1, 'name': 'Python'}], rows])
        connection = FakeConnection(cursor)
        with patch.object(recommendations, 'get_db_connection', return_value=connection), patch.object(recommendations, 'calculate_tfidf_cosine_scores', side_effect=lambda resume, descriptions: [0.0] * len(descriptions)):
            result = recommendations.build_job_recommendations(1, 1)
        self.assertFalse(any('INSERT INTO recommendations' in sql for sql, _ in cursor.queries))
        return result['availability']['status']

    def row(self, **overrides):
        row = dict(job_id=1, title='Inventory', company='Example', location=None, description='Manage inventory', source_name='USAJOBS', source_url='https://example.com/job', skill_id=None, skill_name=None)
        row.update(overrides)
        return row

    def test_complete_unrelated_data_means_no_relevant_matches(self):
        self.assertEqual(self.recommendations([self.row()]), 'no_relevant_matches')
        self.assertEqual(self.recommendations([self.row(description=None, skill_id=2, skill_name='Java')]), 'no_relevant_matches')

    def test_no_signals_means_data_unavailable(self):
        self.assertEqual(self.recommendations([self.row(description=None)]), 'job_skill_data_unavailable')

    def test_empty_and_unauthorized_datasets_remain_distinct(self):
        self.assertEqual(self.recommendations([]), 'no_jobs_available')
        self.assertEqual(self.recommendations([self.row(source_name='Unrecognized')]), 'provider_authorization_required')


class SchedulerAndStatusRepairTests(unittest.TestCase):
    def test_sync_timeout_reports_unknown_without_retry(self):
        import requests
        from scheduled_job_sync import run_scheduled_sync
        http = Mock()
        http.post.side_effect = [Mock(status_code=200, json=lambda: {'access_token': 'offline-token'}), requests.ReadTimeout()]
        code, summary = run_scheduled_sync({'SYNC_ADMIN_EMAIL': 'offline@example.com', 'SYNC_ADMIN_PASSWORD': 'offline-only', 'SYNC_READ_TIMEOUT_SECONDS': '120'}, http=http)
        self.assertEqual(code, 3)
        self.assertEqual(summary, {'status': 'sync_outcome_unknown'})
        self.assertEqual(http.post.call_count, 2)
        self.assertEqual(http.post.call_args.kwargs['timeout'], (5, 120))

    def test_invalid_sync_timeout_never_requests(self):
        from scheduled_job_sync import run_scheduled_sync
        for value in ('0', '-1', '3601', 'invalid'):
            http = Mock()
            code, _ = run_scheduled_sync({'SYNC_ADMIN_EMAIL': 'offline@example.com', 'SYNC_ADMIN_PASSWORD': 'offline-only', 'SYNC_READ_TIMEOUT_SECONDS': value}, http=http)
            self.assertEqual(code, 1)
            http.post.assert_not_called()

    def test_existing_jla_status_contract_without_processing_permission(self):
        from services import job_ingestion_service as ingestion
        base = dict(id='fixture', title='Engineer', company='Example', url='https://example.com/job', description_html='Python')
        with patch.dict(os.environ, {'JLA_RECOMMENDATIONS_AUTHORIZED': 'false'}):
            removed = ingestion._parse_job_listings_api_job(dict(base, status='removed'))
            expired = ingestion._parse_job_listings_api_job(dict(base, valid_through='2000-01-01T00:00:00Z'))
            self.assertEqual(removed['status'], 'closed')
            self.assertEqual(expired['status'], 'expired')
            self.assertIsNone(expired['skills'])
            with self.assertRaises(ValueError):
                ingestion._parse_job_listings_api_job(dict(base, status='unrecognized'))
