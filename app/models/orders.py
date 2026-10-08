from enum import Enum


class OrderStatus(str, Enum):
    NEW = "NEW"                # создана, ждёт работника
    ASSIGNED = "ASSIGNED"      # работник принял, заказ создан
    DONE = "DONE"              # работник завершил


class Request:
    def __init__(
        self,
        request_id: int,
        user_id: int,
        street_id: int,
        house_number: int,
        problem_description: str,
        status: OrderStatus = OrderStatus.NEW,
    ):
        self.id = request_id
        self.user_id = user_id
        self.status = status
        self.street_id = street_id
        self.house_number = house_number
        self.problem_description = problem_description


class WorkOrder:
    def __init__(
        self,
        work_order_id: int,
        request_id: int,
        worker_id: int,
    ):
        self.id = work_order_id
        self.request_id = request_id
        self.worker_id = worker_id