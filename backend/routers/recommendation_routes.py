from fastapi import APIRouter, Depends

from auth import get_current_user
from services.recommendation_service import build_job_recommendations
from services.market_advisor_service import get_market_insights

router = APIRouter()


@router.get("/api/recommendations/{resume_id}")
def get_job_recommendations(resume_id: int, current_user: dict = Depends(get_current_user)):
    return build_job_recommendations(resume_id, current_user["id"])


@router.get("/api/recommendations/{resume_id}/market-insights")
def get_market_insights_endpoint(
    resume_id: int, current_user: dict = Depends(get_current_user)
):
    return get_market_insights(resume_id, current_user["id"])