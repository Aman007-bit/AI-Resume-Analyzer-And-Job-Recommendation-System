import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes-long")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

import auth
from main import app
from routers import resume_routes
from services import recommendation_service, resume_service


def make_pdf(text="Python"):
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def make_encrypted_pdf():
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(make_pdf())))
    writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class TrackingBytesIO(BytesIO):
    def __init__(self, contents):
        super().__init__(contents)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class FakeCursor:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.queries = []
        self.lastrowid = 41
        self.rows = [{"id": 7}]
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("simulated database failure")

    def fetchone(self):
        return self.rows.pop(0)

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


class RecommendationFixtureCursor:
    def __init__(self, resume, resume_skills, jobs):
        self.resume = resume
        self.resume_skills = resume_skills
        self.jobs = jobs
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        query = self.queries[-1][0].lower()
        if "select user_id, extracted_text from resumes" in query:
            return self.resume
        if "information_schema.columns" in query:
            return {"column_count": 1}
        return None

    def fetchall(self):
        query = self.queries[-1][0].lower()
        if "from resume_skills" in query:
            return self.resume_skills
        if "from jobs j" in query:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            return [
                row
                for row in self.jobs
                if row["status"] == "open"
                and (row["expires_at"] is None or row["expires_at"] > now)
            ]
        return []

    def close(self):
        self.closed = True


class ResumeProcessingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = {"id": 7, "name": "A User", "email": "a@example.com"}
        self.token = auth.create_access_token(self.user["id"])
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def upload(self, contents, filename="resume.pdf", content_type="application/pdf"):
        return self.client.post(
            "/api/resumes/upload",
            headers=self.headers,
            files={"file": (filename, contents, content_type)},
        )

    @patch.object(resume_routes, "build_job_recommendations")
    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_valid_pdf_is_extracted_and_persisted(
        self, get_user_by_id, get_db_connection, build_recommendations
    ):
        get_user_by_id.return_value = self.user
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        response = self.upload(make_pdf("Python and FastAPI"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user_id"], 7)
        self.assertEqual(response.json()["skills_found"], ["FastAPI", "Python"])
        self.assertTrue(response.json()["recommendations_generated"])
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        resume_insert = next(
            params
            for query, params in cursor.queries
            if "INSERT INTO resumes" in query
        )
        self.assertIn("Python and FastAPI", resume_insert[2])
        build_recommendations.assert_called_once_with(41, 7)

    @patch.object(auth, "get_user_by_id")
    @patch.object(recommendation_service, "get_db_connection")
    @patch.object(resume_service, "get_db_connection")
    def test_pdf_to_persisted_resume_through_real_recommendation_service(
        self,
        get_resume_db_connection,
        get_recommendation_db_connection,
        get_user_by_id,
    ):
        get_user_by_id.return_value = self.user
        resume_cursor = FakeCursor()
        resume_connection = FakeConnection(resume_cursor)
        get_resume_db_connection.return_value = resume_connection

        resume_text = "Python FastAPI data pipelines engineer cloud automation."
        response_data = {}
        resume_params_holder = {}
        skill_names_holder = {}
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        def run_real_recommendation_service(resume_id, user_id):
            resume_params = next(
                params
                for query, params in resume_cursor.queries
                if "INSERT INTO resumes" in query
            )
            skill_names = [
                params[0]
                for query, params in resume_cursor.queries
                if "INSERT INTO skills" in query
            ]
            skill_ids = {name: index + 1 for index, name in enumerate(skill_names)}
            jobs = [
                {
                    "job_id": 901,
                    "title": "FastAPI Skills Role",
                    "company": "Fixture Co",
                    "location": "Remote",
                    "work_mode": "remote",
                    "description": "",
                    "source_url": "https://jobs.lever.co/fixture/901",
                    "source_name": "Lever",
                    "skill_id": skill_ids["FastAPI"],
                    "skill_name": "FastAPI",
                    "status": "open",
                    "expires_at": None,
                },
                {
                    "job_id": 902,
                    "title": "Text Similarity Role",
                    "company": "Fixture Co",
                    "location": "Remote",
                    "work_mode": "remote",
                    "description": "Python FastAPI data pipelines for cloud automation.",
                    "source_url": "https://jobs.lever.co/fixture/902",
                    "source_name": "Lever",
                    "skill_id": None,
                    "skill_name": None,
                    "status": "open",
                    "expires_at": now + timedelta(days=2),
                },
                {
                    "job_id": 903,
                    "title": "Unmatched Role",
                    "company": "Fixture Co",
                    "location": "Remote",
                    "work_mode": "remote",
                    "description": "",
                    "source_url": "https://jobs.lever.co/fixture/903",
                    "source_name": "Lever",
                    "skill_id": skill_ids["Python"],
                    "skill_name": "Java",
                    "status": "open",
                    "expires_at": None,
                },
                {
                    "job_id": 904,
                    "title": "Closed Role",
                    "company": "Fixture Co",
                    "location": "Remote",
                    "work_mode": "remote",
                    "description": "Python FastAPI",
                    "source_url": "https://jobs.lever.co/fixture/904",
                    "source_name": "Lever",
                    "skill_id": skill_ids["Python"],
                    "skill_name": "Python",
                    "status": "closed",
                    "expires_at": None,
                },
            ]
            recommendation_cursor = RecommendationFixtureCursor(
                {"user_id": user_id, "extracted_text": resume_params[2]},
                [
                    {"id": skill_ids[name], "name": name}
                    for name in skill_names
                ],
                jobs,
            )
            recommendation_connection = FakeConnection(recommendation_cursor)
            get_recommendation_db_connection.return_value = recommendation_connection
            rec_result = recommendation_service.build_job_recommendations(
                resume_id, user_id
            )
            response_data.update(
                resume_params=resume_params,
                skill_names=skill_names,
                rec_result=rec_result,
                recommendation_cursor=recommendation_cursor,
                recommendation_connection=recommendation_connection,
            )
            return rec_result

        get_user_by_id.return_value = self.user
        with patch.dict(
            os.environ, {"LEVER_RECOMMENDATIONS_AUTHORIZED": "true"}
        ), patch.object(
            resume_routes,
            "build_job_recommendations",
            side_effect=run_real_recommendation_service,
        ):
            response = self.upload(make_pdf(resume_text))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["recommendations_generated"])
        saved_text = response_data["resume_params"][2]
        self.assertIn("Python FastAPI data pipelines", saved_text)
        self.assertEqual(set(response_data["skill_names"]), {"Python", "FastAPI"})
        self.assertEqual(response.json()["skills_found"], ["FastAPI", "Python"])
        rec_result = response_data["rec_result"]
        self.assertEqual(
            {job["job_id"] for job in rec_result["recommendations"]}, {901, 902}
        )
        skills_recommendation = next(
            job for job in rec_result["recommendations"] if job["job_id"] == 901
        )
        self.assertEqual(skills_recommendation["match_score"], 100.0)
        self.assertEqual(skills_recommendation["matched_skills"], ["FastAPI"])
        self.assertGreater(
            next(job for job in rec_result["recommendations"] if job["job_id"] == 902)[
                "content_similarity_score"
            ],
            0,
        )
        persisted = [
            params
            for query, params in response_data["recommendation_cursor"].queries
            if "INSERT INTO recommendations" in query
        ]
        self.assertEqual(
            persisted,
            [
                (41, job["job_id"], job["match_score"])
                for job in rec_result["recommendations"]
            ],
        )
        self.assertTrue(resume_connection.committed)
        self.assertTrue(response_data["recommendation_connection"].committed)

    @patch.object(
        resume_routes,
        "build_job_recommendations",
        return_value={
            "availability": {
                "status": "provider_authorization_required",
            },
            "total_jobs": 0,
            "recommendations": [],
        },
    )
    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_upload_reports_provider_authorization_block(
        self, get_user_by_id, get_db_connection, build_recommendations
    ):
        get_user_by_id.return_value = self.user
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        response = self.upload(make_pdf("Python and FastAPI"))

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["recommendations_generated"])
        self.assertEqual(
            body["recommendation_status"],
            "provider_authorization_required",
        )
        self.assertIn(
            "provider data-use authorization is pending",
            body["recommendation_error"],
        )
        self.assertTrue(connection.committed)
        build_recommendations.assert_called_once_with(41, 7)

    @patch.object(auth, "get_user_by_id")
    def test_empty_upload_is_rejected(self, get_user_by_id):
        get_user_by_id.return_value = self.user

        response = self.upload(b"")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "The uploaded file is empty.")

    @patch.object(auth, "get_user_by_id")
    def test_non_pdf_content_is_rejected_even_with_pdf_name_and_mime(
        self, get_user_by_id
    ):
        get_user_by_id.return_value = self.user

        response = self.upload(b"not a PDF")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "The uploaded file is not a valid PDF.")

    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_malformed_pdf_returns_safe_error(self, get_user_by_id, get_db_connection):
        get_user_by_id.return_value = self.user
        get_db_connection.assert_not_called()

        response = self.upload(b"%PDF-this is malformed")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Could not read the PDF. Please upload a valid PDF.",
        )
        get_db_connection.assert_not_called()

    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_encrypted_pdf_is_rejected(self, get_user_by_id, get_db_connection):
        get_user_by_id.return_value = self.user

        response = self.upload(make_encrypted_pdf())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Password-protected PDFs are not supported.",
        )
        get_db_connection.assert_not_called()

    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_pdf_without_extractable_text_is_rejected(
        self, get_user_by_id, get_db_connection
    ):
        get_user_by_id.return_value = self.user

        response = self.upload(make_pdf(""))

        self.assertEqual(response.status_code, 422)
        self.assertIn("No readable text", response.json()["detail"])
        get_db_connection.assert_not_called()

    @patch.object(auth, "get_user_by_id")
    def test_size_limit_is_checked_before_reading_upload(self, get_user_by_id):
        get_user_by_id.return_value = self.user

        with patch.object(resume_routes, "MAX_UPLOAD_SIZE_BYTES", 8):
            response = self.upload(b"%PDF-1234")

        self.assertEqual(response.status_code, 413)

    def test_upload_without_known_size_reads_only_limit_plus_one_byte(self):
        from starlette.datastructures import UploadFile

        tracked_file = TrackingBytesIO(b"%PDF-1234")
        upload = UploadFile(filename="resume.pdf", file=tracked_file)

        with patch.object(resume_routes, "MAX_UPLOAD_SIZE_BYTES", 8):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(resume_routes.upload_resume(upload, self.user))

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(tracked_file.read_sizes, [9])
        self.assertTrue(tracked_file.closed)

    def test_upload_file_is_closed_after_success(self):
        from starlette.datastructures import UploadFile

        tracked_file = TrackingBytesIO(make_pdf())
        upload = UploadFile(filename="resume.pdf", file=tracked_file)

        with patch.object(
            resume_routes,
            "process_resume_upload",
            return_value={"resume_id": 41},
        ), patch.object(resume_routes, "build_job_recommendations"):
            result = asyncio.run(resume_routes.upload_resume(upload, self.user))

        self.assertTrue(result["recommendations_generated"])
        self.assertTrue(tracked_file.closed)

    @patch.object(resume_service, "extract_skills", side_effect=RuntimeError("internal"))
    @patch.object(resume_service, "get_db_connection")
    def test_skill_extraction_failure_returns_safe_error_without_database_write(
        self, get_db_connection, extract_skills
    ):
        with self.assertRaises(HTTPException) as raised:
            resume_service.process_resume_upload(7, "resume.pdf", make_pdf())

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.detail, "Failed to extract resume details.")
        get_db_connection.assert_not_called()
        extract_skills.assert_called_once()

    @patch.object(resume_service, "get_db_connection")
    def test_persistence_failure_rolls_back_and_closes_resources(self, get_db_connection):
        cursor = FakeCursor(fail_on="INSERT INTO skills")
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        with self.assertRaises(HTTPException) as raised:
            resume_service.process_resume_upload(7, "resume.pdf", make_pdf())

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            "Failed to save resume and extracted details.",
        )
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    @patch.object(resume_routes, "build_job_recommendations", side_effect=RuntimeError("internal"))
    @patch.object(resume_service, "get_db_connection")
    @patch.object(auth, "get_user_by_id")
    def test_recommendation_failure_keeps_saved_resume_and_reports_partial_success(
        self, get_user_by_id, get_db_connection, build_recommendations
    ):
        get_user_by_id.return_value = self.user
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        get_db_connection.return_value = connection

        response = self.upload(make_pdf())

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["resume_id"], 41)
        self.assertFalse(body["recommendations_generated"])
        self.assertEqual(
            body["recommendation_error"],
            "Could not generate recommendations right now.",
        )
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        build_recommendations.assert_called_once_with(41, 7)

    def test_upload_requires_authentication(self):
        response = self.client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", make_pdf(), "application/pdf")},
        )

        self.assertEqual(response.status_code, 401)

    def test_upload_closes_file_when_validation_fails(self):
        from starlette.datastructures import UploadFile

        upload = UploadFile(filename="resume.pdf", file=BytesIO(b""))

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(resume_routes.upload_resume(upload, self.user))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(upload.file.closed)

    def test_skill_link_failure_rolls_back_resume_insert(self):
        """If resume_skills insert fails mid-loop, upload must roll back."""
        cursor = FakeCursor(fail_on="INSERT IGNORE INTO resume_skills")
        connection = FakeConnection(cursor)

        with patch.object(resume_service, "get_db_connection", return_value=connection):
            with self.assertRaises(HTTPException) as raised:
                resume_service.process_resume_upload(7, "resume.pdf", make_pdf())

        self.assertEqual(raised.exception.status_code, 500)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)



if __name__ == "__main__":
    unittest.main()
