import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth_service import get_user_by_id

logger = logging.getLogger(__name__)
TOKEN_ISSUER = "ai-resume-analyzer"
bearer_scheme = HTTPBearer(auto_error=False)


def _token_settings() -> tuple[str, int]:
    secret = os.getenv("JWT_SECRET_KEY", "")
    try:
        expires_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    except ValueError:
        expires_minutes = 0

    if len(secret.encode("utf-8")) < 32 or not 1 <= expires_minutes <= 1440:
        logger.error("JWT authentication configuration is invalid")
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured.",
        )

    return secret, expires_minutes


def validate_auth_configuration() -> None:
    """Validate signing settings before any account persistence."""
    _token_settings()


def create_access_token(user_id: int) -> str:
    secret, expires_minutes = _token_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret, _ = _token_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            issuer=TOKEN_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        user_id = int(payload["sub"])
        if user_id < 1:
            raise ValueError("Invalid subject")
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
