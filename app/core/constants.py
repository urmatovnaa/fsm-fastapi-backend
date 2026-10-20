"""Согласованные имена статусов заявок/нарядов.

Единая таблица `statuses` хранит статусы и для заявок (Request), и для
заказов (Order). Различение типов сделано на уровне приложения: разные
классы констант и разные карты допустимых переходов, но физически все
имена лежат в одной таблице (структура БД не меняется).

Роли вынесены из структуры: административность пользователя хранится
флагом `User.is_admin` (см. app/models/users.py).
"""


class RequestStatuses:
    """Жизненный цикл заявки."""

    SEARCHING_MASTER = "SEARCHING_MASTER"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = (SEARCHING_MASTER, REJECTED, COMPLETED, CANCELLED)


class OrderStatuses:
    """Жизненный цикл заказа (наряда)."""

    ACCEPTED = "ACCEPTED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = (ACCEPTED, EN_ROUTE, IN_PROGRESS, COMPLETED, NOT_COMPLETED, CANCELLED)


# Допустимые переходы между состояниями заявки.
# Терминальные состояния (REJECTED/COMPLETED/CANCELLED) не имеют исхода.
REQUEST_TRANSITIONS: dict[str, frozenset[str]] = {
    RequestStatuses.SEARCHING_MASTER: frozenset(
        {
            RequestStatuses.REJECTED,
            RequestStatuses.COMPLETED,
            RequestStatuses.CANCELLED,
        }
    ),
    RequestStatuses.REJECTED: frozenset(),
    RequestStatuses.COMPLETED: frozenset(),
    RequestStatuses.CANCELLED: frozenset(),
}


# Допустимые переходы между состояниями заказа.
# Основной сценарий: ACCEPTED -> EN_ROUTE -> IN_PROGRESS -> COMPLETED.
# NOT_COMPLETED достижим из ACCEPTED/EN_ROUTE/IN_PROGRESS.
# CANCELLED достижим из ACCEPTED/EN_ROUTE.
ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatuses.ACCEPTED: frozenset(
        {
            OrderStatuses.EN_ROUTE,
            OrderStatuses.NOT_COMPLETED,
            OrderStatuses.CANCELLED,
        }
    ),
    OrderStatuses.EN_ROUTE: frozenset(
        {
            OrderStatuses.IN_PROGRESS,
            OrderStatuses.NOT_COMPLETED,
            OrderStatuses.CANCELLED,
        }
    ),
    OrderStatuses.IN_PROGRESS: frozenset(
        {
            OrderStatuses.COMPLETED,
            OrderStatuses.NOT_COMPLETED,
        }
    ),
    OrderStatuses.COMPLETED: frozenset(),
    OrderStatuses.NOT_COMPLETED: frozenset(),
    OrderStatuses.CANCELLED: frozenset(),
}


# Полный набор имён, который должен присутствовать в таблице `statuses`.
# COMPLETED/CANCELLED общие для заявок и заказов — в таблице хранится
# единственная запись каждого имени.
ALL_STATUS_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys((*RequestStatuses.ALL, *OrderStatuses.ALL))
)


def is_valid_transition(
    current: str | None,
    target: str,
    transitions: dict[str, frozenset[str]],
) -> bool:
    """Проверяет допустимость перехода current -> target по карте переходов."""
    if current is None:
        return False
    return target in transitions.get(current, frozenset())