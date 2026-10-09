"""Согласованные имена ролей и статусов (хранятся в БД как записи)."""


class RoleNames:
    ADMIN = "ADMIN"
    WORKER = "WORKER"
    USER = "USER"

    ALL = (ADMIN, WORKER, USER)


class StatusNames:
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    DONE = "DONE"

    ALL = (NEW, ASSIGNED, DONE)