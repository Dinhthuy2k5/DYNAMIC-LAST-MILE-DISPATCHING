"""Interface chung cho mọi routing engine thật (OSRM, OpenRouteService, Google...).

Tách riêng khỏi provider cụ thể để đổi nhà cung cấp không ảnh hưởng
normalize_amazon.py / application/geometry / application/planning — những nơi
gọi RoutingClient chỉ biết tới 2 method: matrix() và directions().

Quy ước toạ độ: LUÔN (lat, lng) — khớp với Location.x=lng, Location.y=lat
trong domain/entities.py (ngược thứ tự so với 1 số API dùng lng,lat — việc
đổi thứ tự khi gọi HTTP thật là trách nhiệm của từng client cụ thể, không rò
ra interface này).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

Coordinate = tuple[float, float]  # (lat, lng)


class RoutingClientError(Exception):
    """Lỗi khi gọi routing engine thật: mạng, quota, API key sai, response bất thường."""


@dataclass(frozen=True)
class MatrixResult:
    """Kết quả ma trận travel giữa 2 tập điểm (sources x destinations)."""

    durations_s: tuple[tuple[float, ...], ...]  # [i][j] = giây từ sources[i] đến destinations[j]
    distances_m: tuple[tuple[float, ...], ...]  # [i][j] = mét, None nếu provider không trả


@dataclass(frozen=True)
class DirectionsResult:
    """Kết quả tuyến đường thật giữa các điểm theo đúng thứ tự — dùng để vẽ map."""

    distance_m: float
    duration_s: float
    geometry: tuple[Coordinate, ...]  # polyline đã decode, (lat, lng) theo đúng thứ tự đi qua


class RoutingClient(ABC):
    """Mọi provider thật phải implement đúng 2 method này."""

    @abstractmethod
    def matrix(
        self,
        sources: list[Coordinate],
        destinations: list[Coordinate],
    ) -> MatrixResult:
        """Trả về travel time (+ distance nếu có) giữa MỌI cặp sources x destinations.

        Dùng cho: vá time_matrix khi có node không nằm sẵn trong dữ liệu gốc
        (vị trí xe live, cặp cross-route). KHÔNG dùng để lấy hình học vẽ map —
        dùng directions() cho việc đó.
        """

    @abstractmethod
    def directions(self, coordinates: list[Coordinate]) -> DirectionsResult:
        """Trả về tuyến đường thật đi qua đúng các điểm theo thứ tự đã cho.

        Dùng cho: vẽ polyline trên map cho 1 cạnh (hoặc 1 route) đã có trong
        plan. Không dùng cho N×N — chỉ gọi cho các cạnh thực sự xuất hiện.
        """
