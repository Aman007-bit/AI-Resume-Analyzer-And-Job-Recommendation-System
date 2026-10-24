"""Read-only staging metadata verification; requires owner-confirmed local provenance."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re

import mysql.connector
from dotenv import dotenv_values

STAGING_ROOT = Path(r'C:\Users\dell\AppData\Local\AIResumeRestore\staging-c9d0f709471544f8bab0b9eb1b6e62cf')
DATABASE = 'resume_analyzer_restore_test'
TABLES = ('users', 'resumes', 'skills', 'resume_skills', 'jobs', 'job_skills', 'recommendations')


def normalized(path):
    return os.path.normcase(os.path.normpath(str(path).replace('/', os.sep)))


def trusted_settings(owner_confirmed=False):
    if not owner_confirmed:
        raise RuntimeError('Owner confirmation of staging records is required')
    config = configparser.ConfigParser(interpolation=None)
    config.read(STAGING_ROOT / 'my.ini', encoding='utf-8')
    server = config['mysqld']
    data = STAGING_ROOT / 'data'
    if (server.get('port') != '33309' or server.get('bind-address') != '127.0.0.1'
            or normalized(server.get('datadir', '')) != normalized(data)):
        raise RuntimeError('Local staging configuration mismatch')
    auto = configparser.ConfigParser(interpolation=None)
    auto.read(data / 'auto.cnf', encoding='utf-8')
    uuid = auto['auto']['server-uuid']
    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid):
        raise RuntimeError('Trusted UUID record is invalid')
    env = dotenv_values(Path(__file__).parent / '.env.staging', interpolate=False)
    if (env.get('DB_HOST') != '127.0.0.1' or env.get('DB_PORT') != '33309'
            or env.get('DB_NAME') != DATABASE or env.get('DB_STAGING_GUARD') != 'true'
            or env.get('DB_EXPECTED_PORT') != '33309'
            or normalized(env.get('DB_EXPECTED_DATA_DIR', '')) != normalized(data)
            or (env.get('DB_EXPECTED_SERVER_UUID') and env['DB_EXPECTED_SERVER_UUID'] != uuid)
            or not env.get('DB_USER') or not env.get('DB_PASSWORD')
            or env.get('JLA_RECOMMENDATIONS_AUTHORIZED') != 'false'):
        raise RuntimeError('Existing staging environment is incomplete or inconsistent')
    if any('\x00' in env[name] for name in ('DB_USER', 'DB_PASSWORD')):
        raise RuntimeError('Staging credential serialization contains a NUL character')
    return {'host': '127.0.0.1', 'port': 33309, 'database': DATABASE,
            'user': env['DB_USER'], 'password': env['DB_PASSWORD'],
            'expected_uuid': uuid, 'expected_datadir': str(data)}


def inspect_schema(settings, connect=None):
    if (settings.get('host') != '127.0.0.1' or settings.get('port') != 33309
            or settings.get('database') != DATABASE
            or not settings.get('expected_uuid') or not settings.get('expected_datadir')):
        raise RuntimeError('Prohibited or incomplete staging target')
    if any(not isinstance(settings.get(key), str) or not settings[key]
           or '\x00' in settings[key] for key in ('user', 'password')):
        raise RuntimeError('Invalid staging credentials; NUL character or missing value')
    connect = mysql.connector.connect if connect is None else connect
    connection = connect(**{key: settings[key] for key in ('host', 'port', 'database', 'user', 'password')}, connection_timeout=5)
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute('SELECT DATABASE() AS db, @@port AS port, @@server_uuid AS uuid, @@datadir AS datadir')
        identity = cursor.fetchone()
        if (not identity or identity['db'] != DATABASE or int(identity['port']) != 33309
                or identity['uuid'] != settings['expected_uuid']
                or normalized(identity['datadir']) != normalized(settings['expected_datadir'])):
            raise RuntimeError('Authenticated staging identity mismatch; inspection stopped')
        output = {'identity_verified': True, 'database': DATABASE, 'port': 33309,
                  'uuid_fingerprint': hashlib.sha256(settings['expected_uuid'].encode()).hexdigest()[:12],
                  'data_directory_matched': True}
        queries = {
            'tables': ('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s', (DATABASE,)),
            'columns': ('SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION', (DATABASE,)),
            'indexes': ('SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, SUB_PART FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX', (DATABASE,)),
            'foreign_keys': ('SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION', (DATABASE,)),
            'foreign_key_rules': ('SELECT TABLE_NAME, CONSTRAINT_NAME, UPDATE_RULE, DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = %s', (DATABASE,)),
            'session': ('SELECT @@autocommit AS autocommit, @@transaction_isolation AS transaction_isolation, @@require_secure_transport AS require_secure_transport', ()),
            'tls': ("SHOW SESSION STATUS WHERE Variable_name IN ('Ssl_cipher','Ssl_version')", ()),
        }
        for name, (query, params) in queries.items():
            cursor.execute(query, params)
            rows = cursor.fetchall()
            if name in ('columns', 'indexes', 'foreign_keys', 'foreign_key_rules'):
                rows = [row for row in rows if row['TABLE_NAME'] in TABLES]
            output[name] = rows
        job_columns = {row['COLUMN_NAME'] for row in output['columns'] if row['TABLE_NAME'] == 'jobs'}
        if {'source_name', 'source_job_id'}.issubset(job_columns):
            cursor.execute('SELECT COUNT(*) AS duplicate_groups FROM (SELECT 1 FROM jobs WHERE source_name IS NOT NULL AND source_job_id IS NOT NULL GROUP BY source_name, source_job_id HAVING COUNT(*) > 1) AS duplicate_keys')
            output['duplicate_source_identity_groups'] = cursor.fetchone()['duplicate_groups']
            cursor.execute("SELECT COUNT(*) AS invalid_identity_rows FROM jobs WHERE source_name IS NULL OR TRIM(source_name) = '' OR source_job_id IS NULL OR TRIM(source_job_id) = ''")
            output['invalid_source_identity_rows'] = cursor.fetchone()['invalid_identity_rows']
        return output
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-confirmed', action='store_true', help='Attest owner has confirmed the fixed local staging records')
    args = parser.parse_args()
    try:
        result = inspect_schema(trusted_settings(args.owner_confirmed))
        print(json.dumps(result, default=str))
        return 0
    except Exception as error:
        # Never print driver exception text, DSN, credentials or tokens.
        print(json.dumps({'verified': False, 'error_type': type(error).__name__, 'mysql_errno': getattr(error, 'errno', None)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
