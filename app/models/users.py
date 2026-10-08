from enum import Enum


class UserRole(str, Enum):
    USER = "USER"
    WORKER = "WORKER"
    ADMIN = "ADMIN"


# временно
class User:
    def __init__(
        self,
        user_id: int,
        username: str,
        role: UserRole,
        is_active: bool = True,
    ):
        self.id = user_id
        self.username = username
        self.role = role
        self.is_active = is_active