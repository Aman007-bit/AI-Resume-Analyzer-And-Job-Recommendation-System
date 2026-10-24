from io import BytesIO
import logging
import re

from fastapi import HTTPException
from pypdf import PdfReader

from db import get_db_connection

logger = logging.getLogger(__name__)


# Keep longer/more specific skills before their shorter aliases.
SKILL_KEYWORDS = [
    "Data Structures and Algorithms",
    "Natural Language Processing",
    "Object-Oriented Programming",
    "Problem Solving",
    "Consultative Selling",
    "Customer Engagement",
    "Business Development",
    "Communication",
    "Time Management",
    "Organizational Skills",
    "Machine Learning",
    "Deep Learning",
    "Scikit-learn",
    "JavaScript",
    "TypeScript",
    "Salesforce",
    "PowerPoint",
    "Microsoft Word",
    "PostgreSQL",
    "Express.js",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "REST API",
    "GitHub",
    "Kubernetes",
    "TensorFlow",
    "PyTorch",
    "Data Analysis",
    "Power BI",
    "Data Structures",
    "Algorithms",
    "Python",
    "Java",
    "C++",
    "C#",
    "C",
    "SQL",
    "MySQL",
    "HTML",
    "CSS",
    "React",
    "Git",
    "Docker",
    "AWS",
    "Azure",
    "NLP",
    "Pandas",
    "NumPy",
    "OOP",
    "Excel",
    "Tableau",
    "Vue.js",
    "Vue",
    "Angular",
    "PHP",
    "GCP",
    "Google Cloud",
    "MongoDB",
    "Redis",
    "GraphQL",
    "Next.js",
    "Spring",
    "Spring Boot",
    "Laravel",
    "Ruby",
    "Ruby on Rails",
    "Go",
    "Golang",
    "Rust",
    "Kotlin",
    "Swift",
    "Flutter",
    "React Native",
    "Terraform",
    "Jenkins",
    "CI/CD",
    "Linux",
    "Bash",
    "Selenium",
    "Cypress",
    "Jest",
    "Webpack",
    "Sass",
    "Tailwind",
    "Bootstrap",
    "Figma",
    "Jira",
    "Agile",
    "Scrum",
    "Microservices",
    "REST",
    "GraphQL",
    "Kafka",
    "Spark",
    "Hadoop",
    "Snowflake",
    "BigQuery",
    "Firebase",
    "Supabase",
]


COMBINED_SKILL_PATTERNS = {
    "Data Structures and Algorithms": (
        r"\bdata\s+structures\s*(?:and|&)\s*algorithms\b"
    ),
    "Natural Language Processing": r"\bnatural\s+language\s+processing\b",
}

SKILL_PATTERNS = {
    "Microsoft Word": r"(?<!\w)(?:microsoft\s+word|ms[-\s]?word)(?!\w)",
    "Time Management": r"(?<!\w)time[-\s]+management(?!\w)",
}


def extract_skills(text: str) -> list[str]:
    """Extract unique skills and avoid counting known combined terms twice."""
    normalized_text = text.lower()
    normalized_text = re.sub(r"[\u2010-\u2015\u2212]", "-", normalized_text)
    normalized_text = re.sub(r"\s+", " ", normalized_text)
    found_skills = []

    for skill, pattern in COMBINED_SKILL_PATTERNS.items():
        if re.search(pattern, normalized_text, re.IGNORECASE):
            found_skills.append(skill)

    excluded_components = set()
    if "Data Structures and Algorithms" in found_skills:
        excluded_components.update({"Data Structures", "Algorithms"})
    if "Natural Language Processing" in found_skills:
        excluded_components.add("NLP")

    for skill in SKILL_KEYWORDS:
        if skill in excluded_components or skill in found_skills:
            continue

        # Do not add a short alias when its full skill name was already found.
        if skill == "NLP" and "Natural Language Processing" in found_skills:
            continue

        pattern = SKILL_PATTERNS.get(
            skill,
            r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)",
        )
        if re.search(pattern, normalized_text):
            found_skills.append(skill)

    return list(dict.fromkeys(found_skills))


def extract_profile_details(text: str) -> dict:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    email_match = re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text
    )
    phone_match = re.search(
        r"(?<!\w)(?:\+?91[\s.-]?)?[6-9]\d{9}(?!\w)", text
    )

    email = email_match.group(0) if email_match else None
    phone = phone_match.group(0) if phone_match else None
    name = None

    name_labels = re.compile(
        r"^(?:full\s+name|candidate\s+name|name)\s*:\s*(.+)$",
        re.IGNORECASE,
    )

    section_headings = {
        "summary", "profile", "objective", "experience", "work experience",
        "skills", "technical skills", "projects", "certifications",
        "achievements", "achievements & activities", "education",
        "educational qualifications", "academic qualifications",
    }

    for line in lines[:10]:
        label_match = name_labels.match(line)
        if label_match:
            name = label_match.group(1).strip()
            break

        if (
            re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,79}", line)
            and line.lower().rstrip(":") not in section_headings
            and not re.search(r"@", line)
            and not re.search(r"\d", line)
        ):
            name = line
            break

    education_lines = []
    in_education_section = False

    for line in lines:
        heading = line.strip().rstrip(":").lower()
        if heading in section_headings:
            in_education_section = heading in {
                "education", "educational qualifications", "academic qualifications"
            }
            continue
        if in_education_section:
            education_lines.append(line)

    education_text = "\n".join(education_lines)
    education_text = re.sub(r"(\d\.\d{1,2})(20\d{2})", r"\1 \2", education_text)
    education_text = re.sub(r"(%)(20\d{2})", r"\1 \2", education_text)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "education": education_text.strip() or None,
    }


def process_resume_upload(user_id: int, filename: str, contents: bytes) -> dict:
    try:
        reader = PdfReader(BytesIO(contents))
        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDFs are not supported.",
            )
        extracted_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
    except HTTPException:
        raise
    except Exception as error:
        logger.error("PDF parsing failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=400,
            detail="Could not read the PDF. Please upload a valid PDF.",
        )

    if not extracted_text:
        raise HTTPException(
            status_code=422,
            detail=(
                "No readable text found in the PDF. Scanned PDFs require "
                "OCR, which is not implemented yet."
            ),
        )

    try:
        matched_skills = extract_skills(extracted_text)
        profile = extract_profile_details(extracted_text)
    except Exception as error:
        logger.error("Resume text analysis failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to extract resume details.",
        )

    connection = get_db_connection()

    if connection is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail="User not found. Create a user before uploading.",
            )

        cursor.execute(
            """
            INSERT INTO resumes (
                user_id, file_name, extracted_text, status,
                extracted_name, extracted_email, extracted_phone, extracted_education
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, filename, extracted_text, "completed", profile["name"],
                profile["email"], profile["phone"], profile["education"],
            ),
        )
        resume_id = cursor.lastrowid

        for skill in matched_skills:
            cursor.execute(
                """
                INSERT INTO skills (name)
                VALUES (%s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
                """,
                (skill,),
            )
            skill_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT IGNORE INTO resume_skills (resume_id, skill_id)
                VALUES (%s, %s)
                """,
                (resume_id, skill_id),
            )

        connection.commit()
        return {
            "message": "Resume uploaded and analyzed successfully.",
            "resume_id": resume_id,
            "user_id": user_id,
            "file_name": filename,
            "status": "completed",
            "pages": len(reader.pages),
            "text_length": len(extracted_text),
            "profile": profile,
            "skills_found": matched_skills,
            "skills_count": len(matched_skills),
        }
    except HTTPException:
        connection.rollback()
        raise
    except Exception as error:
        connection.rollback()
        logger.error("Resume processing failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to save resume and extracted details.",
        )
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()