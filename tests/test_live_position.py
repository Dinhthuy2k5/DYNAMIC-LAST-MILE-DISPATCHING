"""test_live_position.py — test patch_time_matrix_for_live_vehicles bằng 1 fake
RoutingClient (implement đúng interface, không mock HTTP) để kiểm tra logic vá
ma trận, không phụ thuộc OpenRouteService thật.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adapters.routing.base import MatrixResult  # noqa: E402
from application.planning.live_position import patch_time_matrix_for_live_vehicles  # noqa: E402
from application.planning.current_state import build_current_state  # noqa: E402


class FakeRoutingClient:
    """Trả về travel time = khoảng cách Manhattan giữa toạ độ, nhân 10 (giây/đơn vị)
    — đủ để kiểm tra logic vá ma trận mà không cần số liệu thật."""

    def __init__(self):
        self.calls = []

    def matrix(self, sources, destinations):
        self.calls.append((list(sources), list(destinations)))
        durations = tuple(
            tuple((abs(sa - da) + abs(sb - db)) * 10.0 for da, db in destinations)
            for sa, sb in sources
        )
        distances = tuple(tuple(d * 100 for d in row) for row in durations)
        return MatrixResult(durations_s=durations, distances_m=distances)

    def directions(self, coordinates):
        raise NotImplementedError


def make_instance():
    return {
        "instance_id": "i1", "scenario_id": "i1", "matrix_version": 0, "source": "synthetic",
        "depot": {"id": "D", "x": 0.0, "y": 0.0},
        "vehicles": [
            {"id": "V1", "capacity": 100, "remaining_capacity": 100,
             "status": "AVAILABLE", "current_stop": "LIVE1", "start_time": 0.0},
            {"id": "V2", "capacity": 100, "remaining_capacity": 100,
             "status": "AVAILABLE", "current_stop": "D", "start_time": 0.0},  # đã ở node biết sẵn
        ],
        "orders": [
            {"id": "A", "x": 5.0, "y": 0.0, "demand": 1, "release_time": 0,
             "ready_time": 0, "deadline": 1000, "service_time": 0, "status": "PENDING"},
        ],
        "time_matrix": {
            "D": {"D": 0.0, "A": 50.0},
            "A": {"D": 50.0, "A": 0.0},
        },
    }


class TestPatchTimeMatrixForLiveVehicles(unittest.TestCase):
    def test_noop_when_no_live_vehicles(self):
        inst = make_instance()
        patched = patch_time_matrix_for_live_vehicles(inst, {}, FakeRoutingClient())
        self.assertEqual(patched["time_matrix"], inst["time_matrix"])

    def test_adds_two_directions_for_live_node(self):
        inst = make_instance()
        client = FakeRoutingClient()
        patched = patch_time_matrix_for_live_vehicles(inst, {"V1": (3.0, 4.0)}, client)

        live_id = patched["vehicles"][0]["current_stop"]
        self.assertTrue(live_id.startswith("__live_position__:V1"))
        self.assertIn(live_id, patched["time_matrix"])
        # 2 hướng đều phải có: live->existing VÀ existing->live
        self.assertIn("D", patched["time_matrix"][live_id])
        self.assertIn("A", patched["time_matrix"][live_id])
        self.assertIn(live_id, patched["time_matrix"]["D"])
        self.assertIn(live_id, patched["time_matrix"]["A"])
        self.assertEqual(patched["time_matrix"][live_id][live_id], 0.0)

    def test_does_not_mutate_original_instance(self):
        inst = make_instance()
        original_matrix_keys = set(inst["time_matrix"].keys())
        patch_time_matrix_for_live_vehicles(inst, {"V1": (3.0, 4.0)}, FakeRoutingClient())
        self.assertEqual(set(inst["time_matrix"].keys()), original_matrix_keys)  # bản gốc không đổi

    def test_vehicle_not_in_vehicle_positions_untouched(self):
        inst = make_instance()
        patched = patch_time_matrix_for_live_vehicles(inst, {"V1": (3.0, 4.0)}, FakeRoutingClient())
        v2 = next(v for v in patched["vehicles"] if v["id"] == "V2")
        self.assertEqual(v2["current_stop"], "D")  # V2 không trong vehicle_positions -> giữ nguyên

    def test_two_live_vehicles_get_cross_entries(self):
        inst = make_instance()
        inst["vehicles"].append({
            "id": "V3", "capacity": 50, "remaining_capacity": 50,
            "status": "AVAILABLE", "current_stop": "LIVE3", "start_time": 0.0,
        })
        client = FakeRoutingClient()
        patched = patch_time_matrix_for_live_vehicles(
            inst, {"V1": (3.0, 4.0), "V3": (1.0, 1.0)}, client
        )
        live1 = next(v for v in patched["vehicles"] if v["id"] == "V1")["current_stop"]
        live3 = next(v for v in patched["vehicles"] if v["id"] == "V3")["current_stop"]
        self.assertIn(live3, patched["time_matrix"][live1])
        self.assertIn(live1, patched["time_matrix"][live3])

    def test_patched_instance_usable_by_build_current_state(self):
        # Đúng mục tiêu thiết kế: sau khi patch, đưa thẳng vào build_current_state
        # không cần sửa gì thêm.
        inst = make_instance()
        patched = patch_time_matrix_for_live_vehicles(inst, {"V1": (3.0, 4.0)}, FakeRoutingClient())
        state = build_current_state(patched, planning_time=0.0)
        self.assertEqual(len(state["vehicles"]), 2)
        self.assertEqual(len(state["orders"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
