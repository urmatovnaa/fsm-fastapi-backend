from pydantic import BaseModel, ConfigDict, EmailStr


class RoleResponse(BaseModel):
    id: int
    name: str
    rights: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str
    role: str = "USER"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role_id: int | None = None
    role: RoleResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"