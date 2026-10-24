
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth import get_current_user
from services.resume_service import process_resume_upload
from services.recommendation_service import build_job_recommendations

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


@router.post("/api/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed."
            )

        if file.size == 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty."
            )

        if file.size is not None and file.size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="PDF size must not exceed 10 MB."
            )

        filename = file.filename
        # Read at most one byte past the limit so oversized uploads are bounded.
        contents = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty."
            )

        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="PDF size must not exceed 10 MB."
            )

        if not contents.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is not a valid PDF."
            )

        # Step 1: Extract profile and skills, then save the resume.
        upload_result = process_resume_upload(
            user_id=current_user["id"],
            filename=filename,
            contents=contents
        )

        resume_id = upload_result.get("resume_id")

        if resume_id is None:
            raise HTTPException(
                status_code=500,
                detail="Resume was processed, but no resume ID was returned."
            )

        # Step 2: Generate recommendations after the resume transaction commits.
        try:
            recommendation_result = build_job_recommendations(
                resume_id, current_user["id"]
            )
            availability = (
                recommendation_result.get("availability")
                if isinstance(recommendation_result, dict)
                else None
            )
            if isinstance(availability, dict):
                availability_status = availability.get("status")
                if isinstance(availability_status, str):
                    upload_result["recommendation_status"] = availability_status
                    if availability_status == "provider_authorization_required":
                        upload_result["recommendations_generated"] = False
                        upload_result["recommendation_error"] = (
                            "Job listings are stored, but recommendations are "
                            "disabled while provider data-use authorization "
                            "is pending."
                        )
                        return upload_result
            upload_result["recommendations_generated"] = True

        except Exception as exc:
            logger.error(
                "Recommendation generation failed after resume upload (%s)",
                type(exc).__name__,
            )
            upload_result["recommendations_generated"] = False
            upload_result["recommendation_error"] = (
                "Could not generate recommendations right now."
            )

        return upload_result
    finally:
        await file.close()
