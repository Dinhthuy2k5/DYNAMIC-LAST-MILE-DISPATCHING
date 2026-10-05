"""test_route_geometry_service.py — test fetch_geometry_for_plan + plan_total_distance_m
bằng fake RoutingClient (không gọi HTTP thật)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adapters.routing.base import DirectionsResult  # noqa: E402
from application.geometry.route_geometry_service import (  # noqa: E402
    fetch_geometry_for_plan, plan_total_distance_m,
)


class FakeRoutingClient:
    def __init__(self):
        self.directions_calls = []

    def matrix(self, sources, destinations):
        raise NotImplementedError

    def directions(self, coordinates):
        self.directions_calls.append(list(coordinates))
        (lat1, lng1), (lat2, lng2) = coordinates
        dist = (abs(lat1 - lat2) + abs(lng1 - lng2)) * 1000
        return DirectionsResult(
            distance_m=dist, duration_s=dist / 10,
            geometry=(coordinates[0], coordinates[1]),
        )


def make_instance():
    return {
        "instance_id": "i1", "scenario_id": "i1", "matrix_version": 0, "source": "synthetic",
        "depot": {"id": "D", "x": 0.0, "y": 0.0},
        "vehicles": [
            {"id": "V1", "capacity": 100, "remaining_capacity": 100,
             "status": "AVAILABLE", "current_stop": "D", "start_time": 0.0},
        ],
        "orders": [
            {"id": "A", "x": 1.0, "y": 0.0, "demand": 1, "release_time": 0,
             "ready_time": 0, "deadline": 1000, "service_time": 0, "status": "PENDING"},
            {"id": "B", "x": 2.0, "y": 0.0, "demand": 1, "release_time": 0,
             "ready_time": 0, "deadline": 1000, "service_time": 0, "status": "PENDING"},
        ],
        "time_matrix": {
            "D": {"D": 0.0, "A": 10.0, "B": 20.0},
            "A": {"D": 10.0, "A": 0.0, "B": 10.0},
            "B": {"D": 20.0, "A": 10.0, "B": 0.0},
        },
    }


class TestFetchGeometryForPlan(unittest.TestCase):
    def test_fetches_only_plan_edges_not_full_matrix(self):
        inst = make_instance()
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        client = FakeRoutingClient()
        cache = fetch_geometry_for_plan(plan, inst, client)

        # route khép kín: D->A, A->B, B->D = đúng 3 cạnh, không phải N^2
        self.assertEqual(set(cache.keys()), {("D", "A"), ("A", "B"), ("B", "D")})
        self.assertEqual(len(client.directions_calls), 3)

    def test_cache_prevents_duplicate_calls(self):
        inst = make_instance()
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        client = FakeRoutingClient()
        cache = fetch_geometry_for_plan(plan, inst, client)
        fetch_geometry_for_plan(plan, inst, client, cache=cache)  # gọi lại với cache cũ
        self.assertEqual(len(client.directions_calls), 3)  # không tăng thêm

    def test_empty_route_produces_no_edges(self):
        inst = make_instance()
        plan = {"routes": {"V1": []}, "unserved": ["A", "B"]}
        cache = fetch_geometry_for_plan(plan, inst, FakeRoutingClient())
        self.assertEqual(cache, {})

    def test_raises_on_unknown_node_without_extra_coords(self):
        inst = make_instance()
        inst["vehicles"][0]["current_stop"] = "LIVE_X"  # không trùng depot/order nào
        plan = {"routes": {"V1": ["A"]}, "unserved": []}
        with self.assertRaises(ValueError):
            fetch_geometry_for_plan(plan, inst, FakeRoutingClient())

    def test_extra_coords_resolves_live_vehicle_position(self):
        inst = make_instance()
        inst["vehicles"][0]["current_stop"] = "LIVE_X"
        plan = {"routes": {"V1": ["A"]}, "unserved": []}
        cache = fetch_geometry_for_plan(
            plan, inst, FakeRoutingClient(), extra_coords={"LIVE_X": (0.5, 0.5)}
        )
        self.assertIn(("LIVE_X", "A"), cache)


class TestPlanTotalDistance(unittest.TestCase):
    def test_sums_distance_across_edges(self):
        inst = make_instance()
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        client = FakeRoutingClient()
        cache = fetch_geometry_for_plan(plan, inst, client)
        total = plan_total_distance_m(plan, inst, cache)
        expected = sum(cache[e]["distance_m"] for e in [("D", "A"), ("A", "B"), ("B", "D")])
        self.assertAlmostEqual(total, expected)

    def test_raises_if_cache_incomplete(self):
        inst = make_instance()
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        with self.assertRaises(KeyError):
            plan_total_distance_m(plan, inst, {})  # cache rỗng, chưa fetch


if __name__ == "__main__":
    unittest.main(verbosity=2)
