"""Mô hình entity nghiệp vụ độc lập với Amazon, Solomon và OR-Tools.

Các adapter dữ liệu chuyển nguồn ngoài thành những entity này. ``to_dict`` và
``from_dict`` là ranh giới serialize cho định dạng snapshot JSON hiện dùng.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    seed: int | None = None
    clock: float = 0.0
    status: str = "READY"
    config: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Location:
    """Tọa độ theo quy ước project: x là longitude, y là latitude."""

    x: float
    y: float

    @classmethod
    def from_entity(cls, value: Mapping[str, Any]) -> "Location":
        return cls(x=float(value["x"]), y=float(value["y"]))

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class Depot:
    id: str
    location: Location

    @classmethod
    def from_entity(cls, value: Mapping[str, Any]) -> "Depot":
        return cls(str(value["id"]), Location.from_entity(value))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, **self.location.to_dict()}


@dataclass(frozen=True)
class Order:
    id: str
    location: Location
    demand: float
    release_time: float
    ready_time: float
    deadline: float
    service_time: float
    status: str

    @classmethod
    def from_entity(cls, value: Mapping[str, Any]) -> "Order":
        return cls(
            id=str(value["id"]), location=Location.from_entity(value),
            demand=float(value["demand"]), release_time=float(value["release_time"]),
            ready_time=float(value["ready_time"]), deadline=float(value["deadline"]),
            service_time=float(value["service_time"]), status=str(value["status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, **self.location.to_dict(), "demand": self.demand,
            "release_time": self.release_time, "ready_time": self.ready_time,
            "deadline": self.deadline, "service_time": self.service_time,
            "status": self.status,
        }


@dataclass(frozen=True)
class Vehicle:
    id: str
    capacity: float
    remaining_capacity: float
    status: str
    current_stop: str
    start_time: float

    @classmethod
    def from_entity(cls, value: Mapping[str, Any]) -> "Vehicle":
        return cls(
            id=str(value["id"]), capacity=float(value["capacity"]),
            remaining_capacity=float(value["remaining_capacity"]),
            status=str(value["status"]), current_stop=str(value["current_stop"]),
            start_time=float(value["start_time"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "capacity": self.capacity,
            "remaining_capacity": self.remaining_capacity, "status": self.status,
            "current_stop": self.current_stop, "start_time": self.start_time,
        }


@dataclass(frozen=True)
class TimeMatrix:
    """Travel time có hướng, tính bằng giây, gắn với một phiên bản ma trận."""

    matrix_version: int
    times: Mapping[str, Mapping[str, float]]

    def travel_time(self, from_node: str, to_node: str) -> float:
        return float(self.times[from_node][to_node])

    @classmethod
    def from_snapshot(cls, matrix_version: int, value: Mapping[str, Any]) -> "TimeMatrix":
        times = {
            str(source): {str(target): float(seconds) for target, seconds in row.items()}
            for source, row in value.items()
        }
        return cls(matrix_version=int(matrix_version), times=times)

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {source: dict(row) for source, row in self.times.items()}


@dataclass(frozen=True)
class RoutingSnapshot:
    """Snapshot đầu vào của một lần lập kế hoạch."""

    instance_id: str
    scenario_id: str
    source: str
    depot: Depot
    vehicles: tuple[Vehicle, ...]
    orders: tuple[Order, ...]
    time_matrix: TimeMatrix
    state_version: int = 0

    @property
    def matrix_version(self) -> int:
        return self.time_matrix.matrix_version

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RoutingSnapshot":
        matrix_version = value["matrix_version"]
        return cls(
            instance_id=str(value["instance_id"]), scenario_id=str(value["scenario_id"]),
            source=str(value["source"]), depot=Depot.from_entity(value["depot"]),
            vehicles=tuple(Vehicle.from_entity(v) for v in value["vehicles"]),
            orders=tuple(Order.from_entity(o) for o in value["orders"]),
            time_matrix=TimeMatrix.from_snapshot(matrix_version, value["time_matrix"]),
            state_version=int(value.get("state_version", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id, "scenario_id": self.scenario_id,
            "source": self.source, "state_version": self.state_version,
            "matrix_version": self.matrix_version, "depot": self.depot.to_dict(),
            "vehicles": [vehicle.to_dict() for vehicle in self.vehicles],
            "orders": [order.to_dict() for order in self.orders],
            "time_matrix": self.time_matrix.to_dict(),
        }


@dataclass(frozen=True)
class RouteStop:
    """Một lần ghé một stop trong route; sequence xác định thứ tự phục vụ."""

    stop_id: str
    order_id: str
    sequence: int
    route_id: str | None = None
    eta: float | None = None


@dataclass(frozen=True)
class Route:
    """Route của đúng một vehicle; plan chứa nhiều Route nếu dùng nhiều xe."""

    vehicle_id: str
    stops: tuple[RouteStop, ...]
    route_id: str | None = None
    plan_id: str | None = None
    route_metrics: Mapping[str, float] | None = None


@dataclass(frozen=True)
class DeliveryPlan:
    """Plan chứa nhiều route, gắn với đúng phiên bản state và time matrix."""

    routes: tuple[Route, ...]
    unserved_order_ids: tuple[str, ...]
    base_state_version: int
    base_matrix_version: int
    reason_event_id: str | None = None
    plan_id: str | None = None
    scenario_id: str | None = None
    status: str = "DRAFT"
    created_at: str | None = None
    metrics: Mapping[str, Any] | None = None

    @classmethod
    def candidate(
        cls,
        routes: Mapping[str, list[str]],
        unserved_order_ids: list[str],
        base_state_version: int,
        base_matrix_version: int,
    ) -> "DeliveryPlan":
        return cls(
            routes=tuple(
                Route(
                    vehicle_id=vehicle_id,
                    stops=tuple(
                        RouteStop(stop_id=stop_id, order_id=stop_id, sequence=index)
                        for index, stop_id in enumerate(stop_ids, start=1)
                    ),
                )
                for vehicle_id, stop_ids in routes.items()
            ),
            unserved_order_ids=tuple(unserved_order_ids),
            base_state_version=base_state_version,
            base_matrix_version=base_matrix_version,
        )

    def to_candidate_dict(self) -> dict[str, Any]:
        """Serialize sang format candidate hiện được B1/B2 và validator dùng."""
        return {
            "routes": {
                route.vehicle_id: [stop.stop_id for stop in route.stops]
                for route in self.routes
            },
            "unserved": list(self.unserved_order_ids),
            "base_state_version": self.base_state_version,
            "base_matrix_version": self.base_matrix_version,
        }


@dataclass(frozen=True)
class Event:
    """Envelope chuẩn cho event; payload được diễn giải theo event_type."""

    event_id: str
    scenario_id: str
    event_type: str
    event_time: float
    arrival_time: float
    aggregate_id: str
    sequence: int
    payload: Mapping[str, Any]


def snapshot_payload(value: Any) -> dict[str, Any]:
    """Chuẩn hóa entity hoặc payload JSON về dict tại ranh giới solver cũ."""
    if isinstance(value, RoutingSnapshot):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Đầu vào phải là RoutingSnapshot hoặc mapping canonical.")
