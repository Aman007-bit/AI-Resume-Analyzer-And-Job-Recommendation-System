from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from auth import create_access_token, get_current_user, validate_auth_configuration
from services.auth_service import authenticate_user, register_user, reset_password

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class RegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegistrationRequest):
    validate_auth_configuration()
    user = register_user(payload.name, str(payload.email), payload.password)
    return {
        "access_token": create_access_token(user["id"]),
        "user": user,
    }


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    user = authenticate_user(str(payload.email), payload.password)
    return {
        "access_token": create_access_token(user["id"]),
        "user": user,
    }


@router.post("/reset-password")
def reset_password_route(payload: ResetPasswordRequest):
    reset_password(str(payload.email), payload.new_password)
    return {"message": "Password updated successfully."}


@router.get("/me", response_model=UserResponse)
def current_user(
    user: Annotated[dict, Depends(get_current_user)],
):
    return user