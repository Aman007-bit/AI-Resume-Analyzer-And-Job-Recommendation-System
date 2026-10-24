
from io import BytesIO
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pypdf import PdfReader

from db import get_db_connection

app = FastAPI(
    title="AI Resume Analyzer API",
    description="Backend for resume analysis and job recommendations",
    version="1.0.0",
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

SKILL_KEYWORDS = [
    "Python", "Java", "JavaScript", "TypeScript", "C", "C++", "C#",
    "SQL", "MySQL", "PostgreSQL", "HTML", "CSS", "React", "Node.js",
    "Express.js", "FastAPI", "Django", "Flask", "REST API", "Git",
    "GitHub", "Docker", "Kubernetes", "AWS", "Azure", "Machine Learning",
    "Deep Learning", "Natural Language Processing", "NLP", "Scikit-learn",
    "TensorFlow", "PyTorch", "Pandas", "NumPy", "Data Analysis",
    "Data Structures", "Algorithms", "OOP",
    "Object-Oriented Programming", "Problem Solving", "Excel",
    "Power BI", "Tableau",
]


def extract_skills(text: str) -> list[str]:
    found_skills = []
    normalized_text = text.lower()

    for skill in SKILL_KEYWORDS:
        pattern = r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)"

        if re.search(pattern, normalized_text):
            found_skills.append(skill)

    return found_skills




def extract_profile_details(text: str) -> dict:
    # Normalize whitespace while preserving line boundaries.
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Extract email and phone.
    email_match = re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        text
    )
    phone_match = re.search(
        r"(?<!\w)(?:\+?91[\s.-]?)?[6-9]\d{9}(?!\w)",
        text
    )

    email = email_match.group(0) if email_match else None
    phone = phone_match.group(0) if phone_match else None

    # Extract name from a labelled field or the resume header.
    name = None
    name_labels = re.compile(
        r"^(?:full\s+name|candidate\s+name|name)\s*:\s*(.+)$",
        re.IGNORECASE
    )

    section_headings = {
        "summary", "profile", "objective",
        "experience", "work experience",
        "skills", "technical skills",
        "projects", "certifications",
        "achievements", "achievements & activities",
        "education", "educational qualifications",
        "academic qualifications",
    }

    for line in lines[:10]:
        label_match = name_labels.match(line)
        if label_match:
            name = label_match.group(1).strip()
            break

        # The first standalone header line is usually the candidate's name.
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,79}", line)
            and line.lower().rstrip(":") not in section_headings
            and not re.search(r"@", line)
            and not re.search(r"\d", line)
        ):
            name = line
            break

    # Extract only the Education section.
    education_lines = []
    in_education_section = False

    for line in lines:
        heading = line.strip().rstrip(":").lower()

        if heading in section_headings:
            in_education_section = heading in {
                "education",
                "educational qualifications",
                "academic qualifications",
            }
            continue

        if in_education_section:
            education_lines.append(line)

    # Repair common PDF spacing issues in education entries.
    education_text = "\n".join(education_lines)

    # Example: CGPA: 7.832023 – 2027 -> CGPA: 7.83 2023 – 2027
    education_text = re.sub(
        r"(\d\.\d{1,2})(20\d{2})",
        r"\1 \2",
        education_text
    )

    # Example: Percentage: 82%2020 – 2021 -> Percentage: 82% 2020 – 2021
    education_text = re.sub(
        r"(%)(20\d{2})",
        r"\1 \2",
        education_text
    )

    education = education_text.strip() or None

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "education": education,
    }



@app.get("/")
def home():
    return {
        "message": "AI Resume Analyzer API is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@app.get("/health/database")
def database_health_check():
    connection = get_db_connection()

    if connection is None:
        return {
            "status": "unhealthy",
            "database": "disconnected"
        }

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE()")
        database_name = cursor.fetchone()[0]
        cursor.close()

        return {
            "status": "healthy",
            "database": "connected",
            "database_name": database_name
        }

    except Exception as error:
        print(f"Database query failed: {error}")
        return {
            "status": "unhealthy",
            "database": "query_failed"
        }

    finally:
        connection.close()


@app.post("/api/resumes/upload")
async def upload_resume(
    user_id: int = Form(...),
    file: UploadFile = File(...)
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    contents = await file.read()

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty."
        )

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF size must not exceed 10 MB."
        )

    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF."
        )

    try:
        reader = PdfReader(BytesIO(contents))

        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDFs are not supported."
            )

        extracted_text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        ).strip()

        print("===== EXTRACTED RESUME TEXT =====")
        print(extracted_text)
        print("===== END OF RESUME TEXT =====")

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read the PDF. Please upload a valid PDF."
        )
    finally:
        await file.close()

    if not extracted_text:

        raise HTTPException(
            status_code=422,
            detail=(
                "No readable text found in the PDF. "
                "Scanned PDFs require OCR, which is not implemented yet."
            )
        )

    matched_skills = extract_skills(extracted_text)
    profile = extract_profile_details(extracted_text)

    connection = get_db_connection()

    if connection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed."
        )

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT id FROM users WHERE id = %s",
            (user_id,)
        )

        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail="User not found. Create a user before uploading."
            )

        cursor.execute(
            """
            INSERT INTO resumes (
                user_id,
                file_name,
                extracted_text,
                status,
                extracted_name,
                extracted_email,
                extracted_phone,
                extracted_education
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                file.filename,
                extracted_text,
                "completed",
                profile["name"],
                profile["email"],
                profile["phone"],
                profile["education"],
            )
        )

        resume_id = cursor.lastrowid

        for skill in matched_skills:
            cursor.execute(
                """
                INSERT INTO skills (name)
                VALUES (%s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
                """,
                (skill,)
            )

            skill_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT IGNORE INTO resume_skills (resume_id, skill_id)
                VALUES (%s, %s)
                """,
                (resume_id, skill_id)
            )

        connection.commit()

        return {
            "message": "Resume uploaded and analyzed successfully.",
            "resume_id": resume_id,
            "user_id": user_id,
            "file_name": file.filename,
            "status": "completed",
            "pages": len(reader.pages),
            "text_length": len(extracted_text),
            "profile": {
                "name": profile["name"],
                "email": profile["email"],
                "phone": profile["phone"],
                "education": profile["education"],
            },
            "skills_found": matched_skills,
            "skills_count": len(matched_skills),
        }

    except HTTPException:
        connection.rollback()
        raise

    except Exception as error:
        connection.rollback()
        print(f"Resume processing failed: {error}")

        raise HTTPException(
            status_code=500,
            detail="Failed to save resume and extracted details."
        )

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()
@app.get("/api/recommendations/{resume_id}")
def get_job_recommendations(resume_id: int):
    connection = get_db_connection()

    if connection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed."
        )

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # Verify that the resume exists.
        cursor.execute(
            "SELECT id FROM resumes WHERE id = %s",
            (resume_id,)
        )
        resume = cursor.fetchone()

        if resume is None:
            raise HTTPException(
                status_code=404,
                detail="Resume not found."
            )

        # Fetch skills detected for this resume.
        cursor.execute(
            """
            SELECT s.id, s.name
            FROM resume_skills rs
            JOIN skills s ON s.id = rs.skill_id
            WHERE rs.resume_id = %s
            """,
            (resume_id,)
        )
        resume_skills = cursor.fetchall()
        resume_skill_ids = {skill["id"] for skill in resume_skills}

        # Fetch all jobs and their required skills.
        cursor.execute(
            """
            SELECT
                j.id AS job_id,
                j.title,
                j.company,
                j.location,
                j.description,
                j.source_url,
                s.id AS skill_id,
                s.name AS skill_name
            FROM jobs j
            LEFT JOIN job_skills js ON js.job_id = j.id
            LEFT JOIN skills s ON s.id = js.skill_id
            ORDER BY j.id
            """
        )
        rows = cursor.fetchall()

        jobs = {}

        for row in rows:
            job_id = row["job_id"]

            if job_id not in jobs:
                jobs[job_id] = {
                    "job_id": job_id,
                    "title": row["title"],
                    "company": row["company"],
                    "location": row["location"],
                    "description": row["description"],
                    "source_url": row["source_url"],
                    "required_skills": [],
                    "matched_skills": [],
                    "missing_skills": []
                }

            if row["skill_id"] is not None:
                skill_name = row["skill_name"]
                jobs[job_id]["required_skills"].append(skill_name)

                if row["skill_id"] in resume_skill_ids:
                    jobs[job_id]["matched_skills"].append(skill_name)
                else:
                    jobs[job_id]["missing_skills"].append(skill_name)

        recommendations = []

        for job in jobs.values():
            total_required = len(job["required_skills"])
            matched_count = len(job["matched_skills"])

            match_score = (
                round(matched_count / total_required * 100, 2)
                if total_required > 0
                else 0.0
            )

            job["match_score"] = match_score
            recommendations.append(job)

        recommendations.sort(
            key=lambda job: job["match_score"],
            reverse=True
        )

        return {
            "resume_id": resume_id,
            "resume_skills": [s["name"] for s in resume_skills],
            "total_jobs": len(recommendations),
            "recommendations": recommendations
        }

    except HTTPException:
        raise

    except Exception as error:
        print(f"Recommendation failed: {error}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate job recommendations."
        )

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()