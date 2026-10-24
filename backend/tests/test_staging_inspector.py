"""Offline tests for the read-only identity/schema diagnostic, never real MySQL."""
import unittest
from unittest.mock import Mock, patch

import verify_staging_schema as inspector


class StagingInspectorTests(unittest.TestCase):
    def settings(self):
        return dict(host='127.0.0.1', port=33309, database=inspector.DATABASE,
                    user='offline-user', password='offline-only',
                    expected_uuid='offline-uuid', expected_datadir=r'C:\offline\data')

    def test_unconfirmed_records_fail_before_connector(self):
        with patch.object(inspector.mysql.connector, 'connect') as connector:
            with self.assertRaises(RuntimeError):
                inspector.trusted_settings(False)
            connector.assert_not_called()

    def test_bad_identity_closes_without_schema_query(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = dict(db='wrong', port=33309, uuid='offline-uuid', datadir=r'C:\offline\data')
        connector = Mock(return_value=connection)
        with self.assertRaises(RuntimeError):
            inspector.inspect_schema(self.settings(), connect=connector)
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn('SELECT DATABASE()', cursor.execute.call_args.args[0])
        connection.close.assert_called_once()

    def test_verified_connection_executes_only_metadata_reads(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = dict(db=inspector.DATABASE, port=33309, uuid='offline-uuid', datadir=r'C:\offline\data')
        cursor.fetchall.return_value = []
        connector = Mock(return_value=connection)
        result = inspector.inspect_schema(self.settings(), connect=connector)
        self.assertTrue(result['identity_verified'])
        self.assertEqual(connector.call_count, 1)
        for call in cursor.execute.call_args_list:
            self.assertTrue(call.args[0].startswith(('SELECT ', 'SHOW ')))
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_existing_malformed_password_rejected_before_connector(self):
        settings = self.settings()
        settings['password'] = 'offline\x00invalid'
        with patch.object(inspector.mysql.connector, 'connect') as connector:
            with self.assertRaisesRegex(RuntimeError, 'NUL character'):
                inspector.inspect_schema(settings)
            connector.assert_not_called()

    def test_prohibited_targets_never_call_connector(self):
        for overrides in ({'port': 3306}, {'port': 33308}, {'host': 'localhost'}, {'database': 'resume_analyzer'}, {'expected_uuid': ''}):
            settings = dict(self.settings(), **overrides)
            with self.subTest(fields=list(overrides)), patch.object(inspector.mysql.connector, 'connect') as connector:
                with self.assertRaises(RuntimeError):
                    inspector.inspect_schema(settings)
                connector.assert_not_called()
