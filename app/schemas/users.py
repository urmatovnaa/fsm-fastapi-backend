from pydantic import BaseModel, ConfigDict, EmailStr, model_validator


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str
    password_confirmation: str
    is_admin: bool = False

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "UserCreate":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(BaseModel):
    """Пользователь с вычисленной ролью (для админского листинга)."""

    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    is_admin: bool = False
    worker_id: int | None = None
    role: str = "user"

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def resolve_role(self) -> "AdminUserResponse":
        if self.is_admin:
            self.role = "admin"
        elif self.worker_id is not None:
            self.role = "worker"
        else:
            self.role = "user"
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"