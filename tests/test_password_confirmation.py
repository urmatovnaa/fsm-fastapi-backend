"""Unit-тесты валидации password_confirmation в схеме регистрации.

Не требуют БД: проверяют request-схему UserCreate напрямую.
"""
import pytest
from pydantic import ValidationError

from app.schemas.users import UserCreate, UserResponse


def test_passwords_match_ok():
    payload = UserCreate(
        full_name="Ivan Client",
        email="ivan@example.com",
        password="secret123",
        password_confirmation="secret123",
    )
    assert payload.password == "secret123"
    # password_confirmation — только входное поле и не должно попадать в ответ
    # (а значит и в БД), в отличие от него.
    assert "password_confirmation" not in UserResponse.model_fields
    assert "password" not in UserResponse.model_fields


def test_passwords_mismatch_raises():
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(
            full_name="Ivan Client",
            email="ivan@example.com",
            password="secret123",
            password_confirmation="different",
        )
    assert "match" in str(exc_info.value).lower()


def test_password_confirmation_required():
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(
            full_name="Ivan Client",
            email="ivan@example.com",
            password="secret123",
        )
    assert "password_confirmation" in str(exc_info.value)