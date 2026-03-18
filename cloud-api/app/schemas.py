from datetime import datetime
import re
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    if not _EMAIL_REGEX.fullmatch(value):
        raise ValueError("Invalid email format")
    return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _login_email(cls, value: str) -> str:
        return _validate_email(value)


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    is_admin: bool
    created_at: datetime

    @field_validator("email")
    @classmethod
    def _user_email(cls, value: str) -> str:
        return _validate_email(value)


class CreatedUserResponse(BaseModel):
    id: int
    email: EmailStr
    is_admin: bool = False


class LayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    uri: str | None = None
    description: str | None = None
    group_name: str | None = None
    epsg: int | None = None
    schema: str | None = None
    srid: int | None = None
    geom_type: str | None = None
    created_at: datetime
    created_by_user_id: int | None = None
