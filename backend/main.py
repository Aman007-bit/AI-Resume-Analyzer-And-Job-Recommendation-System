import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import get_db_connection
from routers.auth_routes import router as auth_router
from routers.job_ingestion_routes import router as job_ingestion_router
from routers.resume_routes import router as resume_router
from routers.recommendation_routes import router as recommendation_router
from routers.job_routes import router as job_router


logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Resume Analyzer API",
    description="Backend for resume analysis and job recommendations",
    version="1.0.0"
)

# Allow the Vite React frontend to communicate with FastAPI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(resume_router)
app.include_router(recommendation_router)
app.include_router(auth_router)
app.include_router(job_ingestion_router)
app.include_router(job_router)


@app.get("/")
def home():
    return {"message": "AI Resume Analyzer API is running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/health/database")
def database_health_check():
    """DB reachability probe. Never returns credentials, SQL, or exception text."""
    connection = get_db_connection()

    if connection is None:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "detail": "Database connection failed.",
        }

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
        database_name = row[0] if row else None
        return {
            "status": "healthy",
            "database": "connected",
            "database_name": database_name or "unknown",
        }
    except Exception as error:
        # Log exception type only — never str(error) (may contain DSN fragments).
        logger.warning("Database health query failed (%s)", type(error).__name__)
        return {
            "status": "unhealthy",
            "database": "query_failed",
            "detail": "Database health check failed.",
        }
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                logger.warning("Database health cursor close failed")
        try:
            connection.close()
        except Exception:
            logger.warning("Database health connection close failed")