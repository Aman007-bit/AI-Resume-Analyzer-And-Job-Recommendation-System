"""Single-run client for an externally scheduled authenticated job sync.

Configure SYNC_API_BASE_URL, SYNC_ADMIN_EMAIL, and SYNC_ADMIN_PASSWORD in the
service account's protected environment. Run once every 24-48 hours with the
Windows Task Scheduler setting that prevents concurrent task instances.
"""

import os
import sys
from urllib.parse import urlsplit

import requests

REQUEST_TIMEOUT = (5, 30)


def _configuration(environ):
    base_url = environ.get("SYNC_API_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    parsed = urlsplit(base_url)
    email = environ.get("SYNC_ADMIN_EMAIL", "").strip()
    password = environ.get("SYNC_ADMIN_PASSWORD", "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError("SYNC_API_BASE_URL must be an HTTP(S) origin")
    if not email or not password:
        raise ValueError("Authenticated sync credentials are not configured")
    read_timeout = int(environ.get("SYNC_READ_TIMEOUT_SECONDS", "30"))
    if not 1 <= read_timeout <= 3600:
        raise ValueError("Sync read timeout must be between 1 and 3600 seconds")
    return base_url, email, password, read_timeout


def run_scheduled_sync(environ=None, http=None):
    environ = os.environ if environ is None else environ
    http = requests if http is None else http
    try:
        base_url, email, password, read_timeout = _configuration(environ)
    except ValueError:
        return 1, {"status": "configuration_error"}

    try:
        login = http.post(
            base_url + "/api/auth/login",
            json={"email": email, "password": password},
            timeout=REQUEST_TIMEOUT,
        )
        if login.status_code != 200:
            return 1, {"status": "authentication_failed", "http_status": login.status_code}
        auth_payload = login.json()
        token = auth_payload.get("access_token") if isinstance(auth_payload, dict) else None
        if not isinstance(token, str) or not token:
            return 1, {"status": "authentication_response_invalid"}

        try:
            response = http.post(
                base_url + "/api/admin/jobs/sync",
                headers={"Authorization": "Bearer " + token},
                timeout=(REQUEST_TIMEOUT[0], read_timeout),
            )
        except requests.Timeout:
            # The server may still be running. Never automatically repeat this POST.
            return 3, {"status": "sync_outcome_unknown"}
        if response.status_code != 200:
            return 1, {"status": "sync_failed", "http_status": response.status_code}
        result = response.json()
        if not isinstance(result, dict):
            return 1, {"status": "sync_response_invalid"}
        summary = {
            "status": "completed" if not result.get("failures") else "partial",
            "processed": result.get("processed", 0),
            "inserted": result.get("inserted", 0),
            "updated": result.get("updated", 0),
            "skipped": result.get("skipped", 0),
            "sources": {
                name: source.get("status")
                for name, source in (result.get("sources") or {}).items()
                if isinstance(name, str) and isinstance(source, dict)
            },
        }
        return (0 if summary["status"] == "completed" else 2), summary
    except (requests.RequestException, ValueError, TypeError):
        return 1, {"status": "request_or_response_error"}


def main():
    code, summary = run_scheduled_sync()
    print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
