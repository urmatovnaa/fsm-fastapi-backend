from app.models.users import User, UserRole


_users = [
    User(
        user_id=1,
        username="admin",
        role=UserRole.ADMIN,
    ),
    User(
        user_id=2,
        username="worker",
        role=UserRole.WORKER,
    ),
    User(
        user_id=3,
        username="user",
        role=UserRole.USER,
    ),
]


async def get_user_by_username(username: str) -> User | None:
    for user in _users:
        if user.username == username:
            return user

    return None


async def get_user_by_id(user_id: int) -> User | None:
    for user in _users:
        if user.id == user_id:
            return user

    return None


async def create_user(
    username: str,
    password: str,
) -> User:
    new_user = User(
        user_id=len(_users) + 1,
        username=username,
        role=UserRole.USER,
    )

    _users.append(new_user)

    return new_user