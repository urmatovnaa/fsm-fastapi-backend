from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Проверяет пароль против сохранённого хеша."""
    if not hashed_password:
        return False
    return pwd_context.verify(password, hashed_password)


def create_access_token(user_id: int, role: str) -> str:
    """Формирует JWT с user_id, role и exp."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Декодирует JWT. Бросает JWTError при невалидном токене."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "JWTError",
]