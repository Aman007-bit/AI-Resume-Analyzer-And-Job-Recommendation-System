import copy
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes-long")

import auth
from fastapi.testclient import TestClient
from main import app
from routers import job_ingestion_routes
from services import job_ingestion_service as ingestion


def remotive_job(job_id=123, **overrides):
    job = {
        "id": job_id,
        "url": f"https://remotive.com/remote-jobs/example-{job_id}",
        "title": "Backend Engineer",
        "company_name": "Example Company",
        "candidate_required_location": "Worldwide",
        "description": "<p>Build reliable <strong>services</strong>.</p>",
        "tags": ["Python", "FastAPI"],
        "publication_date": "2026-04-01T10:30:00",
    }
    job.update(overrides)
    return job


def quota_headers(remaining="8", limit="10", reset="2000000000"):
    return {
        "X-RateLimit-Limit": limit,
        "X-RateLimit-Remaining": remaining,
        "X-RateLimit-Reset": reset,
    }


class InMemoryDatabase:
    def __init__(self, fail_on_skill=None):
        self.jobs = {}
        self.skills = {}
        self.links = set()
        self.next_job_id = 1
        self.next_skill_id = 1
        self.fail_on_skill = fail_on_skill
        self.snapshot = None
        self.cursor_instance = None
        self.closed = False
        self.commit_count = 0
        self.rollback_count = 0
        self.snapshot = self._state()

    def _state(self):
        return (
            copy.deepcopy(self.jobs),
            copy.deepcopy(self.skills),
            copy.deepcopy(self.links),
            self.next_job_id,
            self.next_skill_id,
        )

    def _restore(self, state):
        (
            self.jobs,
            self.skills,
            self.links,
            self.next_job_id,
            self.next_skill_id,
        ) = copy.deepcopy(state)

    def cursor(self, **kwargs):
        self.cursor_instance = InMemoryCursor(self)
        return self.cursor_instance

    def commit(self):
        self.commit_count += 1
        self.snapshot = self._state()

    def rollback(self):
        self.rollback_count += 1
        if self.snapshot is not None:
            self._restore(self.snapshot)

    def close(self):
        self.closed = True


class InMemoryCursor:
    def __init__(self, database):
        self.database = database
        self.lastrowid = None
        self.result = None
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        params = params or ()
        database = self.database
        self.result = None
        self.lastrowid = None

        if normalized.startswith("SELECT id FROM jobs"):
            self.result = database.jobs.get((params[0], params[1]))
        elif normalized.startswith("INSERT INTO jobs"):
            job = dict(
                zip(
                    (
                        "title",
                        "company",
                        "location",
                        "work_mode",
                        "description",
                        "requirements",
                        "source_url",
                        "posted_at",
                    ),
                    params[:8],
                )
            )
            job.update(
                source_name=params[8],
                source_job_id=params[9],
                status=params[10],
                expires_at=params[11],
            )
            job_id = database.next_job_id
            database.next_job_id += 1
            job["id"] = job_id
            database.jobs[(params[8], params[9])] = job
            self.lastrowid = job_id
        elif normalized == "UPDATE jobs SET requirements = NULL WHERE id = %s":
            job = next(row for row in database.jobs.values() if row["id"] == params[0])
            job["requirements"] = None
        elif normalized.startswith("UPDATE jobs"):
            job_id = params[-1]
            job = next(row for row in database.jobs.values() if row["id"] == job_id)
            update_values = (
                params[0], params[1], params[2], params[4], params[5],
                params[6], params[7], params[8],
            )
            for key, value in zip(
                ("title", "company", "location", "work_mode", "description", "requirements", "source_url", "posted_at"),
                update_values,
            ):
                if value not in (None, ""):
                    job[key] = value
            job["status"] = params[-3]
            job["expires_at"] = params[-2]
        elif normalized.startswith("DELETE FROM job_skills"):
            job_id = params[0]
            database.links = {
                link for link in database.links if link[0] != job_id
            }
        elif normalized.startswith("SELECT id FROM skills"):
            skill_id = database.skills.get(params[0])
            self.result = {"id": skill_id} if skill_id is not None else None
        elif normalized.startswith("INSERT INTO skills"):
            skill_id = database.next_skill_id
            database.next_skill_id += 1
            database.skills[params[0]] = skill_id
            self.lastrowid = skill_id
        elif normalized.startswith("INSERT IGNORE INTO job_skills"):
            job_id, skill_id = params
            skill_name = next(
                name for name, current_id in database.skills.items()
                if current_id == skill_id
            )
            if skill_name == database.fail_on_skill:
                raise RuntimeError("synthetic database failure")
            database.links.add((job_id, skill_id))
        else:
            raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchone(self):
        return self.result

    def close(self):
        self.closed = True


class JobIngestionTests(unittest.TestCase):
    def setUp(self):
        self.database = InMemoryDatabase()
        self.actual_staging_guard = ingestion._require_staging_job_target
        self.staging_guard_patch = patch.object(
            ingestion, "_require_staging_job_target"
        )
        self.staging_guard_patch.start()
        self.addCleanup(self.staging_guard_patch.stop)
        self.connection_patch = patch.object(
            ingestion, "get_db_connection", return_value=self.database
        )
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)


        for p in (
            patch.object(
                ingestion, "_load_checkpoint",
                side_effect=lambda: {"windows": {}, "last_successful": None, "seen_ids": []},
            ),
            patch.object(ingestion, "_save_checkpoint"),
            patch.dict(os.environ, {"JLA_USE_DATE_WINDOWS": "false"}),
        ):
            p.start()
            self.addCleanup(p.stop)
                

    def test_sync_write_paths_require_verified_staging_before_connecting(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                ingestion,
                "_require_staging_job_target",
                side_effect=self.actual_staging_guard,
            ),
            patch.object(ingestion, "get_db_connection") as get_connection,
            patch.object(ingestion, "_load_remotive_jobs") as load_remotive,
        ):
            result = ingestion._sync_source("Lever", [{"id": "fixture"}], lambda row: row)
            with self.assertRaises(ingestion._ProviderError):
                ingestion.synchronize_remotive_jobs()

        self.assertEqual(result["status"], "failed")
        get_connection.assert_not_called()
        load_remotive.assert_not_called()

    def test_maps_documented_provider_fields_and_html_description(self):
        mapped = ingestion._parse_job(remotive_job())

        self.assertEqual(mapped["source_job_id"], "123")
        self.assertEqual(mapped["source_url"], remotive_job()["url"])
        self.assertEqual(mapped["company"], "Example Company")
        self.assertEqual(mapped["description"], "Build reliable services.")
        self.assertEqual(mapped["skills"], ["Python", "FastAPI"])
        self.assertEqual(mapped["posted_at"], datetime(2026, 4, 1, 10, 30))

    def test_maps_the_muse_job_fields_and_extracts_description_skills(self):
        mapped = ingestion._parse_the_muse_job(
            {
                "id": 987,
                "name": "Python Engineer",
                "company": {"name": "Muse Example"},
                "locations": [{"name": "Remote"}, {"name": "New York"}],
                "contents": "<p>Build services with Python and SQL.</p>",
                "publication_date": "2026-04-02T12:30:00Z",
                "refs": {
                    "landing_page": (
                        "https://www.themuse.com/jobs/muse-example/python-engineer"
                    )
                },
            }
        )

        self.assertEqual(mapped["source_job_id"], "987")
        self.assertEqual(
            mapped["source_url"],
            "https://www.themuse.com/jobs/muse-example/python-engineer",
        )
        self.assertEqual(mapped["company"], "Muse Example")
        self.assertEqual(mapped["location"], "Remote, New York")
        self.assertEqual(mapped["description"], "Build services with Python and SQL.")
        self.assertEqual(mapped["posted_at"], datetime(2026, 4, 2, 12, 30))
        self.assertIn("Python", mapped["skills"])

    def test_maps_usajobs_public_announcement_fields_and_skills(self):
        mapped = ingestion._parse_usajobs_job(
            {
                "MatchedObjectId": "123456789",
                "MatchedObjectDescriptor": {
                    "PositionID": "ABC-123",
                    "PositionTitle": "Software Engineer",
                    "OrganizationName": "Example Agency",
                    "PositionLocationDisplay": "Washington, DC",
                    "PositionURI": (
                        "https://www.usajobs.gov/job/123456789"
                    ),
                    "PublicationStartDate": "2026-10-01T00:00:00Z",
                    "UserArea": {
                        "Details": {
                            "JobSummary": (
                                "<p>Build services with Python and SQL.</p>"
                            ),
                            "MajorDuties": [
                                "<p>Deploy applications on AWS.</p>",
                                "Collaborate with engineering teams.",
                            ],
                            "Qualifications": "Experience with Python.",
                        }
                    },
                },
            }
        )

        self.assertEqual(mapped["source_job_id"], "123456789")
        self.assertEqual(mapped["title"], "Software Engineer")
        self.assertEqual(mapped["company"], "Example Agency")
        self.assertEqual(mapped["location"], "Washington, DC")
        self.assertEqual(
            mapped["source_url"],
            "https://www.usajobs.gov/job/123456789",
        )
        self.assertIn("Python", mapped["skills"])
        self.assertIn("SQL", mapped["skills"])
        self.assertIn("AWS", mapped["skills"])

    def test_usajobs_loader_sends_required_headers_and_bounds_pages(self):
        provider_job = {"MatchedObjectId": "1"}
        with patch.object(
            ingestion,
            "_request_json",
            return_value={
                "SearchResult": {
                    "SearchResultItems": [provider_job],
                }
            },
        ) as request_json:
            jobs = ingestion._load_usajobs_jobs(
                "test-api-key",
                "test@example.com",
            )

        self.assertEqual(jobs, [provider_job])
        request_json.assert_called_once_with(
            ingestion.USAJOBS_API_URL,
            {"Page": 1, "ResultsPerPage": ingestion.USAJOBS_PAGE_SIZE},
            headers={
                "Host": "data.usajobs.gov",
                "User-Agent": "test@example.com",
                "Authorization-Key": "test-api-key",
            },
        )

    def test_usajobs_loader_stops_at_configured_page_limit(self):
        first_page = [{"MatchedObjectId": str(index)} for index in range(100)]
        second_page = [
            {"MatchedObjectId": str(index)} for index in range(100, 200)
        ]
        payloads = [
            {"SearchResult": {"SearchResultItems": first_page}},
            {"SearchResult": {"SearchResultItems": second_page}},
        ]
        with patch.object(
            ingestion,
            "_request_json",
            side_effect=payloads,
        ) as request_json:
            jobs = ingestion._load_usajobs_jobs(
                "test-api-key",
                "test@example.com",
            )

        self.assertEqual(len(jobs), 200)
        self.assertEqual(request_json.call_count, ingestion.MAX_USAJOBS_PAGES)

    def test_maps_job_listings_api_job_and_workplace_metadata(self):
        provider_job = {
            "id": 456,
            "title": "Python Engineer",
            "company": "Example Ltd",
            "location": {
                "raw": "Bengaluru, India",
                "city": "Bengaluru",
                "country_code": "IN",
            },
            "remote_policy": "hybrid",
            "is_remote": False,
            "description_html": "<p>Build APIs with Python and SQL.</p>",
            "listed_at": "2026-10-17T10:30:00Z",
            "url": "https://jobs.example.com/positions/456",
        }
        with patch.dict(
            os.environ,
            {"JLA_RECOMMENDATIONS_AUTHORIZED": "true"},
            clear=True,
        ):
            mapped = ingestion._parse_job_listings_api_job(provider_job)

        self.assertEqual(mapped["source_job_id"], "456")
        self.assertEqual(mapped["company"], "Example Ltd")
        self.assertEqual(mapped["location"], "Bengaluru, India")
        self.assertEqual(mapped["work_mode"], "hybrid")
        self.assertEqual(mapped["source_url"], "https://jobs.example.com/positions/456")
        self.assertEqual(mapped["skills"], ["Python", "SQL"])
        self.assertEqual(mapped["posted_at"], datetime(2026, 10, 17, 10, 30))

    def test_job_listings_api_does_not_extract_skills_without_separate_permission(
        self,
    ):
        with patch.dict(os.environ, {}, clear=True):
            mapped = ingestion._parse_job_listings_api_job(
                {
                    "id": 457,
                    "title": "Python Engineer",
                    "company": "Example Ltd",
                    "description_html": "Build APIs with Python and SQL.",
                    "url": "https://jobs.example.com/positions/457",
                }
            )

        self.assertEqual(mapped["description"], "Build APIs with Python and SQL.")
        self.assertIsNone(mapped["skills"])
        self.assertIsNone(mapped["requirements"])

    def test_job_listings_api_work_mode_falls_back_only_on_explicit_remote(self):
        base = {
            "id": 1,
            "title": "Engineer",
            "company": "Example",
            "url": "https://jobs.example.com/1",
        }
        for remote_policy, is_remote, expected in (
            ("on-site", False, "on_site"),
            (None, True, "remote"),
            (None, False, "unknown"),
            ("unspecified", None, "unknown"),
        ):
            with self.subTest(remote_policy=remote_policy, is_remote=is_remote):
                mapped = ingestion._parse_job_listings_api_job(
                    {**base, "remote_policy": remote_policy, "is_remote": is_remote}
                )
                self.assertEqual(mapped["work_mode"], expected)

    def test_job_listings_api_loader_sends_auth_and_caps_pages(self):
        def response(url, params, **kwargs):
            offset = params["offset"]
            total = 250
            count = min(100, max(0, total - offset))
            return (
                {"success": True, "total": total,
                 "jobs": [{"id": f"global-{offset + i}"} for i in range(count)]},
                quota_headers("8"),
            )

        with patch.object(ingestion, "_request_json", side_effect=response) as request_json:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")

        self.assertEqual(len(jobs), 250)
        self.assertFalse(incomplete)
        self.assertEqual(request_json.call_count, 3)
        self.assertEqual(
            request_json.call_args_list[0].args,
            (
                ingestion.JOB_LISTINGS_API_URL,
                {"limit": 100, "offset": 0},
            ),
        )
        self.assertEqual(request_json.call_args_list[0].kwargs["headers"],
                         {"X-API-Key": "test-api-key"})
        self.assertTrue(request_json.call_args_list[0].kwargs["include_headers"])
        self.assertTrue(request_json.call_args_list[0].kwargs["stop_on_rate_limit"])
        self.assertEqual(request_json.call_args_list[0].kwargs["max_attempts"], 1)
        self.assertEqual(
            request_json.call_args_list[1].args[1],
            {"limit": 100, "offset": 100},
        )

    def test_job_listings_api_loader_accepts_empty_results(self):
        with patch.object(
            ingestion,
            "_request_json",
            return_value=({"success": True, "total": 0, "jobs": []},
                          quota_headers("8")),
        ) as request_json:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")

        self.assertEqual(jobs, [])
        self.assertFalse(incomplete)
        self.assertEqual(request_json.call_count, 1)

    def test_job_listings_api_loader_rejects_malformed_response(self):
        malformed_payloads = [
            {"success": False, "total": 0, "jobs": []},
            {"success": True, "jobs": []},
            {"success": True, "total": "0", "jobs": []},
            {"success": True, "total": -1, "jobs": []},
            {"success": True, "total": 0},
            {"success": True, "total": 0, "jobs": None},
        ]
        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                with patch.object(
                    ingestion,
                    "_request_json",
                    return_value=(payload, quota_headers("8")),
                ):
                    with self.assertRaises(ingestion._ProviderError):
                        ingestion._load_job_listings_api_jobs("test-api-key")

    def test_job_listings_api_loader_rejects_page_larger_than_total(self):
        response = (
            {"success": True, "total": 50, "jobs": [{"id": i} for i in range(100)]},
            quota_headers("8"),
        )
        with patch.object(ingestion, "_request_json", return_value=response):
            with self.assertRaisesRegex(
                ingestion._ProviderError, "more jobs than the advertised total"
            ):
                ingestion._load_job_listings_api_jobs("test-api-key")

    def test_job_listings_api_loader_rejects_page_larger_than_remaining_total(self):
        responses = [
            (
                {"success": True, "total": 150, "jobs": [{"id": i} for i in range(100)]},
                quota_headers("8"),
            ),
            (
                {"success": True, "total": 150, "jobs": [{"id": 100 + i} for i in range(51)]},
                quota_headers("7"),
            ),
        ]
        with patch.object(ingestion, "_request_json", side_effect=responses):
            with self.assertRaisesRegex(
                ingestion._ProviderError, "more jobs than the advertised total"
            ):
                ingestion._load_job_listings_api_jobs("test-api-key")

    def test_job_listings_api_loader_marks_changed_total_incomplete(self):
        responses = [
            (
                {"success": True, "total": 250, "jobs": [{"id": i} for i in range(100)]},
                quota_headers("8"),
            ),
            (
                {"success": True, "total": 251, "jobs": [{"id": 100 + i} for i in range(100)]},
                quota_headers("7"),
            ),
        ]
        with patch.object(ingestion, "_request_json", side_effect=responses) as request:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")

        self.assertTrue(incomplete)
        self.assertEqual(len(jobs), 100)
        self.assertEqual(request.call_count, 2)
        with patch.object(ingestion, "get_db_connection") as connect:
            reconciliation = ingestion._reconcile_job_listings_api_statuses(
                jobs, not incomplete, {"status": "partial"}
            )
        self.assertEqual(reconciliation["missing_closed"], 0)
        connect.assert_not_called()

    def test_job_listings_api_loader_aborts_on_upstream_failure(self):
        with patch.object(
            ingestion,
            "_request_json",
            side_effect=[
                ({"success": True, "total": 101,
                  "jobs": [{"id": i} for i in range(100)]},
                 quota_headers("8")),
                ingestion._ProviderError("Upstream request failed"),
            ],
        ) as request_json:
            with self.assertRaises(ingestion._ProviderError):
                ingestion._load_job_listings_api_jobs("test-api-key")

        self.assertEqual(request_json.call_count, 2)

    def test_job_listings_api_loader_stops_when_quota_is_exhausted(self):
        page = ({"success": True, "total": 250,
                 "jobs": [{"id": i} for i in range(100)]},
                quota_headers("0"))
        with patch.object(ingestion, "_request_json", return_value=page) as request:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")
        self.assertEqual(len(jobs), 100)
        self.assertTrue(incomplete)
        request.assert_called_once()

    def test_job_listings_api_loader_is_bounded_per_sync_by_plan_budget(self):
        def response(url, params, **kwargs):
            offset = params["offset"]
            return ({"success": True, "total": 5000,
                     "jobs": [{"id": offset + i} for i in range(100)]},
                    quota_headers("8"))
        with patch.object(ingestion, "_request_json", side_effect=response) as request:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")
        self.assertEqual(len(jobs), 1000)
        self.assertTrue(incomplete)
        self.assertEqual(request.call_count,
                         ingestion.MAX_JOB_LISTINGS_API_REQUESTS_PER_SYNC)

    def test_job_listings_api_loader_marks_missing_quota_header_incomplete(self):
        valid = quota_headers()
        for missing_header in valid:
            with self.subTest(missing_header=missing_header):
                headers = dict(valid)
                del headers[missing_header]
                page = ({"success": True, "total": 0, "jobs": []}, headers)
                with patch.object(ingestion, "_request_json", return_value=page):
                    jobs, incomplete, _ = ingestion._load_job_listings_api_jobs(
                        "test-api-key"
                    )
                self.assertEqual(jobs, [])
                self.assertTrue(incomplete)

    def test_job_listings_api_loader_marks_malformed_or_negative_quota_incomplete(self):
        cases = (
            ("X-RateLimit-Remaining", "not-an-integer"),
            ("X-RateLimit-Remaining", "-1"),
            ("X-RateLimit-Remaining", "+1"),
            ("X-RateLimit-Remaining", "1.5"),
            ("X-RateLimit-Limit", "not-an-integer"),
            ("X-RateLimit-Limit", "-1"),
            ("X-RateLimit-Limit", "0"),
            ("X-RateLimit-Limit", "1.5"),
            ("X-RateLimit-Reset", ""),
            ("X-RateLimit-Reset", "   "),
        )
        for header, value in cases:
            with self.subTest(header=header, value=value):
                headers = quota_headers()
                headers[header] = value
                page = (
                    {"success": True, "total": 0, "jobs": []},
                    headers,
                )
                with patch.object(ingestion, "_request_json", return_value=page):
                    jobs, incomplete, _ = ingestion._load_job_listings_api_jobs(
                        "test-api-key"
                    )
                self.assertEqual(jobs, [])
                self.assertTrue(incomplete)

        headers = quota_headers()
        headers["X-RateLimit-Remaining"] = "11"
        headers["X-RateLimit-Limit"] = "10"
        with patch.object(
            ingestion,
            "_request_json",
            return_value=({"success": True, "total": 0, "jobs": []}, headers),
        ):
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")
        self.assertEqual(jobs, [])
        self.assertTrue(incomplete)

    def test_job_listings_api_loader_detects_repeated_page(self):
        page = ({"success": True, "total": 250,
                 "jobs": [{"id": i} for i in range(100)]},
                quota_headers("8"))
        with patch.object(ingestion, "_request_json", return_value=page) as request:
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")
        self.assertEqual(len(jobs), 100)
        self.assertTrue(incomplete)
        self.assertEqual(request.call_count, 2)

    def test_job_listings_api_loader_deduplicates_repeated_source_ids(self):
        def response(url, params, **kwargs):
            return ({"success": True, "total": 2,
                     "jobs": [{"id": "same", "status": "active"},
                              {"id": "same", "status": "active"}]},
                    quota_headers("8"))
        with patch.object(ingestion, "_request_json", side_effect=response):
            jobs, incomplete, _ = ingestion._load_job_listings_api_jobs("test-api-key")
        self.assertTrue(incomplete)
        self.assertEqual([job["id"] for job in jobs], ["same"])

    def test_job_listings_api_loader_rejects_malformed_expiry(self):
        response = ({"success": True, "total": 1,
                     "jobs": [{"id": "x", "valid_through": "not-a-date"}]},
                     quota_headers("8"))
        with patch.object(ingestion, "_request_json", return_value=response):
            with self.assertRaises(ingestion._ProviderError):
                ingestion._load_job_listings_api_jobs("test-api-key")

    def test_job_listings_api_status_and_expiry_are_preserved(self):
        base = {"id": "closed-1", "title": "Engineer", "company": "Example",
                "url": "https://jobs.example.com/closed-1"}
        removed = ingestion._parse_job_listings_api_job({**base, "status": "removed"})
        expired = ingestion._parse_job_listings_api_job({
            **base, "id": "expired-1", "valid_through": "2000-01-01T00:00:00Z"
        })
        self.assertEqual(removed["status"], "closed")
        self.assertEqual(expired["status"], "expired")
        self.assertIsNotNone(expired["expires_at"])

    def test_incomplete_or_failed_jla_sync_never_closes_missing_jobs(self):
        successful = {"status": "succeeded"}
        with patch.object(ingestion, "get_db_connection") as connect:
            result = ingestion._reconcile_job_listings_api_statuses(
                [{"id": "still-open", "status": "active"}], False, successful
            )
            self.assertEqual(result["missing_closed"], 0)
            ingestion._reconcile_job_listings_api_statuses(
                [], True, {"status": "failed"}
            )
            ingestion._reconcile_job_listings_api_statuses(
                [], True, {"status": "succeeded"}
            )
        connect.assert_not_called()

    def test_concurrent_sync_in_same_api_process_is_rejected_without_second_run(self):
        self.assertTrue(ingestion._SYNC_RUN_LOCK.acquire(blocking=False))
        try:
            with patch.object(ingestion, "_synchronize_configured_sources_unlocked") as run:
                result = ingestion.synchronize_configured_sources()
            run.assert_not_called()
            self.assertEqual(result["inserted"], 0)
            self.assertIn("already running", result["errors"][0]["error"])
        finally:
            ingestion._SYNC_RUN_LOCK.release()

    def test_authoritative_removed_status_is_closed_even_on_partial_scan(self):
        class Cursor:
            rowcount = 1
            def __init__(self): self.executed = []
            def execute(self, query, params): self.executed.append((query, params))
            def close(self): pass
        class Connection:
            def __init__(self): self.cursor_instance = Cursor(); self.committed = False
            def cursor(self): return self.cursor_instance
            def commit(self): self.committed = True
            def rollback(self): pass
            def close(self): pass
        connection = Connection()
        with (
            patch.object(ingestion, "get_db_connection", return_value=connection),
            patch.object(ingestion, "_verify_jla_write_target") as verify,
        ):
            result = ingestion._reconcile_job_listings_api_statuses(
                [{"id": "closed-id", "status": "removed"}],
                False,
                {"status": "partial"},
            )
        self.assertEqual(result["closed"], 1)
        self.assertEqual(result["missing_closed"], 0)
        self.assertTrue(connection.committed)
        self.assertEqual(len(connection.cursor_instance.executed), 1)
        self.assertEqual(connection.cursor_instance.executed[0][1][0], "closed")
        verify.assert_called_once_with(connection, connection.cursor_instance)

    def test_complete_success_may_soft_close_jobs_missing_from_snapshot(self):
        class Cursor:
            rowcount = 2
            def __init__(self): self.executed = []
            def execute(self, query, params): self.executed.append((query, params))
            def close(self): pass
        class Connection:
            def __init__(self): self.cursor_instance = Cursor(); self.committed = False
            def cursor(self): return self.cursor_instance
            def commit(self): self.committed = True
            def rollback(self): pass
            def close(self): pass
        connection = Connection()
        with (
            patch.dict(os.environ, {"JLA_CLOSE_MISSING_JOBS": "true"}),
            patch.object(ingestion, "get_db_connection", return_value=connection),
            patch.object(ingestion, "_verify_jla_write_target") as verify,
        ):
            result = ingestion._reconcile_job_listings_api_statuses(
                [{"id": "present-id", "status": "active"}],
                True,
                {"status": "succeeded"},
            )
        self.assertEqual(result["missing_closed"], 2)
        self.assertIn("JSON_TABLE", connection.cursor_instance.executed[0][0])
        self.assertTrue(connection.committed)
        verify.assert_called_once_with(connection, connection.cursor_instance)

    def test_jla_write_target_requires_database_and_server_identity(self):
        class Cursor:
            def __init__(self, database): self.database = database; self.executed = []
            def execute(self, query): self.executed.append(query)
            def fetchone(self): return (self.database,)
        cursor = Cursor("resume_analyzer_restore_test")
        connection = object()
        with patch("db.verify_database_target") as verify:
            ingestion._verify_jla_write_target(connection, cursor)
        verify.assert_called_once_with(connection)
        self.assertEqual(cursor.executed, ["SELECT DATABASE()"])
        cursor = Cursor("resume_analyzer")
        with patch("db.verify_database_target"):
            with self.assertRaises(RuntimeError):
                ingestion._verify_jla_write_target(connection, cursor)

    def test_job_listings_api_malformed_listing_is_rejected(self):
        with self.assertRaises(ValueError):
            ingestion._parse_job_listings_api_job(
                {
                    "id": 1,
                    "title": "Engineer",
                    "company": "Example",
                    "url": "http://jobs.example.com/1",
                }
            )

    def test_job_listings_api_rejects_missing_required_fields_and_bad_url(self):
        valid = {
            "id": 88,
            "title": "Engineer",
            "company": "Example",
            "url": "https://jobs.example.com/88",
        }
        for field in ("id", "title", "company", "url"):
            with self.subTest(field=field):
                invalid = dict(valid)
                invalid.pop(field)
                with self.assertRaises(ValueError):
                    ingestion._parse_job_listings_api_job(invalid)

        for url in ("http://jobs.example.com/88", "", "not a url"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    ingestion._parse_job_listings_api_job({**valid, "url": url})

    def test_job_listings_api_missing_description_normalizes_to_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            mapped = ingestion._parse_job_listings_api_job(
                {
                    "id": 89,
                    "title": "Engineer",
                    "company": "Example",
                    "location": {"city": "Pune", "country_code": "IN"},
                    "url": "https://jobs.example.com/89",
                }
            )
        self.assertIsNone(mapped["description"])
        self.assertIsNone(mapped["skills"])
        self.assertEqual(mapped["location"], "Pune, IN")

    def test_job_listings_api_loader_handles_http_error_timeout_and_429(self):
        cases = (
            ingestion._ProviderError("Upstream request failed"),
            ingestion._ProviderError("Provider rate limit exhausted"),
        )
        for error in cases:
            with self.subTest(error=type(error).__name__), patch.object(
                ingestion, "_request_json", side_effect=error
            ) as request_json:
                with self.assertRaises(ingestion._ProviderError):
                    ingestion._load_job_listings_api_jobs("mock-key")
                request_json.assert_called_once()
                self.assertEqual(
                    request_json.call_args.kwargs["headers"],
                    {"X-API-Key": "mock-key"},
                )
                self.assertTrue(request_json.call_args.kwargs["stop_on_rate_limit"])

    def test_job_listings_api_loader_rejects_malformed_response(self):
        bad_payloads = (
            None,
            [],
            {"success": False, "jobs": [], "total": 0},
            {"success": True, "jobs": {}, "total": 0},
            {"success": True, "jobs": [], "total": "0"},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload), patch.object(
                ingestion,
                "_request_json",
                return_value=(payload, quota_headers()),
            ):
                with self.assertRaises(ingestion._ProviderError):
                    ingestion._load_job_listings_api_jobs("mock-key")

    def test_job_listings_api_logs_do_not_expose_api_key(self):
        secret = "jla_live_do_not_log_this"
        with (
            patch.dict(
                os.environ,
                {"JLA_API_KEY": secret, "JLA_INGESTION_AUTHORIZED": "true"},
                clear=True,
            ),
            patch.object(
                ingestion, "_load_job_listings_api_jobs",
                side_effect=ingestion._ProviderError("Upstream request failed"),
            ),
            patch.object(ingestion, "_require_staging_job_target"),
            patch.object(ingestion, "_sync_source") as sync,
            self.assertLogs(ingestion.logger, level="WARNING") as captured,
        ):
            result = ingestion.synchronize_configured_sources()

        self.assertNotIn(secret, "\n".join(captured.output))
        self.assertEqual(result["sources"]["Job Listings API"]["status"], "failed")
        sync.assert_not_called()

    def test_job_listings_api_sync_failure_does_not_write_partial_page(self):
        with (
            patch.dict(
                os.environ,
                {
                    "JLA_API_KEY": "test-api-key",
                    "JLA_INGESTION_AUTHORIZED": "true",
                },
                clear=True,
            ),
            patch.object(
                ingestion,
                "_load_job_listings_api_jobs",
                side_effect=ingestion._ProviderError("Upstream request failed"),
            ),
            patch.object(ingestion, "_sync_source") as sync,
        ):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(
            summary["sources"]["Job Listings API"]["status"], "failed"
        )
        self.assertEqual(summary["sources"]["Job Listings API"]["processed"], 0)
        self.assertIn("Job Listings API", summary["attempted_sources"])
        self.assertEqual(self.database.jobs, {})
        sync.assert_not_called()

    def test_job_listings_api_invalid_configuration_fails_before_request(self):
        with (
            patch.dict(
                os.environ,
                {
                    "JLA_API_KEY": "invalid\nkey",
                    "JLA_INGESTION_AUTHORIZED": "true",
                },
                clear=True,
            ),
            patch.object(ingestion, "_load_job_listings_api_jobs") as load,
            patch.object(ingestion, "_sync_source") as sync,
        ):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(summary["sources"]["Job Listings API"]["status"], "failed")
        self.assertEqual(summary["sources"]["Job Listings API"]["processed"], 0)
        load.assert_not_called()
        sync.assert_not_called()
        self.assertEqual(self.database.jobs, {})

    def test_job_listings_api_sync_is_repeatable_when_authorized(self):
        provider_job = {
            "id": 700,
            "title": "Python Engineer",
            "company": "Example Ltd",
            "location": {"raw": "Pune, India"},
            "remote_policy": "onsite",
            "description_html": "Use Python to build services.",
            "url": "https://jobs.example.com/700",
        }
        config = {
            "JLA_API_KEY": "test-api-key",
            "JLA_INGESTION_AUTHORIZED": "true",
        }
        with (
            patch.dict(os.environ, config, clear=True),
            patch.object(
                ingestion,
                "_load_job_listings_api_jobs",
                return_value=([provider_job], False, {}),
            ),
            patch.object(ingestion, "_require_staging_job_target"),
            patch.object(ingestion, "_reconcile_job_listings_api_statuses",
                         return_value={"closed": 0, "expired": 0, "missing_closed": 0}),
        ):
            first = ingestion.synchronize_configured_sources()
            second = ingestion.synchronize_configured_sources()

        self.assertEqual(first["sources"]["Job Listings API"]["inserted"], 1)
        self.assertEqual(second["sources"]["Job Listings API"]["updated"], 1)
        self.assertEqual(len(self.database.jobs), 1)
        stored = self.database.jobs[("Job Listings API", "700")]
        self.assertEqual(stored["source_url"], "https://jobs.example.com/700")
        self.assertEqual(stored["work_mode"], "on_site")

    def test_usajobs_skills_are_persisted_and_source_is_attributed(self):
        provider_job = {
            "MatchedObjectId": "usa-123",
            "MatchedObjectDescriptor": {
                "PositionTitle": "Data Analyst",
                "OrganizationName": "Example Agency",
                "PositionLocationDisplay": "Remote",
                "PositionURI": "https://www.usajobs.gov/job/usa-123",
                "UserArea": {
                    "Details": {
                        "JobSummary": "Analyze data using Python and SQL."
                    }
                },
            },
        }
        result = ingestion._sync_source(
            ingestion.USAJOBS_SOURCE_NAME,
            [provider_job],
            ingestion._parse_usajobs_job,
        )
        stored = self.database.jobs[(ingestion.USAJOBS_SOURCE_NAME, "usa-123")]
        stored_skills = {
            next(
                name for name, skill_id in self.database.skills.items()
                if skill_id == linked_skill
            )
            for job_id, linked_skill in self.database.links
            if job_id == stored["id"]
        }

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(
            stored["source_url"],
            provider_job["MatchedObjectDescriptor"]["PositionURI"],
        )
        self.assertEqual(stored_skills, {"Python", "SQL"})

    def test_usajobs_is_not_configured_without_registered_credentials(self):
        empty_provider_config = {
            "THE_MUSE_API_KEY": "",
            "USAJOBS_API_KEY": "",
            "USAJOBS_USER_AGENT_EMAIL": "",
            "LEVER_SITE_COMPANIES": "",
            "GREENHOUSE_BOARDS": "",
            "ARBEITNOW_ENABLED": "false",
        }
        with patch.dict(os.environ, empty_provider_config):
            result = ingestion.synchronize_configured_sources()

        self.assertEqual(
            result["sources"][ingestion.USAJOBS_SOURCE_NAME]["status"],
            "not_configured",
        )
        self.assertNotIn(ingestion.USAJOBS_SOURCE_NAME, result["attempted_sources"])

    def test_usajobs_partial_credentials_fail_without_requesting_api(self):
        empty_provider_config = {
            "THE_MUSE_API_KEY": "",
            "USAJOBS_API_KEY": "test-api-key",
            "USAJOBS_USER_AGENT_EMAIL": "",
            "LEVER_SITE_COMPANIES": "",
            "GREENHOUSE_BOARDS": "",
            "ARBEITNOW_ENABLED": "false",
        }
        with (
            patch.dict(os.environ, empty_provider_config),
            patch.object(ingestion, "_load_usajobs_jobs") as load_jobs,
        ):
            result = ingestion.synchronize_configured_sources()

        self.assertEqual(
            result["sources"][ingestion.USAJOBS_SOURCE_NAME]["status"],
            "failed",
        )
        load_jobs.assert_not_called()

    def test_maps_arbeitnow_job_fields_and_html_description(self):
        provider_job = {
            "slug": "backend-python-123",
            "company_name": "Example GmbH",
            "title": "Backend Engineer",
            "description": (
                "&lt;p&gt;Build APIs using &lt;strong&gt;Python"
                "&lt;/strong&gt; and PostgreSQL.&lt;/p&gt;"
            ),
            "remote": True,
            "url": (
                "https://www.arbeitnow.com/jobs/example/backend-python-123"
            ),
            "location": "Berlin",
            "created_at": 1775040000,
        }
        mapped = ingestion._parse_arbeitnow_job(provider_job)

        self.assertEqual(mapped["source_job_id"], "backend-python-123")
        self.assertEqual(mapped["source_url"], (
            "https://www.arbeitnow.com/jobs/example/backend-python-123"
        ))
        self.assertEqual(mapped["company"], "Example GmbH")
        self.assertEqual(mapped["location"], "Remote - Berlin")
        self.assertEqual(mapped["work_mode"], "remote")
        self.assertEqual(mapped["description"], "Build APIs using Python and PostgreSQL.")
        self.assertEqual(mapped["skills"], ["PostgreSQL", "Python"])
        self.assertEqual(mapped["posted_at"], datetime(2026, 4, 1, 10, 40))

        provider_job["url"] = (
            "https://www.arbeitnow.co.uk/jobs/example/backend-python-123"
        )
        self.assertEqual(
            ingestion._parse_arbeitnow_job(provider_job)["source_url"],
            provider_job["url"],
        )

    def test_maps_greenhouse_job_and_namespaces_board_job_id(self):
        mapped = ingestion._parse_greenhouse_job(
            {
                "id": 42,
                "title": "Data Engineer",
                "company_name": "Example Inc.",
                "absolute_url": (
                    "https://job-boards.greenhouse.io/example/jobs/42"
                ),
                "location": {"name": "New York"},
                "content": (
                    "&lt;p&gt;Build data pipelines with Python and SQL.&lt;/p&gt;"
                ),
                "first_published": "2026-04-02T12:30:00Z",
            },
            "example",
            "Configured Example",
        )

        self.assertEqual(mapped["source_job_id"], "example:42")
        self.assertEqual(mapped["company"], "Example Inc.")
        self.assertEqual(mapped["location"], "New York")
        self.assertEqual(mapped["work_mode"], "unknown")
        self.assertEqual(mapped["description"], "Build data pipelines with Python and SQL.")
        self.assertEqual(mapped["skills"], ["Python", "SQL"])
        self.assertEqual(mapped["posted_at"], datetime(2026, 4, 2, 12, 30))

    def test_maps_lever_postings_and_optional_remote_fields(self):
        mapped = ingestion._parse_lever_job(
            {
                "id": "lever-123",
                "text": "Python Engineer",
                "categories": {
                    "allLocations": ["Remote", "US"],
                    "commitment": "Full-time",
                },
                "descriptionPlain": "Build APIs with Python.",
                "hostedUrl": "https://jobs.lever.co/example/lever-123",
                "workplaceType": "remote",
            },
            "example",
            "Example Inc",
        )

        self.assertEqual(mapped["source_job_id"], "example:lever-123")
        self.assertEqual(mapped["company"], "Example Inc")
        self.assertEqual(mapped["location"], "Remote, US")
        self.assertEqual(mapped["work_mode"], "remote")
        self.assertEqual(
            mapped["description"],
            "Employment type: Full-time\n\nBuild APIs with Python.",
        )
        self.assertIsNone(mapped["posted_at"])
        self.assertIn("Python", mapped["skills"])

    def test_lever_mapping_includes_html_qualification_lists_and_extra_details(self):
        provider_job = {
            "id": "lever-qualifications",
            "text": "Account Executive",
            "hostedUrl": "https://jobs.lever.co/example/lever-qualifications",
            "descriptionPlain": "Sell solutions to established clients.",
            "lists": [
                {
                    "text": "Education and Experience",
                    "content": (
                        "<ul><li>Use Salesforce.com, MS-Excel, "
                        "MS-PowerPoint and MS-Word.</li>"
                        "<li>Apply consultative selling and "
                        "customer engagement skills.</li></ul>"
                    ),
                },
                {
                    "text": "Essential Skills",
                    "content": (
                        "<p>Strong communication and business development "
                        "skills.</p><p>Strong time-management skills.</p>"
                    ),
                },
            ],
            "additionalPlain": "Further details for applicants.",
        }

        mapped = ingestion._parse_lever_job(
            provider_job,
            "example",
            "Example Inc",
        )

        self.assertIn("Education and Experience", mapped["description"])
        self.assertIn("Further details for applicants.", mapped["description"])
        self.assertNotIn("<li>", mapped["description"])
        self.assertEqual(
            mapped["skills"],
            [
                "Consultative Selling",
                "Customer Engagement",
                "Business Development",
                "Communication",
                "Time Management",
                "Salesforce",
                "PowerPoint",
                "Microsoft Word",
                "Excel",
            ],
        )
        self.assertEqual(len(mapped["skills"]), len(set(mapped["skills"])))

    def test_lever_list_skills_are_persisted_and_retrievable(self):
        provider_job = {
            "id": "lever-stored-skills",
            "text": "Account Executive",
            "hostedUrl": "https://jobs.lever.co/example/lever-stored-skills",
            "descriptionPlain": "Build customer relationships.",
            "lists": [
                {
                    "text": "Qualifications",
                    "content": "<li>Use Salesforce.com and MS-Excel.</li>",
                }
            ],
        }
        result = ingestion._sync_source(
            "Lever",
            [(provider_job, "example", "Example Inc")],
            lambda record: ingestion._parse_lever_job(*record),
        )
        stored = self.database.jobs[("Lever", "example:lever-stored-skills")]
        stored_skills = {
            next(name for name, skill_id in self.database.skills.items()
                 if skill_id == linked_skill)
            for job_id, linked_skill in self.database.links
            if job_id == stored["id"]
        }

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(stored["requirements"], "Salesforce\nExcel")
        self.assertEqual(stored_skills, {"Salesforce", "Excel"})

    def test_lever_missing_or_empty_description_has_no_detected_skills(self):
        base = {
            "id": "lever-no-description",
            "text": "Operations Associate",
            "hostedUrl": "https://jobs.lever.co/example/lever-no-description",
        }
        for description in (None, ""):
            with self.subTest(description=description):
                provider_job = dict(base)
                if description is not None:
                    provider_job["descriptionPlain"] = description
                mapped = ingestion._parse_lever_job(
                    provider_job,
                    "example",
                    "Example Inc",
                )

                self.assertIsNone(mapped["description"])
                self.assertIsNone(mapped["requirements"])
                self.assertIsNone(mapped["skills"])

    def test_lever_malformed_description_sections_are_rejected(self):
        invalid_jobs = [
            {
                "descriptionPlain": {"unexpected": "not text"},
            },
            {
                "descriptionPlain": "Valid intro.",
                "lists": [{"text": "Requirements", "content": None}],
            },
            {
                "descriptionPlain": "Valid intro.",
                "lists": "not a list",
            },
        ]

        for description_fields in invalid_jobs:
            with self.subTest(description_fields=description_fields):
                provider_job = {
                    "id": "lever-malformed",
                    "text": "Engineer",
                    "hostedUrl": "https://jobs.lever.co/example/lever-malformed",
                    **description_fields,
                }
                with self.assertRaises(ValueError):
                    ingestion._parse_lever_job(
                        provider_job,
                        "example",
                        "Example Inc",
                    )

    def test_skill_extraction_normalizes_and_deduplicates_supported_terms(self):
        extracted = ingestion.extract_skills(
            "Python, python; MS-Excel, Excel; Salesforce.com; "
            "and time\u2011management."
        )

        self.assertEqual(
            extracted,
            ["Time Management", "Salesforce", "Python", "Excel"],
        )
        self.assertEqual(len(extracted), len(set(extracted)))

    def test_skill_extraction_ignores_unsupported_or_ambiguous_terms(self):
        extracted = ingestion.extract_skills(
            "Sales technology, CRM experience, and a single word about power."
        )

        self.assertEqual(extracted, [])

    def test_lever_workplace_types_map_to_canonical_location_labels(self):
        expected_locations = {
            "onsite": "On Site",
            "on-site": "On Site",
            "remote": "Remote",
            "hybrid": "Hybrid",
            "unspecified": None,
        }

        for workplace_type, expected_location in expected_locations.items():
            with self.subTest(workplace_type=workplace_type):
                mapped = ingestion._parse_lever_job(
                    {
                        "id": "lever-workplace",
                        "text": "Engineer",
                        "hostedUrl": (
                            "https://jobs.lever.co/example/lever-workplace"
                        ),
                        "workplaceType": workplace_type,
                    },
                    "example",
                    "Example Inc",
                )

                self.assertEqual(mapped["location"], expected_location)

    def test_lever_workplace_type_rejects_unexpected_values(self):
        with self.assertRaisesRegex(ValueError, "Invalid workplace type"):
            ingestion._parse_lever_job(
                {
                    "id": "lever-invalid-workplace",
                    "text": "Engineer",
                    "hostedUrl": (
                        "https://jobs.lever.co/example/lever-invalid-workplace"
                    ),
                    "workplaceType": "office",
                },
                "example",
                "Example Inc",
            )

    def test_work_mode_uses_provider_fields_and_unknown_for_missing_evidence(self):
        base = {
            "id": "lever-mode",
            "text": "Engineer",
            "hostedUrl": "https://jobs.lever.co/example/lever-mode",
        }
        for provider_value, expected in (
            ("onsite", "on_site"),
            ("on-site", "on_site"),
            ("remote", "remote"),
            ("hybrid", "hybrid"),
            ("unspecified", "unknown"),
            (None, "unknown"),
        ):
            with self.subTest(provider_value=provider_value):
                provider_job = dict(base)
                if provider_value is not None:
                    provider_job["workplaceType"] = provider_value
                self.assertEqual(
                    ingestion._parse_lever_job(
                        provider_job, "example", "Example Inc"
                    )["work_mode"],
                    expected,
                )

    def test_provider_mappers_reject_invalid_urls_and_incomplete_records(self):
        with self.assertRaises(ValueError):
            ingestion._parse_the_muse_job(
                {
                    "id": 1,
                    "name": "Engineer",
                    "company": {"name": "Example"},
                    "locations": [],
                    "contents": "",
                    "refs": {"landing_page": "https://example.com/job"},
                }
            )
        with self.assertRaises(ValueError):
            ingestion._parse_lever_job(
                {
                    "id": 1,
                    "text": "",
                    "hostedUrl": "https://jobs.lever.co/example/job",
                },
                "example",
                "Example",
            )
        with self.assertRaisesRegex(ValueError, "Invalid source URL"):
            ingestion._parse_arbeitnow_job(
                {
                    "slug": "bad-url",
                    "title": "Engineer",
                    "company_name": "Example",
                    "url": "https://jobs.example.test/opening",
                    "description": "",
                }
            )

    def test_lever_site_configuration_supports_global_and_eu_boards(self):
        configured = {
            "global-board": "Global Example",
            "eu-board": {"company": "EU Example", "region": "eu"},
        }
        with patch.dict(
            os.environ,
            {"LEVER_SITE_COMPANIES": json.dumps(configured)},
            clear=True,
        ):
            sites = ingestion._configured_lever_sites()

        self.assertEqual(sites["global-board"]["region"], "global")
        self.assertEqual(sites["eu-board"]["company"], "EU Example")
        self.assertEqual(sites["eu-board"]["region"], "eu")

    def test_greenhouse_board_configuration_validates_public_board_mapping(self):
        with patch.dict(
            os.environ,
            {
                "GREENHOUSE_BOARDS": json.dumps(
                    {
                        "gitlab": "GitLab",
                        "coinbase": {
                            "company": "Coinbase",
                            "url_hosts": ["www.coinbase.com"],
                        },
                    }
                )
            },
            clear=True,
        ):
            boards = ingestion._configured_greenhouse_boards()

        self.assertEqual(
            boards,
            {
                "gitlab": {"company": "GitLab", "url_hosts": []},
                "coinbase": {
                    "company": "Coinbase",
                    "url_hosts": ["www.coinbase.com"],
                },
            },
        )

    def test_greenhouse_custom_link_hosts_are_explicit_and_strict(self):
        board = ingestion._configured_greenhouse_boards
        with patch.dict(
            os.environ,
            {
                "GREENHOUSE_BOARDS": json.dumps(
                    {
                        "coinbase": {
                            "company": "Coinbase",
                            "url_hosts": ["www.coinbase.com"],
                        }
                    }
                )
            },
            clear=True,
        ):
            configured = board()["coinbase"]

        provider_job = {
            "id": 5,
            "title": "Finance Analyst",
            "company_name": "Coinbase",
            "absolute_url": "https://www.coinbase.com/careers/positions/5",
            "location": {"name": "Remote"},
            "content": "Analyze reports.",
        }
        mapped = ingestion._parse_greenhouse_job(
            provider_job,
            "coinbase",
            configured["company"],
            configured["url_hosts"],
        )
        self.assertEqual(mapped["source_url"], provider_job["absolute_url"])

        provider_job["absolute_url"] = "https://jobs.example.test/posting/5"
        with self.assertRaisesRegex(ValueError, "Invalid source URL"):
            ingestion._parse_greenhouse_job(
                provider_job,
                "coinbase",
                configured["company"],
                configured["url_hosts"],
            )

    def test_greenhouse_board_config_rejects_invalid_custom_hosts(self):
        with patch.dict(
            os.environ,
            {
                "GREENHOUSE_BOARDS": json.dumps(
                    {
                        "coinbase": {
                            "company": "Coinbase",
                            "url_hosts": ["https://www.coinbase.com"],
                        }
                    }
                )
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                ingestion._configured_greenhouse_boards()

    @patch.object(ingestion, "_request_json")
    def test_arbeitnow_loader_follows_documented_next_page(self, request_json):
        request_json.side_effect = [
            {"data": [{"slug": "one"}], "links": {"next": "page-2"}},
            {"data": [{"slug": "two"}], "links": {"next": None}},
        ]

        jobs = ingestion._load_arbeitnow_jobs()

        self.assertEqual([job["slug"] for job in jobs], ["one", "two"])
        self.assertEqual(
            request_json.call_args_list,
            [
                unittest.mock.call(ingestion.ARBEITNOW_API_URL, {"page": 1}),
                unittest.mock.call(ingestion.ARBEITNOW_API_URL, {"page": 2}),
            ],
        )

    @patch.object(ingestion, "_request_json")
    def test_arbeitnow_loader_requests_page_three_within_bounded_limit(
        self, request_json
    ):
        request_json.side_effect = [
            {"data": [{"slug": "page-1"}], "links": {"next": "page-2"}},
            {"data": [{"slug": "page-2"}], "links": {"next": "page-3"}},
            {"data": [{"slug": "page-3"}], "links": {"next": "page-4"}},
        ]

        jobs = ingestion._load_arbeitnow_jobs()

        self.assertEqual([job["slug"] for job in jobs], [
            "page-1", "page-2", "page-3"
        ])
        self.assertEqual(request_json.call_count, ingestion.MAX_ARBEITNOW_PAGES)
        self.assertEqual(
            request_json.call_args_list[-1],
            unittest.mock.call(
                ingestion.ARBEITNOW_API_URL,
                {"page": ingestion.MAX_ARBEITNOW_PAGES},
            ),
        )

    @patch.object(ingestion, "_request_json")
    def test_arbeitnow_page_failure_aborts_before_partial_page_sync(
        self, request_json
    ):
        request_json.side_effect = [
            {"data": [{"slug": "page-1"}], "links": {"next": "page-2"}},
            ingestion._ProviderError("Upstream request failed"),
        ]

        with self.assertRaises(ingestion._ProviderError):
            ingestion._load_arbeitnow_jobs()

        self.assertEqual(request_json.call_count, 2)

    @patch.object(ingestion, "_request_json")
    def test_greenhouse_loader_calls_public_content_get(self, request_json):
        request_json.return_value = {"jobs": [{"id": 1}]}

        jobs = ingestion._load_greenhouse_jobs("gitlab")

        self.assertEqual(jobs, [{"id": 1}])
        request_json.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/gitlab/jobs",
            {"content": "true"},
        )

    def test_arbeitnow_requires_explicit_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ingestion._arbeitnow_enabled())
        with patch.dict(os.environ, {"ARBEITNOW_ENABLED": "true"}, clear=True):
            self.assertTrue(ingestion._arbeitnow_enabled())
        with patch.dict(
            os.environ, {"ARBEITNOW_ENABLED": "sometimes"}, clear=True
        ):
            with self.assertRaises(ValueError):
                ingestion._arbeitnow_enabled()

    def test_invalid_or_incomplete_upstream_record_is_rejected(self):
        invalid = remotive_job(title="")
        with self.assertRaises(ValueError):
            ingestion._parse_job(invalid)

        with patch.object(
            ingestion.requests,
            "get",
            return_value=type(
                "Response",
                (),
                {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {"unexpected": []},
                },
            )(),
        ):
            with self.assertRaises(Exception) as raised:
                ingestion._load_remotive_jobs()
        self.assertEqual(getattr(raised.exception, "status_code", None), 502)

    @patch.object(ingestion.requests, "get")
    def test_provider_timeout_is_reported_as_bad_gateway(self, get):
        import requests

        get.side_effect = ingestion.requests.Timeout()
        with self.assertRaises(Exception) as raised:
            ingestion._load_remotive_jobs()

        self.assertEqual(getattr(raised.exception, "status_code", None), 502)
        get.assert_called_once_with(
            ingestion.REMOTIVE_API_URL, timeout=ingestion.REQUEST_TIMEOUT
        )

    @patch.object(ingestion, "_load_remotive_jobs")
    def test_duplicate_ids_update_existing_listing_without_duplicate_rows(self, load):
        load.return_value = [remotive_job(), remotive_job()]

        summary = ingestion.synchronize_remotive_jobs()

        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(len(self.database.jobs), 1)
        self.assertEqual(len(self.database.links), 2)
        self.assertEqual(self.database.commit_count, 2)

    @patch.object(ingestion, "_load_remotive_jobs")
    def test_repeat_sync_updates_job_and_replaces_provider_skills(self, load):
        load.return_value = [remotive_job()]
        first = ingestion.synchronize_remotive_jobs()
        load.return_value = [
            remotive_job(title="Updated Engineer", tags=["Go"])
        ]
        second = ingestion.synchronize_remotive_jobs()

        stored = next(iter(self.database.jobs.values()))
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(stored["title"], "Updated Engineer")
        self.assertEqual(len(self.database.jobs), 1)
        self.assertEqual(len(self.database.links), 1)
        linked_skill = next(iter(self.database.links))[1]
        self.assertEqual(
            next(name for name, skill_id in self.database.skills.items()
                 if skill_id == linked_skill),
            "Go",
        )

    @patch.object(ingestion, "_load_remotive_jobs")
    def test_invalid_listing_is_skipped_and_reported(self, load):
        load.return_value = [remotive_job(), remotive_job(124, title="")]

        summary = ingestion.synchronize_remotive_jobs()

        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["errors"], [
            {"source_job_id": "124", "error": "Invalid job record"}
        ])
        self.assertEqual(len(self.database.jobs), 1)

    @patch.object(ingestion, "_load_remotive_jobs")
    def test_jobs_absent_from_provider_response_are_preserved(self, load):
        existing = {
            "id": 40,
            "title": "Manually managed listing",
            "status": "closed",
        }
        self.database.jobs[("Manual", "existing")] = existing
        load.return_value = [remotive_job()]

        summary = ingestion.synchronize_remotive_jobs()

        self.assertEqual(summary["inserted"], 1)
        self.assertIs(
            self.database.jobs[("Manual", "existing")],
            existing,
        )

    @patch.object(ingestion, "_load_remotive_jobs")
    def test_database_failure_rolls_back_only_failed_listing(self, load):
        self.database.fail_on_skill = "FailSkill"
        load.return_value = [
            remotive_job(123),
            remotive_job(124, tags=["FailSkill"]),
        ]

        summary = ingestion.synchronize_remotive_jobs()

        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["errors"], [
            {"source_job_id": "124", "error": "Database write failed"}
        ])
        self.assertEqual(len(self.database.jobs), 1)
        self.assertEqual(self.database.rollback_count, 1)
        self.assertTrue(self.database.cursor_instance.closed)
        self.assertTrue(self.database.closed)

    def test_configured_source_sync_is_repeatable_and_updates_existing_rows(self):
        job = {
            "source_job_id": "lever-repeat",
            "source_url": "https://jobs.lever.co/example/lever-repeat",
            "title": "Python Engineer",
            "company": "Example",
            "location": "Remote",
            "description": "Build Python services.",
            "requirements": "Python",
            "skills": ["Python"],
            "posted_at": datetime(2026, 4, 1),
        }
        first = ingestion._sync_source("Lever", [job], lambda record: record)
        update = dict(job)
        update.update(
            title="Senior Python Engineer",
            location="",
            description="",
            requirements="",
            skills=None,
            posted_at=None,
        )
        second = ingestion._sync_source("Lever", [update], lambda record: record)

        stored = self.database.jobs[("Lever", "lever-repeat")]
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(self.database.jobs), 1)
        self.assertEqual(stored["title"], "Senior Python Engineer")
        self.assertEqual(stored["location"], "Remote")
        self.assertEqual(stored["description"], "Build Python services.")
        self.assertEqual(len(self.database.links), 1)

    def test_duplicate_arbeitnow_source_ids_do_not_create_duplicate_jobs(self):
        provider_record = {
            "slug": "arbeitnow-stable-id",
            "company_name": "Example GmbH",
            "title": "Support Analyst",
            "description": "Support customer operations.",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/example/support-analyst",
            "location": "Berlin",
            "created_at": 1775040000,
        }

        summary = ingestion._sync_source(
            "Arbeitnow",
            [provider_record, dict(provider_record)],
            ingestion._parse_arbeitnow_job,
        )

        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(len(self.database.jobs), 1)
        self.assertIn(
            ("Arbeitnow", "arbeitnow-stable-id"),
            self.database.jobs,
        )

    def test_greenhouse_ids_are_scoped_to_each_board(self):
        provider_job = {
            "id": 1,
            "title": "Operations Analyst",
            "company_name": None,
            "absolute_url": "https://boards.greenhouse.io/board/jobs/1",
            "location": {"name": "Remote"},
            "content": "Coordinate operations.",
        }
        records = [
            (provider_job, "board-one", "Company One", []),
            (provider_job, "board-two", "Company Two", []),
        ]

        summary = ingestion._sync_source(
            "Greenhouse",
            records,
            lambda record: ingestion._parse_greenhouse_job(*record),
        )

        self.assertEqual(summary["inserted"], 2)
        self.assertEqual(
            set(self.database.jobs),
            {
                ("Greenhouse", "board-one:1"),
                ("Greenhouse", "board-two:1"),
            },
        )

    @patch.object(ingestion, "_load_lever_jobs")
    @patch.object(ingestion, "_load_the_muse_jobs")
    def test_source_failures_are_isolated_and_invalid_records_are_counted(
        self, muse_load, lever_load
    ):
        muse_load.side_effect = ingestion._ProviderError("Upstream request failed")
        lever_load.return_value = [
            {
                "id": "lever-1",
                "text": "Python Engineer",
                "categories": {},
                "descriptionPlain": "Build with Python.",
                "hostedUrl": "https://jobs.lever.co/example/lever-1",
                "createdAt": None,
            },
            {"id": False},
        ]
        configured = {
            "THE_MUSE_API_KEY": "test-api-key",
            "THE_MUSE_INGESTION_AUTHORIZED": "true",
            "LEVER_SITE_COMPANIES": json.dumps({"example": "Example Inc"}),
            "LEVER_INGESTION_AUTHORIZED": "true",
        }

        with patch.dict(os.environ, configured, clear=True):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(summary["attempted_sources"], ["The Muse", "Lever"])
        self.assertEqual(summary["successful_sources"], [])
        self.assertEqual(summary["sources"]["The Muse"]["status"], "failed")
        self.assertEqual(summary["sources"]["Lever"]["status"], "partial")
        self.assertEqual(summary["sources"]["Lever"]["inserted"], 1)
        self.assertEqual(summary["sources"]["Lever"]["skipped"], 1)
        self.assertEqual(summary["errors"], summary["failures"])
        self.assertEqual(len(self.database.jobs), 1)
        self.assertNotIn("test-api-key", repr(summary))

    @patch.object(ingestion, "_load_lever_jobs")
    def test_one_lever_site_failure_does_not_discard_another_site(self, load):
        load.side_effect = [
            [
                {
                    "id": "lever-1",
                    "text": "Data Analyst",
                    "categories": {},
                    "descriptionPlain": "Analyze data.",
                    "hostedUrl": "https://jobs.lever.co/first/lever-1",
                    "createdAt": None,
                }
            ],
            ingestion._ProviderError("Upstream request failed"),
        ]
        config = {
            "LEVER_SITE_COMPANIES": json.dumps(
                {"first": "First Company", "second": "Second Company"}
            ),
            "LEVER_INGESTION_AUTHORIZED": "true",
        }

        with patch.dict(os.environ, config, clear=True):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(summary["sources"]["Lever"]["status"], "partial")
        self.assertEqual(summary["sources"]["Lever"]["inserted"], 1)
        self.assertEqual(
            summary["sources"]["Lever"]["sites"]["second"]["status"], "failed"
        )
        self.assertEqual(len(self.database.jobs), 1)

    def test_configured_source_database_failure_rolls_back_only_failed_job(self):
        self.database.fail_on_skill = "Python"
        records = [
            {
                "source_job_id": "first",
                "source_url": "https://jobs.lever.co/example/first",
                "title": "Analyst",
                "company": "Example",
                "location": None,
                "description": "Review records.",
                "requirements": None,
                "skills": None,
                "posted_at": None,
            },
            {
                "source_job_id": "second",
                "source_url": "https://jobs.lever.co/example/second",
                "title": "Python Engineer",
                "company": "Example",
                "location": None,
                "description": "Build with Python.",
                "requirements": "Python",
                "skills": ["Python"],
                "posted_at": None,
            },
        ]

        summary = ingestion._sync_source("Lever", records, lambda record: record)

        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["errors"], [{"error": "Database write failed"}])
        self.assertEqual(len(self.database.jobs), 1)
        self.assertEqual(self.database.rollback_count, 1)
        self.assertTrue(self.database.cursor_instance.closed)
        self.assertTrue(self.database.closed)

    def test_unconfigured_sources_are_reported_without_requests(self):
        with patch.dict(os.environ, {}, clear=True):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(summary["attempted_sources"], [])
        self.assertEqual(summary["successful_sources"], [])
        self.assertEqual(summary["sources"]["The Muse"]["status"], "not_configured")
        self.assertEqual(summary["sources"]["Lever"]["status"], "not_configured")
        self.assertEqual(summary["sources"]["Arbeitnow"]["status"], "not_configured")
        self.assertEqual(summary["sources"]["Greenhouse"]["status"], "not_configured")
        self.assertEqual(
            summary["sources"]["Job Listings API"]["status"], "not_configured"
        )

    @patch.object(ingestion, "_load_greenhouse_jobs")
    @patch.object(ingestion, "_load_arbeitnow_jobs")
    def test_configured_public_sources_sync_and_deduplicate(self, arbeitnow, greenhouse):
        arbeitnow.return_value = [{
            "slug": "arbeitnow-python-1",
            "company_name": "Example GmbH",
            "title": "Python Engineer",
            "description": "Build APIs using Python.",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/example/python-1",
            "location": "Berlin",
            "created_at": 1775040000,
        }]
        greenhouse.return_value = [{
            "id": 1,
            "title": "SQL Analyst",
            "company_name": "GitLab",
            "absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/1",
            "location": {"name": "Remote"},
            "content": "<p>Use SQL to analyze data.</p>",
            "first_published": "2026-04-02T12:30:00Z",
        }]
        config = {
            "ARBEITNOW_ENABLED": "true",
            "ARBEITNOW_INGESTION_AUTHORIZED": "true",
            "GREENHOUSE_BOARDS": json.dumps({"gitlab": "GitLab"}),
            "GREENHOUSE_INGESTION_AUTHORIZED": "true",
        }

        with patch.dict(os.environ, config, clear=True):
            first = ingestion.synchronize_configured_sources()
            second = ingestion.synchronize_configured_sources()

        self.assertEqual(first["sources"]["Arbeitnow"]["inserted"], 1)
        self.assertEqual(first["sources"]["Greenhouse"]["inserted"], 1)
        self.assertEqual(second["sources"]["Arbeitnow"]["updated"], 1)
        self.assertEqual(second["sources"]["Greenhouse"]["updated"], 1)
        self.assertEqual(len(self.database.jobs), 2)

    @patch.object(ingestion, "_load_greenhouse_jobs")
    @patch.object(ingestion, "_load_arbeitnow_jobs")
    def test_public_provider_failure_does_not_block_other_source(
        self, arbeitnow, greenhouse
    ):
        arbeitnow.side_effect = ingestion._ProviderError(
            "Upstream request failed"
        )
        greenhouse.return_value = [{
            "id": 1,
            "title": "Python Engineer",
            "company_name": "GitLab",
            "absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/1",
            "location": {"name": "Remote"},
            "content": "<p>Build services with Python.</p>",
        }]

        with patch.dict(
            os.environ,
            {
                "ARBEITNOW_ENABLED": "true",
                "ARBEITNOW_INGESTION_AUTHORIZED": "true",
                "GREENHOUSE_BOARDS": json.dumps({"gitlab": "GitLab"}),
                "GREENHOUSE_INGESTION_AUTHORIZED": "true",
            },
            clear=True,
        ):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(summary["sources"]["Arbeitnow"]["status"], "failed")
        self.assertEqual(summary["sources"]["Greenhouse"]["status"], "succeeded")
        self.assertEqual(summary["sources"]["Greenhouse"]["inserted"], 1)
        self.assertEqual(len(self.database.jobs), 1)

    @patch.object(ingestion, "_sync_source")
    @patch.object(ingestion, "_load_arbeitnow_jobs")
    def test_arbeitnow_record_limit_is_enforced_before_writes(
        self, load, sync
    ):
        load.return_value = [{}] * (
            ingestion.MAX_ARBEITNOW_PAGES * ingestion.ARBEITNOW_PAGE_SIZE + 1
        )
        sync.return_value = {
            "status": "succeeded",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
        }

        with patch.dict(
            os.environ,
            {
                "ARBEITNOW_ENABLED": "true",
                "ARBEITNOW_INGESTION_AUTHORIZED": "true",
            },
            clear=True,
        ):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(
            len(sync.call_args.args[1]),
            ingestion.MAX_ARBEITNOW_PAGES * ingestion.ARBEITNOW_PAGE_SIZE,
        )
        self.assertEqual(
            summary["sources"]["Arbeitnow"]["record_limit"],
            ingestion.MAX_ARBEITNOW_PAGES * ingestion.ARBEITNOW_PAGE_SIZE,
        )

    @patch.object(ingestion, "_sync_source")
    @patch.object(ingestion, "_load_greenhouse_jobs")
    def test_greenhouse_record_limit_is_enforced_before_writes(
        self, load, sync
    ):
        load.return_value = [{}] * (ingestion.MAX_GREENHOUSE_JOBS_PER_BOARD + 1)
        sync.return_value = {
            "status": "succeeded",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
        }

        with patch.dict(
            os.environ,
            {
                "GREENHOUSE_BOARDS": json.dumps({"gitlab": "GitLab"}),
                "GREENHOUSE_INGESTION_AUTHORIZED": "true",
            },
            clear=True,
        ):
            summary = ingestion.synchronize_configured_sources()

        self.assertEqual(len(sync.call_args.args[1]), 1000)
        self.assertEqual(
            summary["sources"]["Greenhouse"]["boards"]["gitlab"]["record_limit"],
            1000,
        )

    def test_unapproved_sources_are_disabled_before_any_provider_request(self):
        config = {
            "THE_MUSE_API_KEY": "test-api-key",
            "JLA_API_KEY": "test-api-key",
            "LEVER_SITE_COMPANIES": json.dumps({"example": "Example Inc"}),
            "GREENHOUSE_BOARDS": json.dumps({"board": "Example Inc"}),
            "ARBEITNOW_ENABLED": "true",
            "THE_MUSE_RECOMMENDATIONS_AUTHORIZED": "true",
            "LEVER_RECOMMENDATIONS_AUTHORIZED": "true",
            "GREENHOUSE_RECOMMENDATIONS_AUTHORIZED": "true",
            "ARBEITNOW_RECOMMENDATIONS_AUTHORIZED": "true",
        }
        with (
            patch.dict(os.environ, config, clear=True),
            patch.object(ingestion, "_load_the_muse_jobs") as muse,
            patch.object(ingestion, "_load_lever_jobs") as lever,
            patch.object(ingestion, "_load_greenhouse_jobs") as greenhouse,
            patch.object(ingestion, "_load_arbeitnow_jobs") as arbeitnow,
            patch.object(ingestion, "_load_job_listings_api_jobs") as jla,
            patch.object(ingestion, "_sync_source") as sync,
        ):
            summary = ingestion.synchronize_configured_sources()

        for source in (
            ingestion.THE_MUSE_SOURCE_NAME,
            "Lever",
            ingestion.GREENHOUSE_SOURCE_NAME,
            ingestion.ARBEITNOW_SOURCE_NAME,
            ingestion.JOB_LISTINGS_API_SOURCE_NAME,
        ):
            self.assertEqual(
                summary["sources"][source]["status"],
                "disabled_pending_permission",
            )
        self.assertEqual(summary["attempted_sources"], [])
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(self.database.jobs, {})
        muse.assert_not_called()
        lever.assert_not_called()
        greenhouse.assert_not_called()
        arbeitnow.assert_not_called()
        jla.assert_not_called()
        sync.assert_not_called()

    def test_dataset_diagnostics_are_read_only_and_serialize_timestamps(self):
        source_row = {
            "source_name": "Lever",
            "total_jobs": 2,
            "distinct_source_ids": 2,
            "missing_source_ids": 0,
            "missing_source_urls": 0,
            "missing_descriptions": 0,
            "jobs_without_skills": 1,
            "open_jobs": 2,
            "closed_jobs": 0,
            "expired_jobs": 0,
            "missing_sync_timestamps": 0,
            "oldest_last_synced_at": datetime(2026, 10, 18, 10, 0),
            "newest_last_synced_at": datetime(2026, 10, 18, 11, 0),
        }

        class DiagnosticsCursor:
            def __init__(self):
                self.rows = []
                self.row = None
                self.statements = []
                self.closed = False

            def execute(self, query):
                self.statements.append(query)
                if "GROUP BY j.source_name" in query:
                    self.rows = [source_row]
                elif "duplicate_source_keys" in query:
                    self.row = {"duplicate_source_keys": 0}
                else:
                    self.row = {"total_jobs": 2}

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.row

            def close(self):
                self.closed = True

        class DiagnosticsConnection:
            def __init__(self):
                self.cursor_instance = DiagnosticsCursor()
                self.closed = False

            def cursor(self, **kwargs):
                return self.cursor_instance

            def close(self):
                self.closed = True

        connection = DiagnosticsConnection()
        with patch.object(
            ingestion, "get_db_connection", return_value=connection
        ):
            result = ingestion.get_job_dataset_diagnostics()

        self.assertEqual(result["total_jobs"], 2)
        self.assertEqual(result["duplicate_source_keys"], 0)
        self.assertEqual(result["sources"][0]["jobs_without_skills"], 1)
        self.assertEqual(
            result["sources"][0]["oldest_last_synced_at"],
            "2026-10-18 10:00:00",
        )
        self.assertTrue(
            all(query.lstrip().upper().startswith("SELECT")
                for query in connection.cursor_instance.statements)
        )
        self.assertTrue(connection.cursor_instance.closed)
        self.assertTrue(connection.closed)

    def test_dataset_diagnostics_reports_database_failure(self):
        with patch.object(ingestion, "get_db_connection", return_value=None):
            with self.assertRaises(Exception) as raised:
                ingestion.get_job_dataset_diagnostics()
        self.assertEqual(getattr(raised.exception, "status_code", None), 503)

    @patch.object(job_ingestion_routes, "get_job_dataset_diagnostics")
    def test_diagnostics_route_uses_existing_admin_authorization(self, diagnostics):
        diagnostics.return_value = {
            "total_jobs": 0,
            "duplicate_source_keys": 0,
            "sources": [],
        }
        client = TestClient(app)
        app.dependency_overrides[auth.get_current_user] = lambda: {"id": 7}
        self.addCleanup(app.dependency_overrides.pop, auth.get_current_user, None)

        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "7"}):
            response = client.get("/api/admin/jobs/diagnostics")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), diagnostics.return_value)
        diagnostics.assert_called_once_with()


    @patch.object(ingestion.time, "sleep")
    @patch.object(ingestion.requests, "get")
    def test_transient_provider_failure_retries_with_bounded_delay(self, get, sleep):
        class Response:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.headers = {"Retry-After": "20"}
                self.payload = payload

            def json(self):
                return self.payload

        get.side_effect = [
            Response(503, {}),
            Response(200, {"results": []}),
        ]

        self.assertEqual(
            ingestion._request_json("https://provider.example/api", {}),
            {"results": []},
        )
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(20)

    @patch.object(ingestion.time, "sleep")
    @patch.object(ingestion.requests, "get")
    def test_retry_after_beyond_sync_wait_budget_fails_without_early_retry(
        self, get, sleep
    ):
        class RateLimitedResponse:
            status_code = 429
            headers = {"Retry-After": "60"}

        get.return_value = RateLimitedResponse()
        with self.assertRaises(ingestion._ProviderError):
            ingestion._request_json("https://provider.example/api", {})
        get.assert_called_once()
        sleep.assert_not_called()

    @patch.object(ingestion.time, "sleep")
    @patch.object(ingestion.requests, "get")
    def test_timeout_retries_are_bounded_and_return_safe_error(self, get, sleep):
        get.side_effect = ingestion.requests.Timeout()
        with self.assertRaises(ingestion._ProviderError) as raised:
            ingestion._request_json("https://provider.example/api", {})
        self.assertEqual(str(raised.exception), "Upstream request failed")
        self.assertEqual(get.call_count, ingestion.MAX_HTTP_ATTEMPTS)
        self.assertEqual(sleep.call_count, ingestion.MAX_HTTP_ATTEMPTS - 1)

    @patch.object(job_ingestion_routes, "synchronize_configured_sources")
    def test_authorized_sync_route_returns_multi_source_summary(self, sync):
        sync.return_value = {
            "attempted_sources": ["Lever"],
            "successful_sources": ["Lever"],
            "processed": 1,
            "inserted": 1,
            "updated": 0,
            "skipped": 0,
            "failures": [],
            "sources": {"Lever": {"status": "succeeded"}},
        }
        client = TestClient(app)
        app.dependency_overrides[auth.get_current_user] = lambda: {
            "id": 7,
            "email": "admin@example.com",
        }
        self.addCleanup(app.dependency_overrides.pop, auth.get_current_user, None)

        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "7"}), patch.object(
            auth, "get_user_by_id", return_value={"id": 7, "email": "admin@example.com"}
        ):
            response = client.post(
                "/api/admin/jobs/sync",
                headers={"Authorization": f"******"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), sync.return_value)
        sync.assert_called_once_with()

    def test_sync_authorization_fails_closed_and_checks_allowlist(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("JOB_SYNC_ADMIN_USER_IDS", None)
            with self.assertRaises(Exception) as raised:
                ingestion.require_job_sync_admin({"id": 7})
            self.assertEqual(getattr(raised.exception, "status_code", None), 503)

        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "8"}):
            with self.assertRaises(Exception) as raised:
                ingestion.require_job_sync_admin({"id": 7})
            self.assertEqual(getattr(raised.exception, "status_code", None), 403)

    def test_sync_route_requires_auth_and_admin_allowlist(self):
        client = TestClient(app)
        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "7"}):
            unauthenticated = client.post("/api/admin/jobs/sync")
        self.assertEqual(unauthenticated.status_code, 401)

        token = auth.create_access_token(7)
        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "8"}), patch.object(
            auth, "get_user_by_id", return_value={"id": 7, "email": "user@example.com"}
        ):
            forbidden = client.post(
                "/api/admin/jobs/sync",
                headers={"Authorization": "Bearer " + token},
            )
        self.assertEqual(forbidden.status_code, 403)

    @patch.object(job_ingestion_routes, "synchronize_configured_sources")
    def test_authorized_sync_route_returns_summary(self, sync):
        sync.return_value = {
            "attempted_sources": [],
            "successful_sources": [],
            "processed": 1,
            "inserted": 1,
            "updated": 0,
            "skipped": 0,
            "failures": [],
            "sources": {},
        }
        token = auth.create_access_token(7)
        client = TestClient(app)

        with patch.dict(os.environ, {"JOB_SYNC_ADMIN_USER_IDS": "7"}), patch.object(
            auth, "get_user_by_id", return_value={"id": 7, "email": "admin@example.com"}
        ):
            response = client.post(
                "/api/admin/jobs/sync",
                headers={"Authorization": "Bearer " + token},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), sync.return_value)
        sync.assert_called_once_with()



if __name__ == "__main__":
    unittest.main()
