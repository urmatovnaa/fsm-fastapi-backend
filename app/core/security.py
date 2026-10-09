def hash_password(password: str) -> str:
    """
    TODO:
    Реализовать настоящее хеширование пароля.
    """
    return password


def verify_password(
    password: str,
    hashed_password: str,
) -> bool:
    """
    TODO:
    Реализовать проверку пароля.
    """
    return password == hashed_password


def create_access_token(
    user_id: int,
    role: str,
) -> str:
    """
    TODO:
    Реализовать создание JWT.
    """
    return f"temporary-token-{user_id}"


def decode_access_token(token: str) -> dict:
    """
    TODO:
    Реализовать декодирование JWT.
    """
    return {
        "user_id": 1,
    }