"""Согласованные имена статусов заявок/нарядов.

Роли вынесены из структуры: административность пользователя хранится
флагом `User.is_admin` (см. app/models/users.py).
"""


class StatusNames:
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    DONE = "DONE"

    ALL = (NEW, ASSIGNED, DONE)