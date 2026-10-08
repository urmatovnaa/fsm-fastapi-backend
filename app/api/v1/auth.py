from fastapi import APIRouter, HTTPException, status

from app.schemas.users import UserCreate, UserLogin, UserResponse, TokenResponse
from app.services import users as user_service
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate):
    existing = await user_service.get_user_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    # TODO: хеширование (сейчас заглушка)
    _ = hash_password(payload.password)

    user = await user_service.create_user(
        username=payload.username,
        password=payload.password,
    )
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    user = await user_service.get_user_by_username(payload.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # TODO: verify_password(payload.password, user.hashed_password)
    token = create_access_token(user_id=user.id, role=user.role.value)
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def me(user_id: int = 1):
    """Заглушка: вернёт пользователя по id (пока без JWT-зависимости)."""
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
    )