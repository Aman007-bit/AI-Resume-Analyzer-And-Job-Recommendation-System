import os


PROVIDER_USE_AUTHORIZATION = {
    "The Muse": {
        "ingestion": "THE_MUSE_INGESTION_AUTHORIZED",
        "recommendations": "THE_MUSE_RECOMMENDATIONS_AUTHORIZED",
    },
    "Arbeitnow": {
        "ingestion": "ARBEITNOW_INGESTION_AUTHORIZED",
        "recommendations": "ARBEITNOW_RECOMMENDATIONS_AUTHORIZED",
    },
    "Lever": {
        "ingestion": "LEVER_INGESTION_AUTHORIZED",
        "recommendations": "LEVER_RECOMMENDATIONS_AUTHORIZED",
    },
    "Greenhouse": {
        "ingestion": "GREENHOUSE_INGESTION_AUTHORIZED",
        "recommendations": "GREENHOUSE_RECOMMENDATIONS_AUTHORIZED",
    },
    "Jobicy": {
        "ingestion": "JOBICY_INGESTION_AUTHORIZED",
        "recommendations": "JOBICY_RECOMMENDATIONS_AUTHORIZED",
    },
    "Job Listings API": {
        "ingestion": "JLA_INGESTION_AUTHORIZED",
        "recommendations": "JLA_RECOMMENDATIONS_AUTHORIZED",
    },
}


def provider_use_authorized(source_name, use):
    if use not in {"ingestion", "recommendations"}:
        return False
    if source_name == "Remotive":
        return False
    if source_name == "USAJOBS":
        return True
    settings = PROVIDER_USE_AUTHORIZATION.get(source_name)
    setting = settings.get(use) if settings else None
    return setting is not None and os.getenv(setting, "").strip().lower() == "true"
