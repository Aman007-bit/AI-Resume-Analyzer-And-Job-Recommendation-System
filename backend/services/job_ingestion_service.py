import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException

from db import get_db_connection
from services.provider_policy import provider_use_authorized
from services.resume_service import extract_skills

def _load_checkpoint():
    checkpoint_path = "jla_checkpoint.json"
    if not os.path.exists(checkpoint_path):
        return {"windows": {}, "last_successful": None, "seen_ids": []}
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"windows": {}, "last_successful": None, "seen_ids": []}

def _save_checkpoint(checkpoint):
    with open("jla_checkpoint.json", "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2)

logger = logging.getLogger(__name__)
REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_SOURCE_NAME = "Remotive"
REQUEST_TIMEOUT = (5, 20)
THE_MUSE_API_URL = "https://www.themuse.com/api/public/jobs"
USAJOBS_API_URL = "https://data.usajobs.gov/api/search"
LEVER_API_URL = "https://api.lever.co/v0/postings"
LEVER_EU_API_URL = "https://api.eu.lever.co/v0/postings"
ARBEITNOW_API_URL = "https://www.arbeitnow.com/api/job-board-api"
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards"
JOB_LISTINGS_API_URL = "https://api.joblistingsapi.com/v1/jobs"
ARBEITNOW_JOB_URL_HOSTS = {
    "arbeitnow.com",
    "www.arbeitnow.com",
    "arbeitnow.co.uk",
    "www.arbeitnow.co.uk",
    "arbeitnow.fr",
    "www.arbeitnow.fr",
    "arbeitnow.ch",
    "www.arbeitnow.ch",
    "arbeitnow.nl",
    "www.arbeitnow.nl",
}
MAX_HTTP_ATTEMPTS = 3
MAX_RETRY_AFTER_SECONDS = 30
MAX_CONFIGURED_LEVER_SITES = 5
MAX_CONFIGURED_GREENHOUSE_BOARDS = 5
MAX_THE_MUSE_PAGES = 5
MAX_USAJOBS_PAGES = 2
USAJOBS_PAGE_SIZE = 100
MAX_LEVER_PAGES = 10
MAX_ARBEITNOW_PAGES = 3
ARBEITNOW_PAGE_SIZE = 300
MAX_GREENHOUSE_JOBS_PER_BOARD = 1000
JOB_LISTINGS_API_PAGE_SIZE = 100
MAX_JOB_LISTINGS_API_REQUESTS_PER_SYNC = 10
PAGE_SIZE = 100
THE_MUSE_SOURCE_NAME = "The Muse"
USAJOBS_SOURCE_NAME = "USAJOBS"
ARBEITNOW_SOURCE_NAME = "Arbeitnow"
GREENHOUSE_SOURCE_NAME = "Greenhouse"
JOB_LISTINGS_API_SOURCE_NAME = "Job Listings API"
_SYNC_RUN_LOCK = threading.Lock()
class _DescriptionTextParser(HTMLParser):
    _BLOCK_TAGS = {"br", "div", "li", "ol", "p", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")


def _description_text(value):
    if not isinstance(value, str):
        raise ValueError("Invalid description")
    parser = _DescriptionTextParser()
    parser.feed(unescape(value))
    parser.close()
    lines = ("".join(parser.parts)).splitlines()
    return "\n".join(" ".join(line.split()) for line in lines if line.strip())


def _parse_job(job):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")

    source_id = job.get("id")
    if isinstance(source_id, bool) or not isinstance(source_id, (str, int)):
        raise ValueError("Missing source job ID")
    source_id = str(source_id).strip()
    if not source_id or len(source_id) > 255:
        raise ValueError("Invalid source job ID")

    url = job.get("url")
    if (
        not isinstance(url, str)
        or len(url) > 500
        or not url.startswith("https://remotive.com/")
    ):
        raise ValueError("Invalid source URL")

    title = job.get("title")
    company = job.get("company_name")
    location = job.get("candidate_required_location")
    description = job.get("description", "")
    tags = job.get("tags", [])
    publication_date = job.get("publication_date")

    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("Invalid job title")
    if not isinstance(company, str) or not company.strip() or len(company) > 200:
        raise ValueError("Invalid company name")
    if location is not None and (
        not isinstance(location, str) or len(location) > 150
    ):
        raise ValueError("Invalid job location")
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 100
        for tag in tags
    ):
        raise ValueError("Invalid job tags")

    posted_at = None
    if publication_date is not None:
        if not isinstance(publication_date, str):
            raise ValueError("Invalid publication date")
        posted_at = datetime.fromisoformat(publication_date)
        if posted_at.tzinfo is not None:
            posted_at = posted_at.astimezone(timezone.utc).replace(tzinfo=None)

    skills = list(dict.fromkeys(tag.strip() for tag in tags))
    return {
        "source_job_id": source_id,
        "source_url": url,
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip() if location else None,
        "work_mode": "remote",
        "description": _description_text(description),
        "requirements": "\n".join(skills) or None,
        "skills": skills,
        "posted_at": posted_at,
    }


def _load_remotive_jobs():
    try:
        response = requests.get(REMOTIVE_API_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        logger.warning("Remotive request failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail="The job provider is temporarily unavailable.",
        ) from error
    except ValueError as error:
        logger.warning("Remotive returned invalid JSON")
        raise HTTPException(
            status_code=502,
            detail="The job provider returned an invalid response.",
        ) from error

    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise HTTPException(
            status_code=502,
            detail="The job provider returned an invalid response.",
        )
    return payload["jobs"]


def _find_or_create_skill(cursor, skill_name):
    cursor.execute("SELECT id FROM skills WHERE name = %s", (skill_name,))
    skill = cursor.fetchone()
    if skill is not None:
        return skill["id"] if isinstance(skill, dict) else skill[0]

    cursor.execute("INSERT INTO skills (name) VALUES (%s)", (skill_name,))
    return cursor.lastrowid


def _sync_job(cursor, job, source_name=REMOTIVE_SOURCE_NAME):
    # Re-validate identity at the persistence boundary so callers cannot insert
    # blank/null provider keys (which would defeat lookup and uniqueness).
    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("Missing source name")
    if len(source_name.strip()) > 100:
        raise ValueError("Invalid source name")
    source_name = source_name.strip()
    source_job_id = _source_id(job.get("source_job_id"))

    cursor.execute(
        """
        SELECT id FROM jobs
        WHERE source_name = %s AND source_job_id = %s
        """,
        (source_name, source_job_id),
    )
    existing = cursor.fetchone()
    values = (
        job["title"],
        job["company"],
        job["location"],
        job.get("work_mode", "unknown"),
        job["description"],
        job["requirements"],
        job["source_url"],
        job["posted_at"],
    )
    status = job.get("status", "open")
    if status not in {"open", "closed", "expired"}:
        raise ValueError("Invalid job status")
    expires_at = job.get("expires_at")

    if existing is None:
        cursor.execute(
            """
            INSERT INTO jobs (
                title, company, location, work_mode, description, requirements,
                source_url, posted_at, source_name, source_job_id, status, expires_at,
                last_seen_at, last_synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            values + (source_name, source_job_id, status, expires_at),
        )
        job_id = cursor.lastrowid
        outcome = "inserted"
    else:
        job_id = existing["id"] if isinstance(existing, dict) else existing[0]
        cursor.execute(
            """
            UPDATE jobs
            SET title = %s, company = %s,
                location = COALESCE(NULLIF(%s, ''), location),
                work_mode = CASE WHEN %s = 'unknown' THEN work_mode ELSE %s END,
                description = COALESCE(NULLIF(%s, ''), description),
                requirements = COALESCE(NULLIF(%s, ''), requirements),
                source_url = %s, posted_at = COALESCE(%s, posted_at),
                status = %s, expires_at = %s,
                last_seen_at = NOW(), last_synced_at = NOW()
            WHERE id = %s
            """,
            values[:3] + (values[3], values[3]) + values[4:] + (status, expires_at, job_id),
        )
        outcome = "updated"

    if job["skills"] is not None:
        if not job["skills"]:
            cursor.execute("UPDATE jobs SET requirements = NULL WHERE id = %s", (job_id,))
        cursor.execute("DELETE FROM job_skills WHERE job_id = %s", (job_id,))
        for skill_name in job["skills"]:
            skill_id = _find_or_create_skill(cursor, skill_name)
            cursor.execute(
                "INSERT IGNORE INTO job_skills (job_id, skill_id) VALUES (%s, %s)",
                (job_id, skill_id),
            )
    return outcome


def synchronize_remotive_jobs():
    _require_staging_job_target()
    provider_jobs = _load_remotive_jobs()
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    summary = {
        "processed": len(provider_jobs),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        for provider_job in provider_jobs:
            source_id = (
                str(provider_job.get("id"))
                if isinstance(provider_job, dict)
                and isinstance(provider_job.get("id"), (str, int))
                and not isinstance(provider_job.get("id"), bool)
                else None
            )
            try:
                job = _parse_job(provider_job)
            except (TypeError, ValueError, OverflowError):
                summary["skipped"] += 1
                summary["errors"].append(
                    {"source_job_id": source_id, "error": "Invalid job record"}
                )
                continue

            try:
                outcome = _sync_job(cursor, job)
                connection.commit()
                summary[outcome] += 1
            except Exception as error:
                connection.rollback()
                logger.error("Remotive job sync failed (%s)", type(error).__name__)
                summary["errors"].append(
                    {
                        "source_job_id": job["source_job_id"],
                        "error": "Database write failed",
                    }
                )
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()

    return summary


class _ProviderError(Exception):
    pass



def _request_json(
    url,
    params,
    headers=None,
    include_headers=False,
    stop_on_rate_limit=False,
    max_attempts=None,
):
    attempts_allowed = (
        MAX_HTTP_ATTEMPTS if max_attempts is None else max_attempts
    )

    if (
        isinstance(attempts_allowed, bool)
        or not isinstance(attempts_allowed, int)
        or attempts_allowed < 1
    ):
        raise ValueError("Invalid request retry limit")

    for attempt in range(attempts_allowed):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt + 1 >= attempts_allowed:
                raise _ProviderError("Upstream request failed") from error

            time.sleep(0.25 * (attempt + 1))
            continue
        except requests.RequestException as error:
            raise _ProviderError("Upstream request failed") from error

        if response.status_code == 429 or response.status_code >= 500:
            if response.status_code == 429 and stop_on_rate_limit:
                raise _ProviderError("Provider rate limit exhausted")

            if attempt + 1 >= attempts_allowed:
                raise _ProviderError("Upstream request failed")

            retry_after = response.headers.get("Retry-After", "").strip()

            if retry_after:
                if not retry_after.isdigit():
                    raise _ProviderError("Invalid provider retry window")

                delay = int(retry_after)

                if delay > MAX_RETRY_AFTER_SECONDS:
                    raise _ProviderError("Provider retry window is too long")
            else:
                delay = 0.25 * (attempt + 1)

            time.sleep(delay)
            continue

        if response.status_code >= 400:
            raise _ProviderError(
                "Provider request failed with HTTP {}".format(
                    response.status_code
                )
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise _ProviderError("Provider returned invalid JSON") from error

        return (
            (payload, response.headers)
            if include_headers
            else payload
        )

    raise _ProviderError("Upstream request failed")



def _source_url(value, allowed_hosts):
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Invalid source URL")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or host not in allowed_hosts
    ):
        raise ValueError("Invalid source URL")
    return value


def _https_source_url(value):
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Invalid source URL")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
    except ValueError as error:
        raise ValueError("Invalid source URL") from error
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Invalid source URL")
    return value


def _source_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Missing source job ID")
    normalized = str(value).strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("Invalid source job ID")
    return normalized


def _optional_text(value, max_length, field_name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid " + field_name)
    text = value.strip()
    if len(text) > max_length:
        raise ValueError("Invalid " + field_name)
    return text or None


def _optional_date(value):
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError
    except (OverflowError, OSError, TypeError, ValueError) as error:
        raise ValueError("Invalid publication date") from error
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _normalized_source_job(
    source_id, url, title, company, location, description, posted_at,
    work_mode="unknown", extract_skill_terms=True,
):
    source_id = _source_id(source_id)
    title = _optional_text(title, 200, "job title")
    company = _optional_text(company, 200, "company name")
    location = _optional_text(location, 150, "job location")
    if not title or not company:
        raise ValueError("Missing job title or company name")
    if work_mode not in {"remote", "on_site", "hybrid", "unknown"}:
        raise ValueError("Invalid workplace type")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError("Invalid description")
    description_text = _description_text(description)
    description_text = _optional_text(description_text, 60000, "description")
    if description_text and len(description_text.encode("utf-8")) > 60000:
        raise ValueError("Invalid description")
    skills = (
        list(dict.fromkeys(extract_skills(description_text or "")))
        if extract_skill_terms
        else []
    )
    return {
        "source_job_id": source_id,
        "source_url": url,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "description": description_text,
        "requirements": "\n".join(skills) or None,
        # Only nonblank supplied text is authoritative. None preserves stored skills.
        "skills": skills if extract_skill_terms and description_text else None,
        "posted_at": _optional_date(posted_at),
    }


def _parse_the_muse_job(job):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    company = job.get("company")
    refs = job.get("refs")
    locations = job.get("locations", [])
    if not isinstance(company, dict) or not isinstance(refs, dict):
        raise ValueError("Invalid job record")
    if not isinstance(locations, list):
        raise ValueError("Invalid job locations")
    location_names = []
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("name"), str):
            raise ValueError("Invalid job locations")
        if location["name"].strip():
            location_names.append(location["name"].strip())

    description = job.get("contents")
    if description is None:
        description = ""
    return _normalized_source_job(
        job.get("id"),
        _source_url(refs.get("landing_page"), {"themuse.com", "www.themuse.com"}),
        job.get("name"),
        company.get("name"),
        ", ".join(dict.fromkeys(location_names)) or None,
        description,
        job.get("publication_date"),
    )


def _parse_usajobs_job(job):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    descriptor = job.get("MatchedObjectDescriptor")
    if not isinstance(descriptor, dict):
        raise ValueError("Invalid job record")
    user_area = descriptor.get("UserArea") or {}
    details = user_area.get("Details") if isinstance(user_area, dict) else None
    if not isinstance(details, dict):
        details = {}
    description_parts = []
    for field in ("JobSummary", "MajorDuties", "Qualifications", "Requirements"):
        value = details.get(field)
        if isinstance(value, str) and value.strip():
            description_parts.append(value)
        elif isinstance(value, list):
            description_parts.extend(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
    source_id = job.get("MatchedObjectId") or descriptor.get("PositionID")
    return _normalized_source_job(
        source_id,
        _source_url(
            descriptor.get("PositionURI"),
            {"usajobs.gov", "www.usajobs.gov"},
        ),
        descriptor.get("PositionTitle"),
        descriptor.get("OrganizationName"),
        descriptor.get("PositionLocationDisplay"),
        "\n\n".join(description_parts),
        descriptor.get("PublicationStartDate"),
    )


def _parse_job_listings_api_job(job):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    provider_status = job.get("status", "active")
    if provider_status not in {"active", "removed"}:
        raise ValueError("Invalid job status")
    valid_through = job.get("valid_through")
    expires_at = None
    if valid_through is not None:
        if not isinstance(valid_through, str):
            raise ValueError("Invalid expiry date")
        expires_at = datetime.fromisoformat(valid_through.replace("Z", "+00:00"))
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    location_data = job.get("location")
    if location_data is None:
        location = None
    elif isinstance(location_data, str):
        location = location_data
    elif isinstance(location_data, dict):
        location = location_data.get("raw") or ", ".join(
            part.strip()
            for part in (
                location_data.get("city"),
                location_data.get("region"),
                location_data.get("country_code"),
            )
            if isinstance(part, str) and part.strip()
        )
    else:
        raise ValueError("Invalid job location")

    remote_policy = job.get("remote_policy")
    if remote_policy is not None and not isinstance(remote_policy, str):
        raise ValueError("Invalid workplace type")
    workplace = (remote_policy or "").strip().lower().replace("_", "-")
    work_mode = {
        "remote": "remote",
        "hybrid": "hybrid",
        "onsite": "on_site",
        "on-site": "on_site",
    }.get(workplace, "unknown")
    if work_mode == "unknown" and job.get("is_remote") is True:
        work_mode = "remote"

    description = job.get("description_html")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError("Invalid description")

    normalized = _normalized_source_job(
        job.get("id"),
        _https_source_url(job.get("url")),
        job.get("title"),
        job.get("company"),
        location,
        description,
        job.get("listed_at"),
        work_mode,
        extract_skill_terms=provider_use_authorized(
            JOB_LISTINGS_API_SOURCE_NAME, "recommendations"
        ),
    )
    normalized["status"] = "closed" if provider_status == "removed" else "open"
    normalized["expires_at"] = expires_at
    if expires_at is not None and expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        normalized["status"] = "expired"
    return normalized


def _parse_arbeitnow_job(job):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    remote = job.get("remote", False)
    if not isinstance(remote, bool):
        raise ValueError("Invalid remote-work indicator")
    location = _optional_text(job.get("location"), 150, "job location")
    if remote:
        location = "Remote" if not location else "Remote - " + location
    created_at = job.get("created_at")
    posted_at = None
    if created_at is not None:
        if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
            raise ValueError("Invalid publication date")
        posted_at = created_at * 1000
    return _normalized_source_job(
        job.get("slug"),
        _source_url(job.get("url"), ARBEITNOW_JOB_URL_HOSTS),
        job.get("title"),
        job.get("company_name"),
        location,
        job.get("description", ""),
        posted_at,
        "remote" if remote else "unknown",
    )


def _parse_greenhouse_job(
    job, board, configured_company, configured_url_hosts=None
):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    location = job.get("location")
    if location is not None:
        if not isinstance(location, dict):
            raise ValueError("Invalid job location")
        location = location.get("name")
    company = job.get("company_name") or configured_company
    allowed_url_hosts = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
    if configured_url_hosts is not None:
        allowed_url_hosts.update(configured_url_hosts)
    return _normalized_source_job(
        "{}:{}".format(board, job.get("id")),
        _source_url(
            job.get("absolute_url"),
            allowed_url_hosts,
        ),
        job.get("title"),
        company,
        location,
        job.get("content", ""),
        job.get("first_published") or job.get("updated_at"),
        "unknown",
    )


def _lever_description(job):
    description = job.get("descriptionPlain")
    if description is None:
        for field in ("descriptionBodyPlain", "openingPlain", "description"):
            if job.get(field) is not None:
                description = job[field]
                break
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError("Invalid description")

    sections = [description]
    lists = job.get("lists", [])
    if lists is None:
        lists = []
    if not isinstance(lists, list):
        raise ValueError("Invalid job description sections")
    for section in lists:
        if not isinstance(section, dict):
            raise ValueError("Invalid job description section")
        heading = section.get("text", "")
        content = section.get("content", "")
        if not isinstance(heading, str) or not isinstance(content, str):
            raise ValueError("Invalid job description section")
        heading = heading.strip()
        content = _description_text(content)
        if heading or content:
            sections.append("\n".join(part for part in (heading, content) if part))

    additional = job.get("additionalPlain")
    if additional is None:
        additional = job.get("additional", "")
    if not isinstance(additional, str):
        raise ValueError("Invalid additional job description")
    if additional.strip():
        sections.append(additional)
    return "\n\n".join(section for section in sections if section.strip())


def _parse_lever_job(job, site, company_name):
    if not isinstance(job, dict):
        raise ValueError("Invalid job record")
    categories = job.get("categories") or {}
    if not isinstance(categories, dict):
        raise ValueError("Invalid job categories")
    commitment = _optional_text(categories.get("commitment"), 100, "employment type")
    locations = categories.get("allLocations")
    if isinstance(locations, list):
        if any(not isinstance(item, str) for item in locations):
            raise ValueError("Invalid job locations")
        location = ", ".join(
            item.strip() for item in locations if item.strip()
        )
    else:
        location = categories.get("location")
    workplace_type = job.get("workplaceType")
    if workplace_type == "onsite":
        workplace_type = "on-site"
    if workplace_type is not None and workplace_type not in {
        "unspecified",
        "on-site",
        "remote",
        "hybrid",
    }:
        raise ValueError("Invalid workplace type")
    if workplace_type in {"on-site", "remote", "hybrid"}:
        workplace_label = workplace_type.replace("-", " ").title()
        if not location:
            location = workplace_label
        elif workplace_label.lower() not in location.lower():
            location = "{} - {}".format(workplace_label, location)

    description = _lever_description(job)
    provider_id = _source_id(job.get("id"))
    normalized = _normalized_source_job(
        "{}:{}".format(site, provider_id),
        _source_url(
            job.get("hostedUrl"),
            {"jobs.lever.co", "jobs.eu.lever.co"},
        ),
        job.get("text"),
        company_name,
        location,
        description,
        None,
        {"on-site": "on_site", "remote": "remote", "hybrid": "hybrid"}.get(
            workplace_type, "unknown"
        ),
    )
    if commitment:
        description_with_commitment = "Employment type: {}\n\n{}".format(
            commitment,
            normalized["description"] or "",
        ).rstrip()
        if len(description_with_commitment.encode("utf-8")) > 60000:
            raise ValueError("Invalid description")
        normalized["description"] = description_with_commitment
    return normalized


def _load_the_muse_jobs(api_key):
    jobs = []
    for page in range(1, MAX_THE_MUSE_PAGES + 1):
        payload = _request_json(
            THE_MUSE_API_URL,
            {"api_key": api_key, "page": page},
        )
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("results"), list)
        ):
            raise _ProviderError("Provider returned an invalid response")
        page_jobs = payload["results"]
        jobs.extend(page_jobs)
        if len(page_jobs) < 20:
            break
    return jobs


def _load_usajobs_jobs(api_key, user_agent_email):
    jobs = []
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": user_agent_email,
        "Authorization-Key": api_key,
    }
    for page in range(1, MAX_USAJOBS_PAGES + 1):
        payload = _request_json(
            USAJOBS_API_URL,
            {"Page": page, "ResultsPerPage": USAJOBS_PAGE_SIZE},
            headers=headers,
        )
        search_result = (
            payload.get("SearchResult") if isinstance(payload, dict) else None
        )
        if (
            not isinstance(search_result, dict)
            or not isinstance(search_result.get("SearchResultItems"), list)
        ):
            raise _ProviderError("Provider returned an invalid response")
        page_jobs = search_result["SearchResultItems"]
        jobs.extend(page_jobs)
        if len(page_jobs) < USAJOBS_PAGE_SIZE:
            break
    return jobs


def _validate_jla_payload(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise _ProviderError("Provider returned an invalid response")
    page_jobs = payload.get("jobs")
    total = payload.get("total")
    if (
        not isinstance(page_jobs, list)
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
    ):
        raise _ProviderError("Provider returned an invalid response")
    return page_jobs, total


def _jla_quota_remaining(headers):
    """Remaining quota (int) agar X-RateLimit-* headers sahi hon, warna None."""
    if headers is None:
        return None
    values = {}
    for name in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
        raw = headers.get(name)
        if raw is None:
            return None
        raw = str(raw).strip()
        if not raw:
            return None
        values[name] = raw
    for name in ("X-RateLimit-Limit", "X-RateLimit-Remaining"):
        if not (values[name].isascii() and values[name].isdigit()):
            return None
    limit = int(values["X-RateLimit-Limit"])
    remaining = int(values["X-RateLimit-Remaining"])
    if limit < 1 or remaining > limit:
        return None
    return remaining


def _load_job_listings_api_jobs(api_key):
    headers = {"X-API-Key": api_key}
    jobs_by_id = {}
    pagination_incomplete = False
    completed_windows = {}
    requests_made = 0
    now = datetime.now(timezone.utc)

    use_date_windows = os.getenv("JLA_USE_DATE_WINDOWS", "").lower() == "true"
    window_days = int(os.getenv("JLA_WINDOW_DAYS", "7"))

    if use_date_windows:
        window_end = now.date()
        window_start = window_end - timedelta(days=window_days)
    else:
        window_start = None
        window_end = None

    checkpoint = _load_checkpoint()
    window_key = str(window_start) if window_start else "default"
    saved = checkpoint.get("windows", {}).get(window_key, {}).get("offset", 0)
    start_offset = saved if isinstance(saved, int) and saved > 0 else 0
    offset = start_offset
    expected_total = None
    cycle_finished = False

    while requests_made < MAX_JOB_LISTINGS_API_REQUESTS_PER_SYNC:
        params = {"limit": JOB_LISTINGS_API_PAGE_SIZE, "offset": offset}
        if use_date_windows and window_start and window_end:
            params["posted_after"] = window_start.isoformat()
            params["posted_before"] = window_end.isoformat()

        # Error aaye to _ProviderError upar tak jayega, checkpoint aage nahi badhega
        payload, response_headers = _request_json(
            JOB_LISTINGS_API_URL,
            params,
            headers=headers,
            include_headers=True,
            stop_on_rate_limit=True,
            max_attempts=1,
        )
        requests_made += 1

        page_jobs, total = _validate_jla_payload(payload)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            # Beech mein total badal gaya, ye page mat lo
            pagination_incomplete = True
            break
        if offset + len(page_jobs) > total:
            raise _ProviderError(
                "Provider returned more jobs than the advertised total"
            )

        remaining = _jla_quota_remaining(response_headers)
        if remaining is None:
            pagination_incomplete = True

        duplicate_seen = False
        new_in_page = {}
        for job in page_jobs:
            if not isinstance(job, dict):
                raise _ProviderError("Provider returned an invalid job record")
            source_id = str(job.get("id", "")).strip()
            if not source_id:
                continue
            _jla_expiry_is_past(job.get("valid_through"))  # galat date par error
            if source_id in jobs_by_id or source_id in new_in_page:
                duplicate_seen = True
                logger.info("JLA pagination overlap detected; duplicate source ID skipped")
                continue
            new_in_page[source_id] = job
        jobs_by_id.update(new_in_page)
        if duplicate_seen:
            pagination_incomplete = True
        if not (duplicate_seen and not new_in_page):
            offset += len(page_jobs)

        if not page_jobs:
            if offset >= total:
                cycle_finished = True
            else:
                pagination_incomplete = True
            break
        if offset >= total:
            cycle_finished = True
            break
        if pagination_incomplete:
            break
        if remaining == 0:
            pagination_incomplete = True
            break

    if not cycle_finished:
        pagination_incomplete = True
    elif start_offset != 0:
        # Cycle ka sirf aakhri hissa mila, poora snapshot nahi
        pagination_incomplete = True

    checkpoint.setdefault("windows", {})[window_key] = {
        "offset": 0 if cycle_finished else offset,
        "completed": cycle_finished,
    }
    if not pagination_incomplete:
        checkpoint["last_successful"] = now.isoformat()
    _save_checkpoint(checkpoint)

    if (
        use_date_windows and window_start and window_end
        and cycle_finished and start_offset == 0 and not pagination_incomplete
    ):
        completed_windows[
            f"{window_start.isoformat()}_to_{window_end.isoformat()}"
        ] = set(jobs_by_id.keys())

    return list(jobs_by_id.values()), pagination_incomplete, completed_windows



def _load_arbeitnow_jobs():
    jobs = []
    for page in range(1, MAX_ARBEITNOW_PAGES + 1):
        payload = _request_json(ARBEITNOW_API_URL, {"page": page})
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("data"), list)
            or not isinstance(payload.get("links"), dict)
        ):
            raise _ProviderError("Provider returned an invalid response")
        jobs.extend(payload["data"])
        if not payload["links"].get("next"):
            break
    return jobs


def _load_greenhouse_jobs(board):
    payload = _request_json(
        "{}/{}/jobs".format(GREENHOUSE_API_URL, board),
        {"content": "true"},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise _ProviderError("Provider returned an invalid response")
    return payload["jobs"]


def _configured_lever_sites():
    configured = os.getenv("LEVER_SITE_COMPANIES", "").strip()
    if not configured:
        return {}
    try:
        mapping = json.loads(configured)
    except (TypeError, ValueError) as error:
        raise ValueError("Lever site configuration is invalid") from error
    if (
        not isinstance(mapping, dict)
        or not mapping
        or len(mapping) > MAX_CONFIGURED_LEVER_SITES
    ):
        raise ValueError("Lever site configuration is invalid")
    normalized = {}
    for site, company_details in mapping.items():
        if (
            not isinstance(site, str)
            or not site
            or len(site) > 100
            or not all(character.isalnum() or character in "-_" for character in site)
        ):
            raise ValueError("Lever site configuration is invalid")
        if isinstance(company_details, str):
            company = company_details
            region = "global"
        elif isinstance(company_details, dict):
            company = company_details.get("company")
            region = company_details.get("region", "global")
        else:
            raise ValueError("Lever site configuration is invalid")
        if (
            not isinstance(company, str)
            or not company.strip()
            or len(company.strip()) > 200
            or region not in {"global", "eu"}
        ):
            raise ValueError("Lever site configuration is invalid")
        normalized[site] = {"company": company.strip(), "region": region}
    return normalized


def _configured_greenhouse_boards():
    configured = os.getenv("GREENHOUSE_BOARDS", "").strip()
    if not configured:
        return {}
    try:
        mapping = json.loads(configured)
    except (TypeError, ValueError) as error:
        raise ValueError("Greenhouse board configuration is invalid") from error
    if (
        not isinstance(mapping, dict)
        or not mapping
        or len(mapping) > MAX_CONFIGURED_GREENHOUSE_BOARDS
    ):
        raise ValueError("Greenhouse board configuration is invalid")
    normalized = {}
    for board, board_config in mapping.items():
        if (
            not isinstance(board, str)
            or not board
            or len(board) > 100
            or not all(character.isalnum() or character in "-_" for character in board)
        ):
            raise ValueError("Greenhouse board configuration is invalid")
        if isinstance(board_config, str):
            company = board_config
            url_hosts = []
        elif isinstance(board_config, dict):
            company = board_config.get("company")
            url_hosts = board_config.get("url_hosts", [])
        else:
            raise ValueError("Greenhouse board configuration is invalid")
        if (
            not isinstance(company, str)
            or not company.strip()
            or len(company.strip()) > 200
            or not isinstance(url_hosts, list)
            or len(url_hosts) > 10
        ):
            raise ValueError("Greenhouse board configuration is invalid")
        normalized_hosts = []
        for host in url_hosts:
            if (
                not isinstance(host, str)
                or not host
                or len(host) > 253
                or host != host.lower()
                or any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or not all(character.isalnum() or character == "-" for character in label)
                    for label in host.split(".")
                )
            ):
                raise ValueError("Greenhouse board configuration is invalid")
            normalized_hosts.append(host)
        normalized[board] = {
            "company": company.strip(),
            "url_hosts": normalized_hosts,
        }
    return normalized


def _arbeitnow_enabled():
    configured = os.getenv("ARBEITNOW_ENABLED", "").strip().lower()
    if configured in {"", "false", "0", "no"}:
        return False
    if configured in {"true", "1", "yes"}:
        return True
    raise ValueError("Arbeitnow configuration is invalid")


def _disabled_pending_permission():
    return {
        "status": "disabled_pending_permission",
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [
            {"error": "Provider data-use authorization is not configured"}
        ],
    }


def _load_lever_jobs(site, region="global"):
    jobs = []
    api_url = LEVER_EU_API_URL if region == "eu" else LEVER_API_URL
    for page in range(MAX_LEVER_PAGES):
        page_jobs = _request_json(
            "{}/{}".format(api_url, site),
            {"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE},
        )
        if not isinstance(page_jobs, list):
            raise _ProviderError("Provider returned an invalid response")
        jobs.extend(page_jobs)
        if len(page_jobs) < PAGE_SIZE:
            break
    return jobs


def _sync_source(source_name, provider_jobs, parser):
    summary = {
        "status": "succeeded",
        "processed": len(provider_jobs),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }
    connection = None
    cursor = None
    try:
        _require_staging_job_target()
        connection = get_db_connection()
        if connection is None:
            raise RuntimeError("Database is unavailable")
        cursor = connection.cursor(dictionary=True)
        for provider_job in provider_jobs:
            try:
                job = parser(provider_job)
            except (TypeError, ValueError, OverflowError) as error:
                summary["skipped"] += 1
                source_id = (
                    provider_job.get("id")
                    if isinstance(provider_job, dict)
                    else None
                )
                logger.warning(
                    "%s job record skipped: source_id=%s error_type=%s reason=%s",
                    source_name,
                    source_id,
                    type(error).__name__,
                    str(error),
                )
                summary["errors"].append({
                    "source_job_id": source_id,
                    "error": str(error),
                })
                continue

            try:
                outcome = _sync_job(cursor, job, source_name=source_name)
                connection.commit()
                summary[outcome] += 1
            except Exception as error:
                connection.rollback()
                logger.error(
                    "%s job sync failed (%s)", source_name, type(error).__name__
                )
                summary["errors"].append({"error": "Database write failed"})
    except Exception as error:
        if connection is not None:
            connection.rollback()
        logger.error(
            "%s synchronization failed (%s)", source_name, type(error).__name__
        )
        summary["status"] = "failed"
        summary["errors"].append({"error": "Database synchronization failed"})
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
    if summary["errors"] and summary["status"] != "failed":
        summary["status"] = "partial"
    return summary


def _report_record_limit(result, limit):
    result["record_limit"] = limit
    result["errors"].append(
        {"error": "Configured record limit reached; more listings may remain"}
    )
    if result["status"] == "succeeded":
        result["status"] = "partial"


def _require_staging_job_target():
    # Explicit opt-in for original/production DB writes (college/demo use).
    if os.getenv("JLA_ALLOW_PRODUCTION_WRITE", "").strip().lower() == "true":
        return
    if (
        os.getenv("DB_STAGING_GUARD", "").strip().lower() != "true"
        or os.getenv("DB_NAME", "").strip() != "resume_analyzer_restore_test"
        or not all(os.getenv(name) for name in (
            "DB_EXPECTED_PORT", "DB_EXPECTED_DATA_DIR", "DB_EXPECTED_SERVER_UUID"
        ))
    ):
        raise _ProviderError("JLA sync requires a verified isolated staging database")

def _reconcile_job_listings_api_statuses(provider_jobs, complete, sync_result):
    """Soft-close authoritative removals and expire dates; never delete rows."""
    if sync_result.get("status") not in {"succeeded", "partial"}:
        return {"closed": 0, "expired": 0, "missing_closed": 0}

    removed_ids = []
    expired_ids = []
    snapshot_ids = []
    for job in provider_jobs:
        source_id = str(job.get("id", "")).strip()
        if not source_id:
            continue
        snapshot_ids.append(source_id)
        if job.get("status", "active") == "removed":
            removed_ids.append(source_id)
        elif _jla_expiry_is_past(job.get("valid_through")):
            expired_ids.append(source_id)

    may_close_missing = (
        os.getenv("JLA_CLOSE_MISSING_JOBS", "").strip().lower() == "true"
        and complete
        and sync_result["status"] == "succeeded"
        and bool(snapshot_ids)
    )
    
    if not removed_ids and not expired_ids and not may_close_missing:
        return {"closed": 0, "expired": 0, "missing_closed": 0}

    connection = get_db_connection()
    if connection is None:
        raise RuntimeError("Database is unavailable")
    cursor = None
    counts = {"closed": 0, "expired": 0, "missing_closed": 0}
    try:
        cursor = connection.cursor()
        for state, ids in (("closed", removed_ids), ("expired", expired_ids)):
            for start in range(0, len(set(ids)), 500):
                batch = list(dict.fromkeys(ids))[start:start + 500]
                if not batch:
                    continue
                _verify_jla_write_target(connection, cursor)
                placeholders = ",".join(["%s"] * len(batch))
                cursor.execute(
                    f"UPDATE jobs SET status = %s WHERE source_name = %s "
                    f"AND source_job_id IN ({placeholders}) AND status <> %s",
                    (state, JOB_LISTINGS_API_SOURCE_NAME, *batch, state),
                )
                counts[state] += max(0, cursor.rowcount)

        if may_close_missing:
            encoded_ids = json.dumps(sorted(set(snapshot_ids)))
            _verify_jla_write_target(connection, cursor)
            cursor.execute(
                "UPDATE jobs AS j LEFT JOIN JSON_TABLE(%s, '$[*]' "
                "COLUMNS (source_job_id VARCHAR(255) PATH '$')) AS seen "
                "ON seen.source_job_id = j.source_job_id "
                "SET j.status = 'closed' WHERE j.source_name = %s "
                "AND j.status = 'open' AND seen.source_job_id IS NULL",
                (encoded_ids, JOB_LISTINGS_API_SOURCE_NAME),
            )
            counts["missing_closed"] = max(0, cursor.rowcount)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
    return counts


def _close_missing_jobs_in_completed_windows(cursor, source_name, completed_windows):
    """Close jobs missing from completed date windows only."""
    total_closed = 0
    for window_key, fetched_ids in completed_windows.items():
        if not fetched_ids:
            continue
        try:
            window_start, window_end = window_key.split("_to_")
        except ValueError:
            continue

        placeholders = ",".join(["%s"] * len(fetched_ids))
        query = f"""
            UPDATE jobs
            SET status = 'closed', last_synced_at = NOW()
            WHERE source_name = %s
              AND status = 'open'
              AND posted_at >= %s
              AND posted_at < %s
              AND source_job_id NOT IN ({placeholders})
        """
        params = [source_name, window_start, window_end] + list(fetched_ids)
        cursor.execute(query, params)
        total_closed += cursor.rowcount
    return total_closed

def _verify_jla_write_target(connection, cursor):
    if os.getenv("JLA_ALLOW_PRODUCTION_WRITE", "").strip().lower() == "true":
        return
    from db import verify_database_target

    verify_database_target(connection)
    cursor.execute("SELECT DATABASE()")
    row = cursor.fetchone()
    database = row[0] if isinstance(row, (tuple, list)) else next(iter(row.values()))
    if database != "resume_analyzer_restore_test":
        raise RuntimeError("JLA write target is not the isolated staging database")

def _jla_expiry_is_past(value):
    if value is None:
        return False
    if not isinstance(value, str):
        raise _ProviderError("Provider returned an invalid expiry date")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _ProviderError("Provider returned an invalid expiry date") from error
    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return expiry <= datetime.now(timezone.utc).replace(tzinfo=None)


def get_job_dataset_diagnostics():
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                j.source_name,
                COUNT(*) AS total_jobs,
                COUNT(DISTINCT j.source_job_id) AS distinct_source_ids,
                SUM(
                    j.source_job_id IS NULL
                    OR TRIM(j.source_job_id) = ''
                ) AS missing_source_ids,
                SUM(
                    j.source_url IS NULL
                    OR TRIM(j.source_url) = ''
                ) AS missing_source_urls,
                SUM(
                    j.description IS NULL
                    OR TRIM(j.description) = ''
                ) AS missing_descriptions,
                SUM(
                    NOT EXISTS (
                        SELECT 1
                        FROM job_skills js
                        WHERE js.job_id = j.id
                    )
                ) AS jobs_without_skills,
                SUM(j.status = 'open') AS open_jobs,
                SUM(j.status = 'closed') AS closed_jobs,
                SUM(j.status = 'expired') AS expired_jobs,
                SUM(j.last_synced_at IS NULL) AS missing_sync_timestamps,
                MIN(j.last_synced_at) AS oldest_last_synced_at,
                MAX(j.last_synced_at) AS newest_last_synced_at
            FROM jobs j
            GROUP BY j.source_name
            ORDER BY j.source_name
            """
        )
        source_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT COUNT(*) AS duplicate_source_keys
            FROM (
                SELECT source_name, source_job_id
                FROM jobs
                WHERE source_name IS NOT NULL
                  AND source_job_id IS NOT NULL
                GROUP BY source_name, source_job_id
                HAVING COUNT(*) > 1
            ) duplicate_keys
            """
        )
        duplicate_row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS total_jobs FROM jobs")
        total_row = cursor.fetchone()

        def serialize_timestamp(value):
            return value.isoformat(sep=" ") if value is not None else None

        return {
            "total_jobs": total_row["total_jobs"],
            "duplicate_source_keys": duplicate_row["duplicate_source_keys"],
            "sources": [
                {
                    **row,
                    "oldest_last_synced_at": serialize_timestamp(
                        row["oldest_last_synced_at"]
                    ),
                    "newest_last_synced_at": serialize_timestamp(
                        row["newest_last_synced_at"]
                    ),
                }
                for row in source_rows
            ],
        }
    except Exception as error:
        logger.error(
            "Job dataset diagnostics failed (%s)", type(error).__name__
        )
        raise HTTPException(
            status_code=503,
            detail="Job dataset diagnostics are unavailable.",
        ) from error
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def _synchronize_configured_sources_unlocked():
    sources = {
        THE_MUSE_SOURCE_NAME: {"status": "not_configured"},
        USAJOBS_SOURCE_NAME: {"status": "not_configured"},
        "Lever": {"status": "not_configured"},
        ARBEITNOW_SOURCE_NAME: {"status": "not_configured"},
        GREENHOUSE_SOURCE_NAME: {"status": "not_configured"},
        JOB_LISTINGS_API_SOURCE_NAME: {"status": "not_configured"},
    }
    attempted_sources = []
    successful_sources = []
    failures = []
    api_key = os.getenv("THE_MUSE_API_KEY", "").strip()
    if api_key and not provider_use_authorized(THE_MUSE_SOURCE_NAME, "ingestion"):
        sources[THE_MUSE_SOURCE_NAME] = _disabled_pending_permission()
        api_key = ""
    if api_key:
        attempted_sources.append(THE_MUSE_SOURCE_NAME)
        try:
            if len(api_key) > 512 or any(ord(character) < 32 for character in api_key):
                raise ValueError("Invalid API key configuration")
            jobs = _load_the_muse_jobs(api_key)
            result = _sync_source(THE_MUSE_SOURCE_NAME, jobs, _parse_the_muse_job)
            if len(jobs) >= MAX_THE_MUSE_PAGES * 20:
                _report_record_limit(result, MAX_THE_MUSE_PAGES * 20)
        except _ProviderError as error:
            logger.warning("The Muse synchronization failed (%s)", str(error))
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": str(error)}],
            }
        except Exception as error:
            logger.error("The Muse synchronization failed (%s)", type(error).__name__)
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": "Provider configuration is invalid"}],
            }
        sources[THE_MUSE_SOURCE_NAME] = result
        if result["status"] == "succeeded":
            successful_sources.append(THE_MUSE_SOURCE_NAME)
        if result["status"] != "succeeded":
            failures.append({"source": THE_MUSE_SOURCE_NAME, "error": result["errors"]})

    usajobs_api_key = os.getenv("USAJOBS_API_KEY", "").strip()
    usajobs_user_agent = os.getenv("USAJOBS_USER_AGENT_EMAIL", "").strip()
    if usajobs_api_key or usajobs_user_agent:
        attempted_sources.append(USAJOBS_SOURCE_NAME)
        try:
            if (
                not usajobs_api_key
                or len(usajobs_api_key) > 512
                or any(ord(character) < 32 for character in usajobs_api_key)
                or not usajobs_user_agent
                or len(usajobs_user_agent) > 254
                or "@" not in usajobs_user_agent
                or any(ord(character) < 32 for character in usajobs_user_agent)
            ):
                raise ValueError("Invalid USAJOBS configuration")
            jobs = _load_usajobs_jobs(usajobs_api_key, usajobs_user_agent)
            result = _sync_source(
                USAJOBS_SOURCE_NAME,
                jobs,
                _parse_usajobs_job,
            )
            if len(jobs) >= MAX_USAJOBS_PAGES * USAJOBS_PAGE_SIZE:
                _report_record_limit(
                    result, MAX_USAJOBS_PAGES * USAJOBS_PAGE_SIZE
                )
        except _ProviderError as error:
            logger.warning("USAJOBS synchronization failed (%s)", str(error))
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": str(error)}],
            }
        except Exception as error:
            logger.error("USAJOBS synchronization failed (%s)", type(error).__name__)
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": "Provider configuration is invalid"}],
            }
        sources[USAJOBS_SOURCE_NAME] = result
        if result["status"] == "succeeded":
            successful_sources.append(USAJOBS_SOURCE_NAME)
        if result["status"] != "succeeded":
            failures.append({"source": USAJOBS_SOURCE_NAME, "error": result["errors"]})

    job_listings_api_key = os.getenv("JLA_API_KEY", "").strip()
    if job_listings_api_key and not provider_use_authorized(
        JOB_LISTINGS_API_SOURCE_NAME, "ingestion"
    ):
        sources[JOB_LISTINGS_API_SOURCE_NAME] = _disabled_pending_permission()
        job_listings_api_key = ""
    if job_listings_api_key:
        attempted_sources.append(JOB_LISTINGS_API_SOURCE_NAME)
        try:
            if len(job_listings_api_key) > 512 or any(
                ord(character) < 32 for character in job_listings_api_key
            ):
                raise ValueError("Invalid API key configuration")
            _require_staging_job_target()
            provider_jobs, pagination_incomplete, _ = _load_job_listings_api_jobs(job_listings_api_key)
            active_jobs = [job for job in provider_jobs if job.get("status", "active") == "active"]
            result = _sync_source(
                JOB_LISTINGS_API_SOURCE_NAME,
                active_jobs,
                _parse_job_listings_api_job,
            )

            result["pagination_complete"] = not pagination_incomplete
            result["provider_records"] = len(provider_jobs)
            result["removed_records"] = sum(
                job.get("status") == "removed" for job in provider_jobs
            )
            if pagination_incomplete and result["status"] == "succeeded":
                result["status"] = "partial"
                result["errors"].append({"error": "Provider pagination was incomplete"})
            try:
                result["reconciliation"] = _reconcile_job_listings_api_statuses(
                    provider_jobs, not pagination_incomplete, result
                )
            except Exception as error:
                logger.error(
                    "Job Listings API reconciliation failed (%s)",
                    type(error).__name__,
                )
                result["status"] = "partial"
                result["errors"].append(
                    {"error": "Job status reconciliation failed"}
                )
        except _ProviderError as error:
            logger.warning("Job Listings API synchronization failed (%s)", str(error))
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": str(error)}],
            }
        except Exception as error:
            logger.error(
                "Job Listings API synchronization failed (%s)",
                type(error).__name__,
            )
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": "Provider configuration is invalid"}],
            }
        sources[JOB_LISTINGS_API_SOURCE_NAME] = result
        if result["status"] == "succeeded":
            successful_sources.append(JOB_LISTINGS_API_SOURCE_NAME)
        if result["status"] != "succeeded":
            failures.append(
                {"source": JOB_LISTINGS_API_SOURCE_NAME, "error": result["errors"]}
            )

    try:
        lever_sites = _configured_lever_sites()
    except ValueError:
        lever_sites = None
        sources["Lever"] = {
            "status": "failed",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "Provider configuration is invalid"}],
        }
        failures.append(
            {
                "source": "Lever",
                "error": [{"error": "Provider configuration is invalid"}],
            }
        )

    if lever_sites:
        if not provider_use_authorized("Lever", "ingestion"):
            sources["Lever"] = _disabled_pending_permission()
            lever_sites = {}
    if lever_sites:
        attempted_sources.append("Lever")
        site_results = {}
        for site, provider_config in lever_sites.items():
            try:
                provider_jobs = _load_lever_jobs(
                    site, provider_config["region"]
                )
            except _ProviderError as error:
                logger.warning(
                    "Lever synchronization failed (%s)", type(error).__name__
                )
                site_results[site] = {
                    "status": "failed",
                    "processed": 0,
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"error": "Provider request or response failed"}],
                }
                continue
            records = [
                (job, site, provider_config["company"])
                for job in provider_jobs
            ]
            site_results[site] = _sync_source(
                "Lever",
                records,
                lambda record: _parse_lever_job(*record),
            )
            if len(provider_jobs) >= MAX_LEVER_PAGES * PAGE_SIZE:
                _report_record_limit(
                    site_results[site], MAX_LEVER_PAGES * PAGE_SIZE
                )
        source_statuses = {
            source["status"] for source in site_results.values()
        }
        if source_statuses == {"succeeded"}:
            status = "succeeded"
        elif "succeeded" in source_statuses or "partial" in source_statuses:
            status = "partial"
        else:
            status = "failed"
        result = {
            "status": status,
            **{
                key: sum(source.get(key, 0) for source in site_results.values())
                for key in ("processed", "inserted", "updated", "skipped")
            },
            "errors": [
                {"site": site, "error": error}
                for site, site_result in site_results.items()
                for error in site_result["errors"]
            ],
            "sites": site_results,
        }
        sources["Lever"] = result
        if result["status"] == "succeeded":
            successful_sources.append("Lever")
        if result["status"] != "succeeded":
            failures.append({"source": "Lever", "error": result["errors"]})

    try:
        arbeitnow_enabled = _arbeitnow_enabled()
    except ValueError:
        arbeitnow_enabled = False
        sources[ARBEITNOW_SOURCE_NAME] = {
            "status": "failed",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "Provider configuration is invalid"}],
        }
        failures.append(
            {
                "source": ARBEITNOW_SOURCE_NAME,
                "error": [{"error": "Provider configuration is invalid"}],
            }
        )
    if arbeitnow_enabled:
        if not provider_use_authorized(ARBEITNOW_SOURCE_NAME, "ingestion"):
            sources[ARBEITNOW_SOURCE_NAME] = _disabled_pending_permission()
            arbeitnow_enabled = False
    if arbeitnow_enabled:
        attempted_sources.append(ARBEITNOW_SOURCE_NAME)
        try:
            jobs = _load_arbeitnow_jobs()
            result = _sync_source(
                ARBEITNOW_SOURCE_NAME,
                jobs[:MAX_ARBEITNOW_PAGES * ARBEITNOW_PAGE_SIZE],
                _parse_arbeitnow_job,
            )
            if len(jobs) >= MAX_ARBEITNOW_PAGES * ARBEITNOW_PAGE_SIZE:
                _report_record_limit(
                    result, MAX_ARBEITNOW_PAGES * ARBEITNOW_PAGE_SIZE
                )
        except _ProviderError as error:
            logger.warning("Arbeitnow synchronization failed (%s)", str(error))
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": str(error)}],
            }
        except Exception as error:
            logger.error(
                "Arbeitnow synchronization failed (%s)", type(error).__name__
            )
            result = {
                "status": "failed",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": "Provider configuration is invalid"}],
            }
        sources[ARBEITNOW_SOURCE_NAME] = result
        if result["status"] == "succeeded":
            successful_sources.append(ARBEITNOW_SOURCE_NAME)
        if result["status"] != "succeeded":
            failures.append(
                {"source": ARBEITNOW_SOURCE_NAME, "error": result["errors"]}
            )

    try:
        greenhouse_boards = _configured_greenhouse_boards()
    except ValueError:
        greenhouse_boards = None
        sources[GREENHOUSE_SOURCE_NAME] = {
            "status": "failed",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "Provider configuration is invalid"}],
        }
        failures.append(
            {
                "source": GREENHOUSE_SOURCE_NAME,
                "error": [{"error": "Provider configuration is invalid"}],
            }
        )

    if greenhouse_boards:
        if not provider_use_authorized(GREENHOUSE_SOURCE_NAME, "ingestion"):
            sources[GREENHOUSE_SOURCE_NAME] = _disabled_pending_permission()
            greenhouse_boards = {}
    if greenhouse_boards:
        attempted_sources.append(GREENHOUSE_SOURCE_NAME)
        board_results = {}
        for board, board_config in greenhouse_boards.items():
            try:
                provider_jobs = _load_greenhouse_jobs(board)
            except _ProviderError as error:
                logger.warning(
                    "Greenhouse synchronization failed (%s)", str(error)
                )
                board_results[board] = {
                    "status": "failed",
                    "processed": 0,
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"error": "Provider request or response failed"}],
                }
                continue
            records = [
                (job, board, board_config["company"], board_config["url_hosts"])
                for job in provider_jobs[:MAX_GREENHOUSE_JOBS_PER_BOARD]
            ]
            board_results[board] = _sync_source(
                GREENHOUSE_SOURCE_NAME,
                records,
                lambda record: _parse_greenhouse_job(*record),
            )
            if len(provider_jobs) >= MAX_GREENHOUSE_JOBS_PER_BOARD:
                _report_record_limit(
                    board_results[board], MAX_GREENHOUSE_JOBS_PER_BOARD
                )
        board_statuses = {
            result["status"] for result in board_results.values()
        }
        if board_statuses == {"succeeded"}:
            status = "succeeded"
        elif "succeeded" in board_statuses or "partial" in board_statuses:
            status = "partial"
        else:
            status = "failed"
        result = {
            "status": status,
            **{
                key: sum(board.get(key, 0) for board in board_results.values())
                for key in ("processed", "inserted", "updated", "skipped")
            },
            "errors": [
                {"board": board, "error": error}
                for board, board_result in board_results.items()
                for error in board_result["errors"]
            ],
            "boards": board_results,
        }
        sources[GREENHOUSE_SOURCE_NAME] = result
        if result["status"] == "succeeded":
            successful_sources.append(GREENHOUSE_SOURCE_NAME)
        if result["status"] != "succeeded":
            failures.append(
                {"source": GREENHOUSE_SOURCE_NAME, "error": result["errors"]}
            )

    totals = {
        key: sum(source.get(key, 0) for source in sources.values())
        for key in ("processed", "inserted", "updated", "skipped")
    }
    return {
        "attempted_sources": attempted_sources,
        "successful_sources": successful_sources,
        **totals,
        "failures": failures,
        "errors": failures,
        "sources": sources,
    }


def synchronize_configured_sources():
    """Prevent overlapping sync runs within this API process."""
    if not _SYNC_RUN_LOCK.acquire(blocking=False):
        return {
            "attempted_sources": [],
            "successful_sources": [],
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failures": [{"error": "A job synchronization is already running"}],
            "errors": [{"error": "A job synchronization is already running"}],
            "sources": {},
        }
    try:
        return _synchronize_configured_sources_unlocked()
    finally:
        _SYNC_RUN_LOCK.release()


def require_job_sync_admin(user):
    configured_ids = os.getenv("JOB_SYNC_ADMIN_USER_IDS", "").strip()
    if not configured_ids:
        raise HTTPException(
            status_code=503,
            detail="Job synchronization is not configured.",
        )

    try:
        admin_ids = {
            int(value.strip())
            for value in configured_ids.split(",")
            if value.strip()
        }
    except ValueError as error:
        logger.error("Job synchronization admin configuration is invalid")
        raise HTTPException(
            status_code=503,
            detail="Job synchronization is not configured.",
        ) from error

    if user.get("id") not in admin_ids:
        raise HTTPException(status_code=403, detail="Administrator access required.")

def synchronize_job_listings_api_only():
    """Synchronize only Job Listings API jobs into the guarded staging DB."""
    if not _SYNC_RUN_LOCK.acquire(blocking=False):
        return {
            "status": "busy",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "A job synchronization is already running"}],
        }

    try:
        # _require_staging_job_target()

        if not provider_use_authorized(
            JOB_LISTINGS_API_SOURCE_NAME, "ingestion"
        ):
            return _disabled_pending_permission()

        api_key = os.getenv("JLA_API_KEY", "").strip()
        if not api_key:
            return {
                "status": "not_configured",
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [{"error": "JLA API key is not configured"}],
            }

        if len(api_key) > 512 or any(
            ord(character) < 32 for character in api_key
        ):
            raise _ProviderError("Invalid API key configuration")

        provider_jobs, pagination_incomplete, completed_windows = (
            _load_job_listings_api_jobs(api_key)
        )

        active_jobs = [
            job for job in provider_jobs
            if job.get("status", "active") == "active"
        ]

        result = _sync_source(
            JOB_LISTINGS_API_SOURCE_NAME,
            active_jobs,
            _parse_job_listings_api_job,
        )

        result["pagination_complete"] = not pagination_incomplete
        result["provider_records"] = len(provider_jobs)
        result["removed_records"] = sum(
            job.get("status") == "removed" for job in provider_jobs
        )

        if pagination_incomplete and result["status"] == "succeeded":
            result["status"] = "partial"
            result["errors"].append(
                {"error": "Provider pagination was incomplete"}
            )

        try:
            result["reconciliation"] = (
                _reconcile_job_listings_api_statuses(
                    provider_jobs,
                    not pagination_incomplete,
                    result,
                )
            )
        except Exception as error:
            logger.exception("JLA-only reconciliation failed")
            result["status"] = "partial"
            result["errors"].append(
                {"error": "Job status reconciliation failed"}
            )

        if completed_windows:
            connection = get_db_connection()
            if connection is not None:
                cursor = None
                try:
                    cursor = connection.cursor()
                    closed = _close_missing_jobs_in_completed_windows(
                        cursor,
                        JOB_LISTINGS_API_SOURCE_NAME,
                        completed_windows,
                    )
                    connection.commit()
                    if "reconciliation" not in result:
                        result["reconciliation"] = {}
                    result["reconciliation"]["window_closed"] = closed
                finally:
                    if cursor is not None:
                        cursor.close()
                    connection.close()

        return result

    except _ProviderError as error:
        logger.warning("JLA-only sync failed (%s)", str(error))
        return {
            "status": "failed",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": str(error)}],
        }
    except Exception as error:
        logger.error("JLA-only sync failed (%s)", type(error).__name__)
        return {
            "status": "failed",
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "JLA-only synchronization failed"}],
        }
    finally:
        _SYNC_RUN_LOCK.release()