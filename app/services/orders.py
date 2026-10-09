from app.models.orders import OrderStatus, Request, WorkOrder
from app.schemas.orders import RequestCreate


class OrderNotFound(Exception):
    ...


class InvalidOrderState(Exception):
    ...


class NotOrderOwner(Exception):
    ...


# TODO: заменить на AsyncSession
_requests: list[Request] = []
_work_orders: list[WorkOrder] = []
_next_request_id = 1
_next_work_order_id = 1


def create_request(*, user_id: int, data: RequestCreate) -> Request:
    global _next_request_id

    request = Request(
        request_id=_next_request_id,
        user_id=user_id,
        street_id=data.street_id,
        house_number=data.house_number,
        problem_description=data.problem_description,
        status=OrderStatus.NEW,
    )
    _requests.append(request)
    _next_request_id += 1

    return request


def get_request(request_id: int) -> Request | None:
    for request in _requests:
        if request.id == request_id:
            return request

    return None


def accept_request(*, request_id: int, worker_id: int) -> WorkOrder:
    global _next_work_order_id

    request = get_request(request_id)
    if request is None:
        raise OrderNotFound

    if request.status != OrderStatus.NEW:
        raise InvalidOrderState

    work_order = WorkOrder(
        work_order_id=_next_work_order_id,
        request_id=request.id,
        worker_id=worker_id,
    )
    _work_orders.append(work_order)
    _next_work_order_id += 1

    request.status = OrderStatus.ASSIGNED

    return work_order


def get_work_order(work_order_id: int) -> WorkOrder | None:
    for work_order in _work_orders:
        if work_order.id == work_order_id:
            return work_order

    return None


def complete_work_order(*, work_order_id: int, worker_id: int) -> WorkOrder:
    work_order = get_work_order(work_order_id)
    if work_order is None:
        raise OrderNotFound

    if work_order.worker_id != worker_id:
        raise NotOrderOwner

    request = get_request(work_order.request_id)
    if request is None:
        raise OrderNotFound

    if request.status != OrderStatus.ASSIGNED:
        raise InvalidOrderState

    request.status = OrderStatus.DONE

    return work_order