from fastapi import APIRouter, Depends

from auth import get_current_user
from services.job_ingestion_service import (
    get_job_dataset_diagnostics,
    require_job_sync_admin,
    synchronize_configured_sources,
)

router = APIRouter()


@router.post("/api/admin/jobs/sync")
def sync_jobs(current_user: dict = Depends(get_current_user)):
    require_job_sync_admin(current_user)
    return synchronize_configured_sources()


@router.get("/api/admin/jobs/diagnostics")
def get_job_diagnostics(current_user: dict = Depends(get_current_user)):
    require_job_sync_admin(current_user)
    return get_job_dataset_diagnostics()
