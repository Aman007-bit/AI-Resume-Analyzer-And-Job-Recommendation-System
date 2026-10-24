
import os
import re

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error

load_dotenv()


def _staging_guard_enabled():
    return os.getenv("DB_STAGING_GUARD", "").strip().lower() == "true"


def _normalize_data_dir(value):
    return os.path.normcase(os.path.normpath(str(value).replace("/", os.sep)))


def verify_database_target(connection):
    """Fail closed when the isolated staging target is configured."""
    if not _staging_guard_enabled():
        raise RuntimeError("Isolated staging guard is required.")

    expected_database = os.getenv("DB_NAME", "resume_analyzer")
    expected_port = os.getenv("DB_EXPECTED_PORT")
    expected_data_dir = os.getenv("DB_EXPECTED_DATA_DIR")
    expected_uuid = os.getenv("DB_EXPECTED_SERVER_UUID")
    if not all((expected_database, expected_port, expected_data_dir, expected_uuid)):
        raise RuntimeError("Staging database identity is incompletely configured.")

    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE(), @@port, @@datadir, @@server_uuid")
        row = cursor.fetchone()
    finally:
        cursor.close()

    if isinstance(row, dict):
        actual_database = row.get("DATABASE()")
        actual_port = row.get("@@port")
        actual_data_dir = row.get("@@datadir")
        actual_uuid = row.get("@@server_uuid")
    else:
        actual_database, actual_port, actual_data_dir, actual_uuid = row or (None,) * 4

    try:
        matches = (
            actual_database == expected_database
            and int(actual_port) == int(expected_port)
            and _normalize_data_dir(actual_data_dir)
            == _normalize_data_dir(expected_data_dir)
            and actual_uuid == expected_uuid
        )
    except (TypeError, ValueError):
        matches = False

    if not matches:
        raise RuntimeError("Database connection does not match the verified staging target.")


class _StagingGuardCursor:
    _READ_ONLY_PREFIXES = ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "HELP")

    @classmethod
    def _is_unambiguously_read_only(cls, operation):
        if not isinstance(operation, str):
            return False

        sql = operation.strip()
        if not sql or ";" in sql:
            return False

        # A WITH clause may precede INSERT, UPDATE, or DELETE. Treat it as a
        # write-capable statement unless a SQL parser can prove otherwise.
        keyword = re.match(r"([A-Za-z]+)", sql)
        if not keyword or keyword.group(1).upper() not in cls._READ_ONLY_PREFIXES:
            return False

        statement = keyword.group(1).upper()
        if statement == "SELECT" and re.search(
            r"\bINTO\b|:=|\bFOR\s+(?:UPDATE|SHARE)\b|"
            r"\bLOCK\s+IN\s+SHARE\s+MODE\b|"
            r"\b(?:GET_LOCK|RELEASE_LOCK|SLEEP)\s*\(",
            sql,
            re.IGNORECASE,
        ):
            return False
        if statement == "EXPLAIN" and re.search(
            r"\bANALYZE\b", sql, re.IGNORECASE
        ):
            return False
        return True

    def __init__(self, cursor, connection):
        self._cursor = cursor
        self._connection = connection

    def execute(self, operation, *args, **kwargs):
        if not self._is_unambiguously_read_only(operation):
            verify_database_target(self._connection)
        return self._cursor.execute(operation, *args, **kwargs)

    def executemany(self, operation, *args, **kwargs):
        verify_database_target(self._connection)
        return self._cursor.executemany(operation, *args, **kwargs)

    def callproc(self, procname, *args, **kwargs):
        verify_database_target(self._connection)
        return self._cursor.callproc(procname, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _StagingGuardConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self, *args, **kwargs):
        return _StagingGuardCursor(self._connection.cursor(*args, **kwargs), self._connection)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _validate_connection_configuration():
    """Reject unsafe targets before opening any socket; trust markers come from the owner."""
    if (
        not _staging_guard_enabled()
        or os.getenv("DB_HOST", "").strip() != "127.0.0.1"
        or os.getenv("DB_PORT", "").strip() != "33309"
        or os.getenv("DB_NAME", "").strip() != "resume_analyzer_restore_test"
        or os.getenv("DB_EXPECTED_PORT", "").strip() != "33309"
        or not os.path.isabs(os.getenv("DB_EXPECTED_DATA_DIR", ""))
        or not all(os.getenv(name, "").strip() for name in (
            "DB_EXPECTED_SERVER_UUID", "DB_USER", "DB_PASSWORD"
        ))
    ):
        raise RuntimeError("Verified isolated staging configuration is required.")


def get_db_connection():
    connection = None
    try:
        if _staging_guard_enabled():
            _validate_connection_configuration()
            guarded = True
        elif (
            os.getenv("DB_ALLOW_UNGUARDED", "").strip().lower() == "true"
            and os.getenv("DB_NAME", "").strip()
            and os.getenv("DB_USER", "").strip()
        ):
            # Apna asli local DB (resume_analyzer), jaan-boojhke opt-in
            guarded = False
        else:
            raise RuntimeError("Database target is not approved.")

        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            connection_timeout=5,
        )
        if not connection.is_connected():
            connection.close()
            return None

        if guarded:
            verify_database_target(connection)
            return _StagingGuardConnection(connection)
        return connection
    except Exception as error:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        print(f"MySQL connection failed: {type(error).__name__}")
    return None

if __name__ == "__main__":
    connection = get_db_connection()

    if connection is not None:
        connection.close()
        print("MySQL connection successful and closed.")
