from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.constants import RoleNames
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.users import User
from app.schemas.users import TokenResponse, UserCreate, UserLogin, UserResponse
from app.services import users as user_service
from app.services.users import RoleNotFound, UserAlreadyExists

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, session: AsyncSession = Depends(get_db)):
    role_name = (payload.role or RoleNames.USER).upper()
    if role_name not in RoleNames.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role: {payload.role}",
        )

    try:
        user = await user_service.create_user(
            session,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            phone=payload.phone,
            role_name=role_name,
        )
    except UserAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    except RoleNotFound:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{role_name}' not found. Run seed.",
        )

    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, session: AsyncSession = Depends(get_db)):
    user = await user_service.get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    role_name = user.role.name if user.role else RoleNames.USER
    token = create_access_token(user_id=user.id, role=role_name)
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user