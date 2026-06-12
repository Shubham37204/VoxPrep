from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse