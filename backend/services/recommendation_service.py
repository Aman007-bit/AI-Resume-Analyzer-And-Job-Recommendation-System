import logging
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import urlsplit

from fastapi import HTTPException
from db import get_db_connection
from services.resume_service import extract_skills
from services.provider_policy import (
    PROVIDER_USE_AUTHORIZATION,
    provider_use_authorized,
)

logger = logging.getLogger(__name__)


# These skills represent equivalent knowledge for matching purposes.
# The database schema and stored skill names remain unchanged.
DSA_SKILLS = {
    "data structures and algorithms",
    "data structures",
    "algorithms",
    "data structures & algorithms",
}
MIN_DUPLICATE_DESCRIPTION_SIMILARITY = 0.9
MAX_MATCHING_TEXT_CHARS = 100_000


def normalize_skill_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def skills_match(resume_skill_names: set[str], required_skill_name: str) -> bool:
    required = normalize_skill_name(required_skill_name)
    if required in resume_skill_names:
        return True

    # A combined DSA skill covers either component; both components together
    # also satisfy a job requirement written as the combined phrase.
    if required in DSA_SKILLS:
        if "data structures and algorithms" in resume_skill_names:
            return True
        if required == "data structures and algorithms":
            return {"data structures", "algorithms"}.issubset(resume_skill_names)
        if required == "data structures & algorithms":
            return {"data structures", "algorithms"}.issubset(resume_skill_names)

    return False


def _normalize_listing_text(value: str | None) -> str:
    text = unescape(value or "").casefold()
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def calculate_tfidf_cosine_scores(resume_text: str | None, descriptions: list[str | None]) -> list[float]:
    """Compare authorized resume and job text without retaining vectorizer data."""
    resume_document = (resume_text or "")[:MAX_MATCHING_TEXT_CHARS]
    job_documents = [
        re.sub(r"<[^>]*>", " ", unescape(text or ""))[:MAX_MATCHING_TEXT_CHARS]
        for text in descriptions
    ]
    if not resume_document.strip():
        return [0.0] * len(job_documents)
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        matrix = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), max_features=20_000
        ).fit_transform([resume_document, *job_documents])
        return [
            float(score)
            for score in cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        ]
    except ModuleNotFoundError as error:
        if error.name != "sklearn":
            raise
        # Keep existing offline test/development environments usable when the
        # pinned production dependency has not yet been installed.
        documents = [resume_document, *job_documents]
        terms_by_doc = [
            Counter(re.findall(r"(?u)\b\w\w+\b", doc.casefold()))
            for doc in documents
        ]
        vocabulary = set().union(*(terms.keys() for terms in terms_by_doc))
        if not vocabulary:
            return [0.0] * len(job_documents)
        document_frequency = {
            term: sum(term in terms for terms in terms_by_doc)
            for term in vocabulary
        }
        idf = {
            term: math.log((1 + len(documents)) / (1 + frequency)) + 1
            for term, frequency in document_frequency.items()
        }

        def vector(terms):
            values = {term: count * idf[term] for term, count in terms.items()}
            norm = math.sqrt(sum(value * value for value in values.values()))
            return {term: value / norm for term, value in values.items()} if norm else {}

        vectors = [vector(terms) for terms in terms_by_doc]
        return [
            sum(value * vectors[0].get(term, 0.0) for term, value in item.items())
            for item in vectors[1:]
        ]
    except ValueError:  # Empty vocabulary (for example, punctuation-only input).
        return [0.0] * len(job_documents)


def _normalize_listing_url(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return "{}://{}{}".format(parsed.scheme.casefold(), host, path)


def _locations_compatible(left: str | None, right: str | None) -> bool:
    left_normalized = _normalize_listing_text(left)
    right_normalized = _normalize_listing_text(right)
    if not left_normalized or not right_normalized:
        return False
    left_terms = set(left_normalized.split())
    right_terms = set(right_normalized.split())
    return left_terms.issubset(right_terms) or right_terms.issubset(left_terms)


def _is_duplicate_listing(left: dict, right: dict) -> bool:
    if left.get("source_name") == right.get("source_name"):
        return False
    if (
        not _normalize_listing_text(left.get("title"))
        or _normalize_listing_text(left.get("title"))
        != _normalize_listing_text(right.get("title"))
        or not _normalize_listing_text(left.get("company"))
        or _normalize_listing_text(left.get("company"))
        != _normalize_listing_text(right.get("company"))
    ):
        return False

    left_url = _normalize_listing_url(left.get("source_url"))
    right_url = _normalize_listing_url(right.get("source_url"))
    if left_url and left_url == right_url:
        return True

    if not _locations_compatible(left.get("location"), right.get("location")):
        return False
    left_description = _normalize_listing_text(left.get("description"))
    right_description = _normalize_listing_text(right.get("description"))
    if not left_description or not right_description:
        return False
    return (
        SequenceMatcher(None, left_description, right_description).ratio()
        >= MIN_DUPLICATE_DESCRIPTION_SIMILARITY
    )


def suppress_duplicate_listings(jobs: dict[int, dict]) -> dict[int, dict]:
    """Keep one original provider listing per confidently matched cross-source posting."""
    retained = {}
    candidates = {}
    for job_id, job in jobs.items():
        title = _normalize_listing_text(job.get("title"))
        company = _normalize_listing_text(job.get("company"))
        if not title or not company:
            retained[job_id] = job
            continue

        identity = (title, company)
        peers = candidates.setdefault(identity, [])
        if any(_is_duplicate_listing(job, peer) for peer in peers):
            continue
        peers.append(job)
        retained[job_id] = job
    return retained


def build_job_recommendations(resume_id: int, user_id: int) -> dict:
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT user_id, extracted_text FROM resumes WHERE id = %s",
            (resume_id,),
        )
        resume = cursor.fetchone()
        if resume is None or resume["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="Resume not found.")

        # Read the skills extracted from this resume.
        cursor.execute(
            """
            SELECT s.id, s.name
            FROM resume_skills rs
            JOIN skills s ON s.id = rs.skill_id
            WHERE rs.resume_id = %s
            """,
            (resume_id,),
        )
        resume_skills = cursor.fetchall()
        resume_skill_names = {
            normalize_skill_name(skill["name"]) for skill in resume_skills
        }

        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'jobs'
              AND COLUMN_NAME = 'work_mode'
            """
        )
        work_mode_supported = cursor.fetchone()["column_count"] > 0
        work_mode_expression = (
            "j.work_mode" if work_mode_supported else "'unknown'"
        )

        jla_source_name = next(
            (
                source_name
                for source_name, settings in PROVIDER_USE_AUTHORIZATION.items()
                if settings.get("recommendations")
                == "JLA_RECOMMENDATIONS_AUTHORIZED"
            ),
            None,
        )
        jla_recommendations_authorized = (
            provider_use_authorized(jla_source_name, "recommendations")
            if jla_source_name is not None
            else False
        )
        description_expression = "j.description"
        skill_join_condition = ""
        job_query_params = ()
        if jla_source_name is not None and not jla_recommendations_authorized:
            # Return only NULL for unauthorized JLA descriptions, and do not
            # join its job_skills/skills rows into the result set at all.
            description_expression = (
                "CASE WHEN j.source_name = %s THEN NULL ELSE j.description END"
            )
            skill_join_condition = " AND j.source_name <> %s"
            job_query_params = (jla_source_name, jla_source_name)

        # Read each job and its required skills.
        job_query = f"""
            SELECT
                j.id AS job_id,
                j.title,
                j.company,
                j.location,
                {work_mode_expression} AS work_mode,
                {description_expression} AS description,
                j.source_url,
                j.source_name,
                s.id AS skill_id,
                s.name AS skill_name
            FROM jobs j
            LEFT JOIN job_skills js ON js.job_id = j.id{skill_join_condition}
            LEFT JOIN skills s ON s.id = js.skill_id
            WHERE j.status = 'open'
              AND (j.expires_at IS NULL OR j.expires_at > UTC_TIMESTAMP())
            ORDER BY j.id
            """
        if job_query_params:
            cursor.execute(job_query, job_query_params)
        else:
            cursor.execute(job_query)
        rows = cursor.fetchall()
        jobs = {}

        for row in rows:
            job_id = row["job_id"]
            if job_id not in jobs:
                recommendations_authorized = provider_use_authorized(
                    row["source_name"], "recommendations"
                )
                jobs[job_id] = {
                    "job_id": job_id,
                    "title": row["title"],
                    "company": row["company"],
                    "location": row["location"],
                    "work_mode": row.get("work_mode", "unknown"),
                    "description": (
                        row["description"] if recommendations_authorized else None
                    ),
                    "recommendations_authorized": recommendations_authorized,
                    "source_url": row["source_url"],
                    "source_name": row["source_name"],
                    "required_skills": [],
                    "matched_skills": [],
                    "missing_skills": [],
                }

            if not jobs[job_id]["recommendations_authorized"]:
                continue

            skill_name = row["skill_name"]
            if skill_name is not None:
                # Avoid duplicate requirements affecting the score.
                if normalize_skill_name(skill_name) not in {
                    normalize_skill_name(item)
                    for item in jobs[job_id]["required_skills"]
                }:
                    jobs[job_id]["required_skills"].append(skill_name)

        stored_job_count = len(jobs)
        excluded_sources = sorted(
            {
                job["source_name"]
                if isinstance(job["source_name"], str)
                else "Unspecified"
                for job in jobs.values()
                if not job["recommendations_authorized"]
            }
        )
        jobs = {
            job_id: job
            for job_id, job in jobs.items()
            if job["recommendations_authorized"]
        }
        for job in jobs.values():
            job.pop("recommendations_authorized", None)
        provider_eligible_job_count = len(jobs)
        jobs_without_description_data = sum(
            not isinstance(job["description"], str) or not job["description"].strip()
            for job in jobs.values()
        )
        jobs_without_skill_data = sum(
            not job["required_skills"] for job in jobs.values()
        )
        # Title fallback: when a job has no description and no linked skills,
        # extract skills from the title so it can still be matched.
        for job in jobs.values():
            has_desc = isinstance(job.get("description"), str) and job["description"].strip()
            if not job["required_skills"] and not has_desc and job.get("title"):
                title_skills = extract_skills(job["title"])
                if title_skills:
                    job["required_skills"] = title_skills
                    job["skills_from_title"] = True

        # Provider policy is checked before text enters the vectorizer. Listings
        # with either skills or descriptions can be scored; no-signal rows cannot.
        jobs = {
            job_id: job
            for job_id, job in jobs.items()
            if job["required_skills"]
            or (isinstance(job["description"], str) and job["description"].strip())
        }
        recommendation_candidate_count = len(jobs)
        jobs = suppress_duplicate_listings(jobs)
        suppressed_duplicate_count = recommendation_candidate_count - len(jobs)
        similarity_scores = calculate_tfidf_cosine_scores(
            resume.get("extracted_text"),
            [job.get("description") for job in jobs.values()],
        )
        for job, similarity in zip(jobs.values(), similarity_scores):
            job["content_similarity_score"] = round(similarity * 100, 2)
        jobs = {
            job_id: job
            for job_id, job in jobs.items()
            if any(
                skills_match(resume_skill_names, required_skill)
                for required_skill in job["required_skills"]
            )
            or job["content_similarity_score"] > 0
        }

        # Calculate coverage using normalized names and DSA equivalence.
        recommendations = []
        for job in jobs.values():
            for required_skill in job["required_skills"]:
                if skills_match(resume_skill_names, required_skill):
                    job["matched_skills"].append(required_skill)
                else:
                    job["missing_skills"].append(required_skill)

            total_required = len(job["required_skills"])
            matched_count = len(job["matched_skills"])
            skill_score = matched_count / total_required if total_required else None
            content_score = job["content_similarity_score"] / 100
            has_description = isinstance(job.get("description"), str) and bool(
                job["description"].strip()
            )
            if skill_score is not None and has_description:
                job["match_score"] = round((skill_score * 0.75 + content_score * 0.25) * 100, 2)
            elif skill_score is not None:
                job["match_score"] = round(skill_score * 100, 2)
            else:
                job["match_score"] = round(content_score * 100, 2)
            recommendations.append(job)

        recommendations.sort(key=lambda job: job["match_score"], reverse=True)

        # Persist scores in the existing table/column; update duplicate pairs.
        for job in recommendations:
            cursor.execute(
                """
                INSERT INTO recommendations (resume_id, job_id, match_score)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    match_score = VALUES(match_score),
                    created_at = CURRENT_TIMESTAMP
                """,
                (resume_id, job["job_id"], job["match_score"]),
            )

        connection.commit()
        if recommendations:
            availability_status = "available"
        elif stored_job_count:
            availability_status = (
                "provider_authorization_required"
                if not provider_eligible_job_count
                else "no_relevant_matches"
                if recommendation_candidate_count
                else "job_skill_data_unavailable"
            )
        else:
            availability_status = "no_jobs_available"
        return {
            "resume_id": resume_id,
            "resume_skills": [skill["name"] for skill in resume_skills],
            "total_jobs": len(recommendations),
            "availability": {
                "status": availability_status,
                "stored_job_count": stored_job_count,
                "provider_eligible_job_count": provider_eligible_job_count,
                "recommendation_count": len(recommendations),
                "jobs_without_skill_data": jobs_without_skill_data,
                "jobs_without_description_data": jobs_without_description_data,
                "excluded_job_count": (
                    stored_job_count - provider_eligible_job_count
                ),
                "excluded_sources": excluded_sources,
                "suppressed_duplicate_count": suppressed_duplicate_count,
            },
            "recommendations": recommendations,
        }
    except HTTPException:
        connection.rollback()
        raise
    except Exception as error:
        connection.rollback()
        logger.error("Recommendation failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate job recommendations.",
        )
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()