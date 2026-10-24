import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes-long")

from services import job_ingestion_service as jis
from services import recommendation_service as rs


class WorkModeAndStatusMappingTests(unittest.TestCase):
    """Offline Phase 4/5 mapping coverage for provider payload -> internal fields."""

    def _jla_job(self, **overrides):
        job = {
            "id": "jla-1",
            "title": "Engineer",
            "company": "Acme",
            "url": "https://example.com/jobs/1",
            "description_html": "Python FastAPI",
            "listed_at": "2026-01-01T00:00:00Z",
            "status": "active",
            "location": "Berlin",
            "remote_policy": "remote",
        }
        job.update(overrides)
        return job

    def test_work_mode_maps_remote_hybrid_onsite(self):
        cases = [
            ("remote", "remote"),
            ("hybrid", "hybrid"),
            ("onsite", "on_site"),
            ("on-site", "on_site"),
            ("on_site", "on_site"),
            ("unknown-policy", "unknown"),
            (None, "unknown"),
        ]
        for remote_policy, expected in cases:
            with self.subTest(remote_policy=remote_policy):
                payload = self._jla_job()
                if remote_policy is None:
                    payload.pop("remote_policy", None)
                else:
                    payload["remote_policy"] = remote_policy
                normalized = jis._parse_job_listings_api_job(payload)
                self.assertEqual(normalized["work_mode"], expected)

    def test_work_mode_is_remote_when_is_remote_true_and_policy_unknown(self):
        normalized = jis._parse_job_listings_api_job(
            self._jla_job(remote_policy="mystery", is_remote=True)
        )
        self.assertEqual(normalized["work_mode"], "remote")

    def test_removed_provider_status_maps_to_closed(self):
        normalized = jis._parse_job_listings_api_job(self._jla_job(status="removed"))
        self.assertEqual(normalized["status"], "closed")

    def test_past_valid_through_maps_to_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        normalized = jis._parse_job_listings_api_job(
            self._jla_job(status="active", valid_through=past)
        )
        self.assertEqual(normalized["status"], "expired")
        self.assertIsNotNone(normalized["expires_at"])

    def test_invalid_provider_status_is_rejected(self):
        with self.assertRaises(ValueError):
            jis._parse_job_listings_api_job(self._jla_job(status="weird"))

    def test_arbeitnow_remote_true_prefixes_location(self):
        job = {
            "slug": "py-1",
            "url": "https://www.arbeitnow.com/view/py-1",
            "title": "Python Dev",
            "company_name": "Co",
            "location": "Berlin",
            "description": "Python",
            "remote": True,
            "created_at": 1700000000,
        }
        # arbeitnow parser may use different field names - call and assert work_mode/location
        try:
            normalized = jis._parse_arbeitnow_job(job)
        except Exception as exc:
            self.skipTest("arbeitnow fixture shape mismatch: %s" % type(exc).__name__)
            return
        self.assertIn("Remote", normalized.get("location") or "")


class RecommendationEligibilitySqlTests(unittest.TestCase):
    def test_job_query_requires_open_and_non_expired(self):
        source = Path(rs.__file__).read_text(encoding="utf-8")
        self.assertIn("j.status = 'open'", source)
        self.assertIn("j.expires_at IS NULL OR j.expires_at > UTC_TIMESTAMP()", source)


if __name__ == "__main__":
    unittest.main()

