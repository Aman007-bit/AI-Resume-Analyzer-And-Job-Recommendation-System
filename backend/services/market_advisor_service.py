"""Local market insights based only on jobs already stored in the database.

No external APIs, no scraping, no schema changes.
"""
import logging
from collections import Counter
from datetime import datetime, timezone

from fastapi import HTTPException
from db import get_db_connection
from services.recommendation_service import (
    build_job_recommendations,
    normalize_skill_name,
    skills_match,
)

logger = logging.getLogger(__name__)

# Static free learning links (dated). Update when resources change.
FREE_LEARNING_LINKS = {
    "python": "https://docs.python.org/3/tutorial/",
    "sql": "https://www.w3schools.com/sql/",
    "react": "https://react.dev/learn",
    "javascript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
    "fastapi": "https://fastapi.tiangolo.com/tutorial/",
    "docker": "https://docs.docker.com/get-started/",
    "git": "https://git-scm.com/doc",
    "aws": "https://aws.amazon.com/getting-started/",
    "machine learning": "https://scikit-learn.org/stable/tutorial/index.html",
    "data analysis": "https://pandas.pydata.org/docs/user_guide/index.html",
}

DEFAULT_LEARNING_LINK = "https://www.freecodecamp.org/"


def _learning_link(skill_name: str) -> str:
    key = normalize_skill_name(skill_name)
    return FREE_LEARNING_LINKS.get(key, DEFAULT_LEARNING_LINK)


def get_market_insights(resume_id: int, user_id: int) -> dict:
    """Rank missing skills by how many additional recommended jobs they unlock."""
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    try:
        # Reuse existing recommendation engine (does not modify it).
        rec_result = build_job_recommendations(resume_id, user_id)
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Market insights failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate market insights.",
        ) from error

    recommendations = rec_result.get("recommendations") or []
    resume_skills = {
        normalize_skill_name(s) for s in (rec_result.get("resume_skills") or [])
    }

    # Count how many recommended jobs require each missing skill.
    missing_counter = Counter()
    for job in recommendations:
        for skill in job.get("missing_skills") or []:
            missing_counter[skill] += 1

    ranked = []
    for skill, job_count in missing_counter.most_common(10):
        ranked.append({
            "skill": skill,
            "jobs_requiring": job_count,
            "coverage_improvement": job_count,
            "learning_link": _learning_link(skill),
        })

    total_relevant = len(recommendations)
    current_matched_jobs = sum(
        1 for job in recommendations if job.get("matched_skills")
    )

    return {
        "resume_id": resume_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "jobs currently stored in your database",
        "total_relevant_jobs": total_relevant,
        "jobs_with_at_least_one_match": current_matched_jobs,
        "top_missing_skills": ranked,
        "note": (
            "Coverage numbers are estimates based on skills already linked "
            "to jobs in the local database. Adding a skill does not guarantee "
            "eligibility (education, experience, location, and other criteria "
            "still apply)."
        ),
    }