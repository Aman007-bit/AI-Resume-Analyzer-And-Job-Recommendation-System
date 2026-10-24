import traceback
from fastapi import APIRouter, Query, HTTPException
from db import get_db_connection

router = APIRouter()

CATEGORY_KEYWORDS = {
    "tech": [
        "python", "java", "javascript", "react", "node", "aws", "docker",
        "sql", "backend", "frontend", "developer", "engineer", "software",
        "golang", "kubernetes", "devops", "machine learning", "data"
    ],
    "business": [
        "sales", "marketing", "finance", "hr", "product manager", "manager",
        "business", "analyst", "consultant", "operations"
    ],
    "design": [
        "design", "ui", "ux", "figma", "graphic", "designer"
    ],
    "marketing": [
        "marketing", "seo", "content", "social media", "growth"
    ],
}

def _classify(title: str, skills: list) -> str:
    text = (title or "").lower() + " " + " ".join(skills or []).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "other"

@router.get("/api/jobs")
def list_all_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str = Query(None),
    location: str = Query(None),
    work_mode: str = Query(None),
    search: str = Query(None),
):
    print("=== /api/jobs HIT ===")
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    offset = (page - 1) * limit
    where = ["1=1", "status = 'open'"]
    params = []

    if search:
        where.append("(title LIKE %s OR company LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if location:
        where.append("location LIKE %s")
        params.append(f"%{location}%")
    if work_mode:
        where.append("work_mode = %s")
        params.append(work_mode)

    where_sql = " AND ".join(where)

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            f"SELECT COUNT(*) AS total FROM jobs WHERE {where_sql}",
            params,
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT j.id, j.title, j.company, j.location, j.work_mode,
                   j.description, j.source_url, j.source_name
            FROM jobs j
            WHERE {where_sql}
            ORDER BY j.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cursor.fetchall()

        job_ids = [r["id"] for r in rows]
        skills_map = {}
        if job_ids:
            placeholders = ",".join(["%s"] * len(job_ids))
            cursor.execute(
                f"""
                SELECT js.job_id, s.name
                FROM job_skills js
                JOIN skills s ON s.id = js.skill_id
                WHERE js.job_id IN ({placeholders})
                """,
                job_ids,
            )
            for row in cursor.fetchall():
                skills_map.setdefault(row["job_id"], []).append(row["name"])

        jobs = []
        for row in rows:
            skills = skills_map.get(row["id"], [])
            cat = _classify(row["title"], skills)
            if category and category != "all" and cat != category:
                continue
            jobs.append({
                "id": row["id"],
                "title": row["title"],
                "company": row["company"],
                "location": row["location"],
                "work_mode": row["work_mode"],
                "description": row["description"],
                "source_url": row["source_url"],
                "source_name": row["source_name"],
                "skills": skills,
                "category": cat,
            })

        return {
            "jobs": jobs,
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        connection.close()


@router.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT j.id, j.title, j.company, j.location, j.work_mode,
                   j.description, j.source_url, j.source_name
                        FROM jobs j
                        WHERE j.id = %s AND j.status = 'open'
                        """,
                        (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        cursor.execute(
            """
            SELECT s.name
            FROM job_skills js
            JOIN skills s ON s.id = js.skill_id
            WHERE js.job_id = %s
            """,
            (job_id,),
        )
        skills = [row["name"] for row in cursor.fetchall()]
        job["skills"] = skills
        return job
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        connection.close()