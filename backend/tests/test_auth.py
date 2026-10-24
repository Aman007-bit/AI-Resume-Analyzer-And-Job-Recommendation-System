import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes-long")

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient

import auth
from main import app
from routers import auth_routes, recommendation_routes, resume_routes
from services import auth_service, recommendation_service
from services.provider_policy import provider_use_authorized


class FakeCursor:
    def __init__(self, rows=None, collections=None, work_mode_exists=0):
        self.rows = list(rows or [])
        self.collections = list(collections or [])
        self.work_mode_exists = work_mode_exists
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        if self.queries and "information_schema.columns" in self.queries[-1][0].lower():
            return {"column_count": self.work_mode_exists}
        return self.rows.pop(0)

    def fetchall(self):
        rows = self.collections.pop(0)
        query = self.queries[-1][0].lower() if self.queries else ""
        if "from jobs j" in query and "j.status = 'open'" in query:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            rows = [
                row
                for row in rows
                if row.get("status", "open") == "open"
                and (
                    row.get("expires_at") is None
                    or row["expires_at"] > now
                )
            ]
        return rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_password_hash_is_not_plaintext_and_verifies(self):
        stored_hash = auth_service.hash_password("a-safe-password")

        self.assertNotEqual(stored_hash, "a-safe-password")
        self.assertTrue(auth_service.verify_password("a-safe-password", stored_hash))
        self.assertFalse(auth_service.verify_password("wrong-password", stored_hash))
        self.assertFalse(auth_service.verify_password("any-password", None))

    @patch.object(auth_service, "get_db_connection")
    def test_unknown_account_is_rejected(self, get_db_connection):
        cursor = FakeCursor(rows=[None])
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with self.assertRaises(HTTPException) as raised:
            auth_service.authenticate_user("missing@example.com", "a-safe-password")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Invalid email or password.")
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    @patch.object(auth_routes, "register_user")
    def test_registration_returns_token_and_safe_user(self, register_user):
        register_user.return_value = {
            "id": 7,
            "name": "A User",
            "email": "a@example.com",
        }

        response = self.client.post(
            "/api/auth/register",
            json={
                "name": " A User ",
                "email": "A@example.com",
                "password": "a-safe-password",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["id"], 7)
        self.assertNotIn("password", response.json()["user"])
        self.assertNotIn("password_hash", response.json()["user"])
        self.assertTrue(response.json()["access_token"])
        register_user.assert_called_once_with(
            "A User", "a@example.com", "a-safe-password"
        )

    def test_registration_rejects_invalid_email_and_short_password(self):
        response = self.client.post(
            "/api/auth/register",
            json={"name": "A User", "email": "not-an-email", "password": "short"},
        )

        self.assertEqual(response.status_code, 422)

    def test_registration_rejects_missing_fields(self):
        response = self.client.post(
            "/api/auth/register",
            json={"name": "A User", "email": "a@example.com"},
        )

        self.assertEqual(response.status_code, 422)

    @patch.object(auth_routes, "register_user")
    def test_duplicate_registration_is_conflict(self, register_user):
        register_user.side_effect = HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

        response = self.client.post(
            "/api/auth/register",
            json={
                "name": "A User",
                "email": "a@example.com",
                "password": "a-safe-password",
            },
        )

        self.assertEqual(response.status_code, 409)

    @patch.object(auth_routes, "authenticate_user")
    def test_successful_login_returns_token(self, authenticate_user):
        authenticate_user.return_value = {
            "id": 7,
            "name": "A User",
            "email": "a@example.com",
        }

        response = self.client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "a-safe-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "a@example.com")
        self.assertNotIn("password_hash", response.json()["user"])
        authenticate_user.assert_called_once_with("a@example.com", "a-safe-password")

    @patch.object(auth_routes, "authenticate_user")
    def test_bad_credentials_return_unauthorized(self, authenticate_user):
        authenticate_user.side_effect = HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

        response = self.client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)

    def test_protected_routes_reject_missing_or_invalid_token(self):
        upload_response = self.client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", b"%PDF-fake", "application/pdf")},
        )
        recommendation_response = self.client.get("/api/recommendations/10")
        invalid_token_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid"},
        )

        self.assertEqual(upload_response.status_code, 401)
        self.assertEqual(recommendation_response.status_code, 401)
        self.assertEqual(invalid_token_response.status_code, 401)

    @patch.object(auth, "get_user_by_id")
    def test_valid_token_returns_current_database_user(self, get_user_by_id):
        get_user_by_id.return_value = {
            "id": 7,
            "name": "A User",
            "email": "a@example.com",
        }
        token = auth.create_access_token(7)

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 7)
        self.assertNotIn("password_hash", response.json())
        get_user_by_id.assert_called_once_with(7)

    @patch.object(resume_routes, "build_job_recommendations")
    @patch.object(resume_routes, "process_resume_upload")
    @patch.object(auth, "get_user_by_id")
    def test_upload_uses_identity_from_token(
        self,
        get_user_by_id,
        process_resume_upload,
        build_job_recommendations,
    ):
        get_user_by_id.return_value = {
            "id": 7,
            "name": "A User",
            "email": "a@example.com",
        }
        process_resume_upload.return_value = {"resume_id": 10, "user_id": 7}
        token = auth.create_access_token(7)

        response = self.client.post(
            "/api/resumes/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("resume.pdf", b"%PDF-test", "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], 7)
        self.assertEqual(process_resume_upload.call_args.kwargs["user_id"], 7)
        build_job_recommendations.assert_called_once_with(10, 7)

    @patch.object(recommendation_routes, "build_job_recommendations")
    @patch.object(auth, "get_user_by_id")
    def test_recommendation_route_uses_authenticated_owner(
        self,
        get_user_by_id,
        build_job_recommendations,
    ):
        get_user_by_id.return_value = {
            "id": 7,
            "name": "A User",
            "email": "a@example.com",
        }
        build_job_recommendations.return_value = {
            "resume_id": 10,
            "recommendations": [],
        }
        token = auth.create_access_token(7)

        response = self.client.get(
            "/api/recommendations/10",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        build_job_recommendations.assert_called_once_with(10, 7)

    @patch.object(auth, "get_user_by_id")
    def test_expired_token_is_rejected(self, get_user_by_id):
        expired_token = jwt.encode(
            {
                "sub": "7",
                "iss": auth.TOKEN_ISSUER,
                "iat": datetime.now(timezone.utc) - timedelta(minutes=2),
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            os.environ["JWT_SECRET_KEY"],
            algorithm="HS256",
        )

        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        self.assertEqual(response.status_code, 401)
        get_user_by_id.assert_not_called()


class ResumeOwnershipTests(unittest.TestCase):
    def test_jla_recommendation_authorization_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                provider_use_authorized("Job Listings API", "recommendations")
            )

    def test_jla_recommendation_authorization_obeys_enabled_setting(self):
        with patch.dict(
            os.environ,
            {"JLA_RECOMMENDATIONS_AUTHORIZED": "false"},
            clear=True,
        ):
            self.assertFalse(
                provider_use_authorized("Job Listings API", "recommendations")
            )

        with patch.dict(
            os.environ,
            {"JLA_RECOMMENDATIONS_AUTHORIZED": "true"},
            clear=True,
        ):
            self.assertTrue(
                provider_use_authorized("Job Listings API", "recommendations")
            )

    def test_provider_ingestion_and_recommendation_authorizations_are_independent(
        self,
    ):
        with patch.dict(
            os.environ,
            {
                "LEVER_INGESTION_AUTHORIZED": "true",
                "LEVER_RECOMMENDATIONS_AUTHORIZED": "false",
            },
            clear=True,
        ):
            self.assertTrue(provider_use_authorized("Lever", "ingestion"))
            self.assertFalse(
                provider_use_authorized("Lever", "recommendations")
            )

        with patch.dict(
            os.environ,
            {
                "LEVER_INGESTION_AUTHORIZED": "false",
                "LEVER_RECOMMENDATIONS_AUTHORIZED": "true",
            },
            clear=True,
        ):
            self.assertFalse(provider_use_authorized("Lever", "ingestion"))
            self.assertTrue(
                provider_use_authorized("Lever", "recommendations")
            )

        with patch.dict(
            os.environ,
            {
                "JLA_INGESTION_AUTHORIZED": "true",
                "JLA_RECOMMENDATIONS_AUTHORIZED": "false",
            },
            clear=True,
        ):
            self.assertTrue(
                provider_use_authorized("Job Listings API", "ingestion")
            )
            self.assertFalse(
                provider_use_authorized("Job Listings API", "recommendations")
            )

    def test_unreviewed_providers_and_unknown_policy_operations_fail_closed(
        self,
    ):
        self.assertFalse(
            provider_use_authorized("Unreviewed provider", "ingestion")
        )
        self.assertFalse(
            provider_use_authorized("Unreviewed provider", "recommendations")
        )
        self.assertFalse(provider_use_authorized("USAJOBS", "other"))

    @patch.object(recommendation_service, "get_db_connection")
    def test_other_users_resume_is_hidden(self, get_db_connection):
        cursor = FakeCursor(rows=[{"user_id": 2}])
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with self.assertRaises(HTTPException) as raised:
            recommendation_service.build_job_recommendations(10, 1)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_owner_can_retrieve_recommendations(self, get_db_connection):
        cursor = FakeCursor(
            rows=[{"user_id": 1}],
            collections=[[], []],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}):
            result = recommendation_service.build_job_recommendations(10, 1)

        self.assertEqual(result["resume_id"], 10)
        self.assertEqual(result["recommendations"], [])
        self.assertIn(
            "'unknown' AS work_mode",
            next(query for query, _ in cursor.queries if "FROM jobs j" in query),
        )
        recommendation_query = next(
            query for query, _ in cursor.queries if "FROM jobs j" in query
        )
        self.assertIn("j.status = 'open'", recommendation_query)
        self.assertIn("j.expires_at > UTC_TIMESTAMP()", recommendation_query)
        self.assertEqual(
            result["availability"],
            {
                "status": "no_jobs_available",
                "stored_job_count": 0,
                "provider_eligible_job_count": 0,
                "recommendation_count": 0,
                "jobs_without_skill_data": 0,
                "jobs_without_description_data": 0,
                "excluded_job_count": 0,
                "excluded_sources": [],
                "suppressed_duplicate_count": 0,
            },
        )
        self.assertTrue(connection.committed)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def _recommendation_job_row(self, job_id, status="open", expires_at=None):
        return {
            "job_id": job_id,
            "title": f"Python Engineer {job_id}",
            "company": "Example",
            "location": "Remote",
            "description": "",
            "source_url": f"https://jobs.lever.co/example/{job_id}",
            "source_name": "Lever",
            "skill_id": 101,
            "skill_name": "Python",
            "status": status,
            "expires_at": expires_at,
        }

    def _run_recommendations_with_job_rows(self, get_db_connection, job_rows):
        cursor = FakeCursor(
            rows=[{"user_id": 1, "extracted_text": "Python engineer"}],
            collections=[[{"id": 101, "name": "Python"}], job_rows],
            work_mode_exists=1,
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(
            os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}
        ):
            result = recommendation_service.build_job_recommendations(10, 1)
        return result, cursor, connection

    @patch.object(recommendation_service, "get_db_connection")
    def test_closed_job_is_filtered_and_never_persisted(self, get_db_connection):
        result, cursor, connection = self._run_recommendations_with_job_rows(
            get_db_connection,
            [self._recommendation_job_row(70, status="closed")],
        )

        self.assertEqual(result["recommendations"], [])
        self.assertFalse(
            any("INSERT INTO recommendations" in query for query, _ in cursor.queries)
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_expired_job_is_filtered_and_never_persisted(self, get_db_connection):
        expired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        result, cursor, connection = self._run_recommendations_with_job_rows(
            get_db_connection,
            [self._recommendation_job_row(71, expires_at=expired_at)],
        )

        self.assertEqual(result["recommendations"], [])
        self.assertFalse(
            any("INSERT INTO recommendations" in query for query, _ in cursor.queries)
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_open_nonexpired_job_is_recommended_and_persisted(self, get_db_connection):
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
        with patch.dict(os.environ, {"JLA_RECOMMENDATIONS_AUTHORIZED": "false"}):
            result, cursor, connection = self._run_recommendations_with_job_rows(
                get_db_connection,
                [self._recommendation_job_row(72, expires_at=expires_at)],
            )

        self.assertEqual([job["job_id"] for job in result["recommendations"]], [72])
        self.assertEqual(result["recommendations"][0]["match_score"], 100.0)
        persisted = [
            params
            for query, params in cursor.queries
            if "INSERT INTO recommendations" in query
        ]
        self.assertEqual(persisted, [(10, 72, 100.0)])
        job_query, job_query_params = next(
            (query, params)
            for query, params in cursor.queries
            if "FROM jobs j" in query
        )
        self.assertIn(
            "CASE WHEN j.source_name = %s THEN NULL ELSE j.description END AS description",
            job_query,
        )
        self.assertIn(
            "LEFT JOIN job_skills js ON js.job_id = j.id AND j.source_name <> %s",
            job_query,
        )
        self.assertEqual(
            job_query_params, ("Job Listings API", "Job Listings API")
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_job_with_no_skill_or_text_match_is_not_recommended_or_persisted(
        self, get_db_connection
    ):
        job = self._recommendation_job_row(73)
        job["skill_name"] = "Java"
        result, cursor, connection = self._run_recommendations_with_job_rows(
            get_db_connection, [job]
        )

        self.assertEqual(result["recommendations"], [])
        self.assertFalse(
            any("INSERT INTO recommendations" in query for query, _ in cursor.queries)
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_authorized_jla_query_can_retrieve_description_and_skills(
        self, get_db_connection
    ):
        row = self._recommendation_job_row(75)
        row.update(
            source_name="Job Listings API",
            description="Build reliable Python services.",
        )
        cursor = FakeCursor(
            rows=[{"user_id": 1, "extracted_text": "Python services"}],
            collections=[[{"id": 101, "name": "Python"}], [row]],
            work_mode_exists=1,
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {"JLA_RECOMMENDATIONS_AUTHORIZED": "true"}):
            result = recommendation_service.build_job_recommendations(10, 1)

        job_query, job_query_params = next(
            (query, params)
            for query, params in cursor.queries
            if "FROM jobs j" in query
        )
        self.assertIn("j.description AS description", job_query)
        self.assertNotIn("j.source_name <> %s", job_query)
        self.assertIsNone(job_query_params)
        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(result["recommendations"][0]["job_id"], 75)
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_jla_jobs_are_filtered_before_description_matching_without_authorization(
        self, get_db_connection
    ):
        row = self._recommendation_job_row(74)
        row.update(
            source_name="Job Listings API",
            description="Private description must not reach ranking.",
        )
        cursor = FakeCursor(
            rows=[{"user_id": 1, "extracted_text": "Python engineer"}],
            collections=[[{"id": 101, "name": "Python"}], [row]],
            work_mode_exists=1,
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {}, clear=True):
            with (
                patch.object(
                    recommendation_service,
                    "calculate_tfidf_cosine_scores",
                    wraps=recommendation_service.calculate_tfidf_cosine_scores,
                ) as calculate_scores,
                patch.object(
                    recommendation_service,
                    "normalize_skill_name",
                    wraps=recommendation_service.normalize_skill_name,
                ) as normalize_skill,
            ):
                result = recommendation_service.build_job_recommendations(10, 1)

        calculate_scores.assert_called_once_with("Python engineer", [])
        normalize_skill.assert_called_once_with("Python")
        self.assertEqual(result["recommendations"], [])
        self.assertFalse(
            any("INSERT INTO recommendations" in query for query, _ in cursor.queries)
        )
        job_query, job_query_params = next(
            (query, params)
            for query, params in cursor.queries
            if "FROM jobs j" in query
        )
        self.assertIn(
            "CASE WHEN j.source_name = %s THEN NULL ELSE j.description END AS description",
            job_query,
        )
        self.assertIn(
            "LEFT JOIN job_skills js ON js.job_id = j.id AND j.source_name <> %s",
            job_query,
        )
        self.assertEqual(
            job_query_params, ("Job Listings API", "Job Listings API")
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_recommendations_match_skills_and_sort_by_coverage(
        self, get_db_connection
    ):
        job_rows = [
            {
                "job_id": 10,
                "title": "Partial match",
                "company": "Example",
                "location": None,
                "description": "",
                "source_url": "https://jobs.lever.co/example/partial",
                "source_name": "Lever",
                "skill_id": 1,
                "skill_name": "Python",
            },
            {
                "job_id": 10,
                "title": "Partial match",
                "company": "Example",
                "location": None,
                "description": "",
                "source_url": "https://jobs.lever.co/example/partial",
                "source_name": "Lever",
                "skill_id": 2,
                "skill_name": "FastAPI",
            },
            {
                "job_id": 20,
                "title": "Full match",
                "company": "Example",
                "location": None,
                "description": "",
                "source_url": "https://jobs.lever.co/example/full",
                "source_name": "Lever",
                "skill_id": 3,
                "skill_name": "SQL",
            },
            {
                "job_id": 30,
                "title": "No requirements",
                "company": "Example",
                "location": None,
                "description": "",
                "source_url": "https://jobs.lever.co/example/none",
                "source_name": "Lever",
                "skill_id": None,
                "skill_name": None,
            },
        ]
        cursor = FakeCursor(
            rows=[{"user_id": 1}],
            collections=[
                [
                    {"id": 101, "name": "Python"},
                    {"id": 102, "name": "SQL"},
                ],
                job_rows,
            ],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}):
            result = recommendation_service.build_job_recommendations(10, 1)

        recommendations = result["recommendations"]
        self.assertEqual(
            result["availability"],
            {
                "status": "available",
                "stored_job_count": 3,
                "provider_eligible_job_count": 3,
                "recommendation_count": 2,
                "jobs_without_skill_data": 1,
                "jobs_without_description_data": 3,
                "excluded_job_count": 0,
                "excluded_sources": [],
                "suppressed_duplicate_count": 0,
            },
        )
        self.assertEqual(
            [(job["job_id"], job["match_score"]) for job in recommendations],
            [(20, 100.0), (10, 50.0)],
        )
        partial_match = recommendations[1]
        self.assertEqual(partial_match["matched_skills"], ["Python"])
        self.assertEqual(partial_match["missing_skills"], ["FastAPI"])
        self.assertTrue(connection.committed)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_description_similarity_ranks_text_only_jobs(self, get_db_connection):
        rows = [
            {
                "job_id": 5,
                "title": "Python API Engineer",
                "company": "Example",
                "location": "Remote",
                "description": "Build Python APIs using FastAPI and SQL.",
                "source_url": "https://jobs.example.com/python",
                "source_name": "Lever",
                "skill_id": None,
                "skill_name": None,
            },
            {
                "job_id": 6,
                "title": "Retail Associate",
                "company": "Example",
                "location": "Pune",
                "description": "Help customers and manage store inventory.",
                "source_url": "https://jobs.example.com/retail",
                "source_name": "Lever",
                "skill_id": None,
                "skill_name": None,
            },
        ]
        cursor = FakeCursor(
            rows=[{
                "user_id": 1,
                "extracted_text": "Python developer building APIs with FastAPI and SQL databases.",
            }],
            collections=[[], rows],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}):
            result = recommendation_service.build_job_recommendations(10, 1)

        recommendations = result["recommendations"]
        self.assertEqual([item["job_id"] for item in recommendations], [5])
        self.assertGreater(recommendations[0]["content_similarity_score"], 0)
        self.assertEqual(recommendations[0]["source_name"], "Lever")
        self.assertEqual(
            recommendations[0]["source_url"], "https://jobs.example.com/python"
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_recommendations_exclude_providers_without_reuse_authorization(
        self, get_db_connection
    ):
        rows = [{
            "job_id": 10,
            "title": "Engineer",
            "company": "Example",
            "location": None,
            "description": "Use Python.",
            "source_url": "https://jobs.lever.co/example/10",
            "source_name": "Lever",
            "skill_id": 1,
            "skill_name": "Python",
        }]
        cursor = FakeCursor(
            rows=[{"user_id": 1}],
            collections=[[{"id": 101, "name": "Python"}], rows],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                recommendation_service,
                "calculate_tfidf_cosine_scores",
                wraps=recommendation_service.calculate_tfidf_cosine_scores,
            ) as calculate_scores:
                result = recommendation_service.build_job_recommendations(10, 1)

        calculate_scores.assert_called_once_with(None, [])

        self.assertEqual(result["total_jobs"], 0)
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(
            result["availability"],
            {
                "status": "provider_authorization_required",
                "stored_job_count": 1,
                "provider_eligible_job_count": 0,
                "recommendation_count": 0,
                "jobs_without_skill_data": 0,
                "jobs_without_description_data": 0,
                "excluded_job_count": 1,
                "excluded_sources": ["Lever"],
                "suppressed_duplicate_count": 0,
            },
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_authorized_provider_with_no_job_skills_returns_data_unavailable(
        self, get_db_connection
    ):
        job_rows = [{
            "job_id": 41,
            "title": "Engineer",
            "company": "Example",
            "location": None,
            "description": "",
            "source_url": "https://jobs.lever.co/example/41",
            "source_name": "Lever",
            "skill_id": None,
            "skill_name": None,
        }]
        cursor = FakeCursor(
            rows=[{"user_id": 1}],
            collections=[[{"id": 101, "name": "Python"}], job_rows],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}):
            result = recommendation_service.build_job_recommendations(10, 1)

        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["availability"]["status"], "job_skill_data_unavailable")
        self.assertEqual(result["availability"]["jobs_without_skill_data"], 1)
        self.assertFalse(any("INSERT INTO recommendations" in query for query, _ in cursor.queries))

    @patch.object(recommendation_service, "get_db_connection")
    def test_unknown_provider_fails_closed(self, get_db_connection):
        rows = [{
            "job_id": 10,
            "title": "Engineer",
            "company": "Example",
            "location": None,
            "description": "Use Python.",
            "source_url": "https://jobs.example.com/10",
            "source_name": "Unreviewed provider",
            "skill_id": 1,
            "skill_name": "Python",
        }]
        cursor = FakeCursor(
            rows=[{"user_id": 1}],
            collections=[[{"id": 101, "name": "Python"}], rows],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(os.environ, {}, clear=True):
            result = recommendation_service.build_job_recommendations(10, 1)

        self.assertEqual(result["recommendations"], [])
        self.assertEqual(
            result["availability"]["status"],
            "provider_authorization_required",
        )
        self.assertEqual(
            result["availability"]["excluded_sources"],
            ["Unreviewed provider"],
        )
        self.assertTrue(connection.committed)

    @patch.object(recommendation_service, "get_db_connection")
    def test_recommendations_suppress_cross_provider_duplicates(
        self, get_db_connection
    ):
        duplicate_description = (
            "Build regional sales strategy for France. Lead pipeline reviews, "
            "coach account executives, and deliver quarterly revenue goals."
        )
        rows = []
        for job_id, source_name, source_url, description, skill_id, skill_name in (
            (
                10,
                "Greenhouse",
                "https://jobs.example.com/role/10",
                duplicate_description,
                1,
                "Salesforce",
            ),
            (
                20,
                "Arbeitnow",
                "https://jobs.example.org/role/20",
                duplicate_description.replace("revenue goals", "revenue targets"),
                2,
                "Salesforce",
            ),
            (
                30,
                "Greenhouse",
                "https://jobs.example.com/role/30",
                "Lead a distinct customer support team.",
                3,
                "Communication",
            ),
        ):
            rows.append(
                {
                    "job_id": job_id,
                    "title": (
                        "Regional Sales Director – France"
                        if job_id < 30
                        else "Customer Support Lead"
                    ),
                    "company": "GitLab",
                    "location": "Remote" if job_id == 10 else "Remote, France",
                    "description": description,
                    "source_url": source_url,
                    "source_name": source_name,
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                }
            )

        cursor = FakeCursor(
            rows=[{
                "user_id": 1,
                "extracted_text": (
                    "Regional sales strategy and customer support team leadership."
                ),
            }],
            collections=[
                [{"id": 101, "name": "Salesforce"}],
                rows,
            ],
        )
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with patch.dict(
            os.environ,
            {
                "GREENHOUSE_RECOMMENDATIONS_AUTHORIZED": "true",
                "ARBEITNOW_RECOMMENDATIONS_AUTHORIZED": "true",
            },
        ):
            result = recommendation_service.build_job_recommendations(10, 1)
        recommendations = result["recommendations"]

        self.assertEqual(result["total_jobs"], 2)
        self.assertEqual([job["job_id"] for job in recommendations], [10, 30])
        self.assertEqual(recommendations[0]["source_name"], "Greenhouse")
        self.assertEqual(
            recommendations[0]["source_url"],
            "https://jobs.example.com/role/10",
        )
        self.assertEqual(
            set(recommendations[0]),
            {
                "job_id",
                "title",
                "company",
                "location",
                "work_mode",
                "description",
                "source_url",
                "source_name",
                "required_skills",
                "matched_skills",
                "missing_skills",
                "match_score",
                "content_similarity_score",
            },
        )
        self.assertTrue(connection.committed)




class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        from main import app

        self.client = TestClient(app)

    def test_liveness_health_returns_healthy(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_root_health_message(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

    @patch("main.get_db_connection", return_value=None)
    def test_database_health_reports_disconnected_without_secrets(self, _mock_db):
        response = self.client.get("/health/database")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "unhealthy")
        self.assertEqual(payload["database"], "disconnected")
        blob = str(payload).lower()
        for forbidden in ("password", "jwt", "secret", "traceback", "mysql.connector"):
            self.assertNotIn(forbidden, blob)

    @patch("main.get_db_connection")
    def test_database_health_reports_connected_database_name_only(self, mock_db):
        cursor = MagicMock()
        cursor.fetchone.return_value = ("resume_analyzer_staging_audit",)
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mock_db.return_value = connection

        response = self.client.get("/health/database")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["database"], "connected")
        self.assertEqual(payload["database_name"], "resume_analyzer_staging_audit")
        connection.close.assert_called()

    @patch("main.get_db_connection")
    def test_database_health_query_failure_does_not_leak_exception_text(self, mock_db):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("DSN=user:password@host/db secrets")
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mock_db.return_value = connection

        response = self.client.get("/health/database")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "unhealthy")
        self.assertEqual(payload["database"], "query_failed")
        blob = str(payload).lower()
        self.assertNotIn("password", blob)
        self.assertNotIn("dsn=", blob)
        self.assertNotIn("secrets", blob)


class ProtectedRouteAuthGapTests(unittest.TestCase):
    def setUp(self):
        from main import app

        self.client = TestClient(app)

    def test_recommendations_without_token_are_rejected(self):
        response = self.client.get("/api/recommendations/1")
        self.assertEqual(response.status_code, 401)

    def test_recommendations_with_invalid_bearer_are_rejected(self):
        response = self.client.get(
            "/api/recommendations/1",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_me_with_invalid_bearer_is_rejected(self):
        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer totally-invalid"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
