import json
from dotenv import load_dotenv

load_dotenv(".env")
# load_dotenv(".env.staging", override=True)  # staging band

from services.job_ingestion_service import (
    synchronize_job_listings_api_only,
)

result = synchronize_job_listings_api_only()
print(json.dumps(result, indent=2, default=str))

if result.get("status") not in {"succeeded", "partial"}:
    raise SystemExit(1)