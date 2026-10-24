"""Phase 1–3 acceptance checks against transactional in-memory test doubles."""
import copy
import unittest
from unittest.mock import patch

import mysql.connector
from fastapi import HTTPException
from services import auth_service, resume_service
from tests.test_resume_processing import make_pdf


class TransactionStore:
    """Models pending/committed state; does not simulate MySQL isolation or durability."""
    def __init__(self, fail_sql=None, fail_commit=False):
        self.committed = {'users': {7: {'id': 7, 'name': 'Existing', 'email': 'existing@example.com'}}, 'resumes': {}, 'skills': {}, 'links': set()}
        self.pending = copy.deepcopy(self.committed)
        self.fail_sql = fail_sql
        self.fail_commit = fail_commit
        self.queries = []
        self.closed = False
        self.cursor_closed = False
        self.lastrowid = None
        self.result = None

    def cursor(self, **kwargs):
        return self

    def execute(self, query, params=None):
        sql = ' '.join(query.split())
        self.queries.append((sql, params))
        if self.fail_sql and self.fail_sql in sql:
            raise mysql.connector.Error('synthetic storage failure')
        if params is not None:
            assert sql.count('%s') == len(params)
        if sql.startswith('INSERT INTO users'):
            name, email, hashed = params
            if any(row['email'] == email for row in self.pending['users'].values()):
                raise mysql.connector.IntegrityError('synthetic duplicate')
            self.lastrowid = 8
            self.pending['users'][8] = dict(id=8, name=name, email=email, password_hash=hashed)
        elif sql.startswith('SELECT id, name, email, password_hash'):
            self.result = next((row for row in self.pending['users'].values() if row['email'] == params[0]), None)
        elif sql.startswith('SELECT id FROM users'):
            self.result = self.pending['users'].get(params[0])
        elif sql.startswith('INSERT INTO resumes'):
            self.lastrowid = 41
            self.pending['resumes'][41] = params
        elif sql.startswith('INSERT INTO skills'):
            name = params[0]
            self.lastrowid = self.pending['skills'].setdefault(name, len(self.pending['skills']) + 1)
        elif sql.startswith('INSERT IGNORE INTO resume_skills'):
            self.pending['links'].add(tuple(params))
        else:
            raise AssertionError('Unhandled fixture SQL')

    def fetchone(self):
        return self.result

    def commit(self):
        if self.fail_commit:
            raise mysql.connector.Error('synthetic commit failure before durability')
        self.committed = copy.deepcopy(self.pending)

    def rollback(self):
        self.pending = copy.deepcopy(self.committed)

    def close(self):
        self.closed = True
        self.cursor_closed = True


class Phase1AcceptanceTests(unittest.TestCase):
    def test_registration_commits_hash_and_login_checks_password(self):
        store = TransactionStore()
        with patch.object(auth_service, 'get_db_connection', return_value=store):
            user = auth_service.register_user('Candidate', 'candidate@example.com', 'offline-password')
            hashed = store.committed['users'][user['id']]['password_hash']
            self.assertNotEqual(hashed, 'offline-password')
            self.assertTrue(auth_service.verify_password('offline-password', hashed))
            self.assertEqual(auth_service.authenticate_user('candidate@example.com', 'offline-password'), user)
            with self.assertRaises(HTTPException) as raised:
                auth_service.authenticate_user('candidate@example.com', 'incorrect')
            self.assertEqual(raised.exception.status_code, 401)

    def test_duplicate_email_preserves_committed_state(self):
        store = TransactionStore()
        before = copy.deepcopy(store.committed)
        with patch.object(auth_service, 'get_db_connection', return_value=store):
            with self.assertRaises(HTTPException) as raised:
                auth_service.register_user('Candidate', 'existing@example.com', 'offline-password')
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(store.pending, before)
        self.assertEqual(store.committed, before)

    def test_same_display_name_is_allowed_by_existing_contract(self):
        store = TransactionStore()
        with patch.object(auth_service, 'get_db_connection', return_value=store):
            auth_service.register_user('Existing', 'different@example.com', 'offline-password')
        self.assertEqual(len(store.committed['users']), 2)

    def test_registration_execute_and_commit_failure_leave_no_account(self):
        for store in (TransactionStore(fail_sql='INSERT INTO users'), TransactionStore(fail_commit=True)):
            before = copy.deepcopy(store.committed)
            with self.subTest(fail_commit=store.fail_commit), patch.object(auth_service, 'get_db_connection', return_value=store):
                with self.assertRaises(HTTPException) as raised:
                    auth_service.register_user('Candidate', 'candidate@example.com', 'offline-password')
                self.assertEqual(raised.exception.status_code, 503)
                self.assertEqual(store.pending, before)
                self.assertEqual(store.committed, before)
                self.assertTrue(store.closed)

    def test_hashing_failure_is_safe_and_rolls_back(self):
        store = TransactionStore()
        before = copy.deepcopy(store.committed)
        with patch.object(auth_service, 'get_db_connection', return_value=store), patch.object(auth_service, 'hash_password', side_effect=RuntimeError('synthetic hashing failure')):
            with self.assertRaises(HTTPException) as raised:
                auth_service.register_user('Candidate', 'candidate@example.com', 'offline-password')
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(store.pending, before)
        self.assertEqual(store.committed, before)
        self.assertTrue(store.closed)


class Phase2AcceptanceTests(unittest.TestCase):
    def test_pdf_resume_and_unique_skill_links_commit_together(self):
        store = TransactionStore()
        with patch.object(resume_service, 'get_db_connection', return_value=store):
            result = resume_service.process_resume_upload(7, 'synthetic.pdf', make_pdf('Python python SQL'))
        self.assertEqual(set(result['skills_found']), {'Python', 'SQL'})
        self.assertEqual(len(store.committed['resumes']), 1)
        self.assertEqual(len(store.committed['links']), 2)
        self.assertEqual(set(store.committed['skills']), {'Python', 'SQL'})
        self.assertEqual(result['user_id'], 7)
        self.assertEqual(result['status'], 'completed')

    def test_skill_and_link_failures_restore_all_related_state(self):
        for sql in ('INSERT INTO skills', 'INSERT IGNORE INTO resume_skills'):
            store = TransactionStore(fail_sql=sql)
            before = copy.deepcopy(store.committed)
            with self.subTest(sql=sql), patch.object(resume_service, 'get_db_connection', return_value=store):
                with self.assertRaises(HTTPException):
                    resume_service.process_resume_upload(7, 'synthetic.pdf', make_pdf('Python SQL'))
            self.assertEqual(store.pending, before)
            self.assertEqual(store.committed, before)
            self.assertTrue(store.closed)

    def test_failed_resume_commit_restores_pending_state(self):
        store = TransactionStore(fail_commit=True)
        before = copy.deepcopy(store.committed)
        with patch.object(resume_service, 'get_db_connection', return_value=store):
            with self.assertRaises(HTTPException):
                resume_service.process_resume_upload(7, 'synthetic.pdf', make_pdf('Python'))
        self.assertEqual(store.pending, before)
        self.assertEqual(store.committed, before)

    def test_missing_user_does_not_create_resume(self):
        store = TransactionStore()
        with patch.object(resume_service, 'get_db_connection', return_value=store):
            with self.assertRaises(HTTPException) as raised:
                resume_service.process_resume_upload(999, 'synthetic.pdf', make_pdf('Python'))
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(store.committed['resumes'], {})

    def test_skill_normalization_combined_terms_and_deduplication(self):
        result = resume_service.extract_skills('Python PYTHON data structures and algorithms Natural Language Processing NLP time-management')
        self.assertEqual(result.count('Python'), 1)
        self.assertIn('Data Structures and Algorithms', result)
        self.assertNotIn('Data Structures', result)
        self.assertNotIn('Algorithms', result)
        self.assertIn('Natural Language Processing', result)
        self.assertNotIn('NLP', result)
        self.assertIn('Time Management', result)


class Phase3AcceptanceTests(unittest.TestCase):
    def setUp(self):
        from services import job_ingestion_service as ingestion
        from tests.test_job_ingestion import InMemoryDatabase
        self.ingestion = ingestion
        self.store = InMemoryDatabase()
        for target, value in (('get_db_connection', self.store), ('_require_staging_job_target', None)):
            mocked = patch.object(ingestion, target, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def job(self, description='Python', **overrides):
        job = self.ingestion._normalized_source_job('fixture-1', 'https://example.com/job', 'Engineer', 'Example', 'Remote', description, None)
        job.update(overrides)
        return job

    def sync(self, job, source='USAJOBS'):
        return self.ingestion._sync_source(source, [job], lambda record: record)

    def test_repeat_identity_updates_without_duplicate_and_refreshes_skills(self):
        self.assertEqual(self.sync(self.job())['inserted'], 1)
        self.assertEqual(self.sync(self.job('SQL', title='Updated'))['updated'], 1)
        self.assertEqual(len(self.store.jobs), 1)
        row = self.store.jobs[('USAJOBS', 'fixture-1')]
        self.assertEqual(row['title'], 'Updated')
        self.assertEqual(row['description'], 'SQL')
        self.assertEqual(self.store.links, {(row['id'], self.store.skills['SQL'])})

    def test_authoritative_empty_clears_links_and_requirements(self):
        self.sync(self.job())
        result = self.sync(self.job('Manage inventory'))
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.store.links, set())
        self.assertIsNone(self.store.jobs[('USAJOBS', 'fixture-1')]['requirements'])

    def test_missing_blank_and_unauthorized_preserve_mappings(self):
        self.sync(self.job())
        original = self.store.links.copy()
        for description, authorized in ((None, True), ('', True), ('  ', True), ('SQL', False)):
            job = self.ingestion._normalized_source_job('fixture-1', 'https://example.com/job', 'Engineer', 'Example', None, description, None, extract_skill_terms=authorized)
            self.assertEqual(self.sync(job)['updated'], 1)
            self.assertEqual(self.store.links, original)

    def test_distinct_sources_and_ids_do_not_collide(self):
        for source, identity in (('USAJOBS', 'same'), ('FixtureSource', 'same'), ('USAJOBS', 'other')):
            self.assertEqual(self.sync(self.job(source_job_id=identity), source)['inserted'], 1)
        self.assertEqual(len(self.store.jobs), 3)

    def test_failed_first_job_leaves_no_partial_job_skills_or_links(self):
        self.store.fail_on_skill = 'Python'
        result = self.sync(self.job())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(self.store.jobs, {})
        self.assertEqual(self.store.skills, {})
        self.assertEqual(self.store.links, set())

    def test_failed_update_restores_previous_job_and_skill_mappings(self):
        self.sync(self.job())
        original = self.store._state()
        self.store.fail_on_skill = 'SQL'
        result = self.sync(self.job('SQL', title='Should roll back'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.store._state(), original)

    def test_malformed_identity_rejected_and_sql_values_parameterized(self):
        from tests.test_job_identity_upsert import RecordingCursor
        for identity in (None, '', '  ', True, [], {}, 'x' * 256):
            cursor = RecordingCursor()
            with self.assertRaises(ValueError):
                self.ingestion._sync_job(cursor, self.job(source_job_id=identity), source_name='USAJOBS')
            self.assertEqual(cursor.statements, [])
        payload = "fixture'); DROP TABLE jobs; --"
        cursor = RecordingCursor()
        self.ingestion._sync_job(cursor, self.job(source_job_id=payload, title=payload), source_name='USAJOBS')
        for sql, params in cursor.statements:
            self.assertNotIn(payload, sql)
            self.assertEqual(sql.count('%s'), len(params))
