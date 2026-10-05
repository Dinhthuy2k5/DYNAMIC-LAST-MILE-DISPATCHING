"""test_normalize_amazon_routing.py — test normalize_multi_route với 2 route
nhỏ tự dựng tay: (1) mặc định routing_client=None dùng Euclidean fallback
đúng như hành vi cũ, (2) khi truyền routing_client thì dùng đúng giá trị từ
client đó cho cặp cross-route, KHÔNG đụng vào cặp cùng-route (dữ liệu thật)."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adapters.datasets.amazon.normalize_amazon import normalize_multi_route  # noqa: E402
from adapters.routing.base import MatrixResult  # noqa: E402


def _make_two_route_fixture():
    """R1: station S + dropoff A. R2: station S (cùng toạ độ) + dropoff B.
    travel_times chỉ có cặp CÙNG route (đúng bản chất dữ liệu Amazon thật)."""
    route_data = {
        "R1": {
            "date_YYYY_MM_DD": "2021-01-01", "departure_time_utc": "08:00:00",
            "executor_capacity_cm3": 1000,
            "stops": {
                "S": {"type": "Station", "lat": 0.0, "lng": 0.0},
                "A": {"type": "Dropoff", "lat": 0.0, "lng": 1.0},
            },
        },
        "R2": {
            "date_YYYY_MM_DD": "2021-01-01", "departure_time_utc": "08:00:00",
            "executor_capacity_cm3": 1000,
            "stops": {
                "S": {"type": "Station", "lat": 0.0, "lng": 0.0},
                "B": {"type": "Dropoff", "lat": 0.0, "lng": 2.0},
            },
        },
    }
    package_data = {
        "R1": {"A": {"P1": {"dimensions": {"depth_cm": 1, "height_cm": 1, "width_cm": 1},
                             "planned_service_time_seconds": 10,
                             "time_window": {"start_time_utc": None, "end_time_utc": None}}}},
        "R2": {"B": {"P1": {"dimensions": {"depth_cm": 1, "height_cm": 1, "width_cm": 1},
                             "planned_service_time_seconds": 10,
                             "time_window": {"start_time_utc": None, "end_time_utc": None}}}},
    }
    travel_times = {
        "R1": {"S": {"S": 0.0, "A": 111.0}, "A": {"S": 111.0, "A": 0.0}},
        "R2": {"S": {"S": 0.0, "B": 222.0}, "B": {"S": 222.0, "B": 0.0}},
    }
    return route_data, package_data, travel_times


class FakeRoutingClient:
    def __init__(self, fixed_duration=999.0):
        self.fixed_duration = fixed_duration
        self.calls = []

    def matrix(self, sources, destinations):
        self.calls.append((list(sources), list(destinations)))
        durations = tuple(tuple(self.fixed_duration for _ in destinations) for _ in sources)
        distances = tuple(tuple(self.fixed_duration * 10 for _ in destinations) for _ in sources)
        return MatrixResult(durations_s=durations, distances_m=distances)

    def directions(self, coordinates):
        raise NotImplementedError


class TestNormalizeMultiRouteDefaultFallback(unittest.TestCase):
    def test_same_route_pairs_use_real_data_not_euclidean(self):
        route_data, package_data, travel_times = _make_two_route_fixture()
        snapshot = normalize_multi_route(["R1", "R2"], route_data, package_data, travel_times)
        tm = snapshot.to_dict()["time_matrix"]
        # R1:A <-> S cùng route -> phải lấy đúng 111.0 từ travel_times thật, không phải Euclidean
        self.assertEqual(tm["R1:A"]["S"], 111.0)
        self.assertEqual(tm["S"]["R1:A"], 111.0)
        self.assertEqual(tm["R2:B"]["S"], 222.0)

    def test_cross_route_pair_uses_euclidean_when_no_routing_client(self):
        route_data, package_data, travel_times = _make_two_route_fixture()
        snapshot = normalize_multi_route(["R1", "R2"], route_data, package_data, travel_times)
        tm = snapshot.to_dict()["time_matrix"]

        # R1:A (lng=1,lat=0) <-> R2:B (lng=2,lat=0): cross-route, phải fallback Euclidean
        expected = math.hypot(0.0, (2.0 - 1.0) * 111_000) / 11.0
        self.assertAlmostEqual(tm["R1:A"]["R2:B"], expected, places=3)


class TestNormalizeMultiRouteWithRoutingClient(unittest.TestCase):
    def test_cross_route_pair_uses_routing_client_result(self):
        route_data, package_data, travel_times = _make_two_route_fixture()
        client = FakeRoutingClient(fixed_duration=777.0)
        snapshot = normalize_multi_route(
            ["R1", "R2"], route_data, package_data, travel_times, routing_client=client,
        )
        tm = snapshot.to_dict()["time_matrix"]
        self.assertEqual(tm["R1:A"]["R2:B"], 777.0)  # từ client, KHÔNG phải Euclidean

    def test_same_route_pairs_still_untouched_by_routing_client(self):
        route_data, package_data, travel_times = _make_two_route_fixture()
        client = FakeRoutingClient(fixed_duration=777.0)
        snapshot = normalize_multi_route(
            ["R1", "R2"], route_data, package_data, travel_times, routing_client=client,
        )
        tm = snapshot.to_dict()["time_matrix"]
        self.assertEqual(tm["R1:A"]["S"], 111.0)  # vẫn dữ liệu thật, không bị client ghi đè

    def test_routing_client_called_once_batched_not_per_pair(self):
        route_data, package_data, travel_times = _make_two_route_fixture()
        client = FakeRoutingClient()
        normalize_multi_route(
            ["R1", "R2"], route_data, package_data, travel_times, routing_client=client,
        )
        # dù có nhiều cặp cross-route thiếu, chỉ gọi matrix() đúng 1 lần (batch)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
