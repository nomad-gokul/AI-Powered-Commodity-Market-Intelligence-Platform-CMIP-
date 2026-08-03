"""Request/response DTOs for the auth module."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    roles: list[RoleRead]


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=256)
    # Minimum length only here at the input boundary; bcrypt work factor is
    # the actual brute-force defense, this just rejects trivially weak input.
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AssignRoleRequest(BaseModel):
    role_id: uuid.UUID
