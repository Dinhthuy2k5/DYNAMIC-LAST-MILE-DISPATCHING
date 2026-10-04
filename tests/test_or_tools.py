"""
test_or_tools.py — unit test cho current_state.py + or_tools_optimizer.py (W3).
Dùng time_limit_sec ngắn (1s) để test chạy nhanh — không ảnh hưởng tính đúng đắn
trên instance nhỏ dùng để test.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from application.planning.current_state import build_current_state  # noqa: E402
from optimization.or_tools_optimizer import solve_or_tools  # noqa: E402
from validation.validator import validate_plan  # noqa: E402

# import instance mẫu y hệt test_pipeline.py để 2 bộ test nhất quán
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_pipeline import make_trivial_instance  # noqa: E402

TL = 1  # time_limit_sec ngắn cho test


class TestCurrentStateBuilder(unittest.TestCase):
    def test_excludes_unreleased_order(self):
        inst = make_trivial_instance()
        inst["orders"][1]["release_time"] = 15
        state = build_current_state(inst, planning_time=0)
        self.assertEqual([o["id"] for o in state["orders"]], ["A"])

    def test_snapshot_version_is_preserved_on_state_and_candidate(self):
        inst = make_trivial_instance()
        inst["state_version"] = 12
        inst["matrix_version"] = 4
        state = build_current_state(inst, planning_time=0)
        plan = solve_or_tools(inst, time_limit_sec=TL)
        self.assertEqual(state["state_version"], 12)
        self.assertEqual(state["matrix_version"], 4)
        self.assertEqual(plan["base_state_version"], 12)
        self.assertEqual(plan["base_matrix_version"], 4)

    def test_includes_released_order_at_snapshot_time(self):
        inst = make_trivial_instance()
        inst["orders"][1]["release_time"] = 15
        state = build_current_state(inst, planning_time=15)
        self.assertEqual({o["id"] for o in state["orders"]}, {"A", "B"})

    def test_excludes_unavailable_vehicle(self):
        inst = make_trivial_instance()
        inst["vehicles"].append({
            "id": "V2", "capacity": 50, "remaining_capacity": 50,
            "status": "UNAVAILABLE", "current_stop": "D", "start_time": 0,
        })
        state = build_current_state(inst, planning_time=0)
        self.assertEqual([v["id"] for v in state["vehicles"]], ["V1"])

    def test_node_ids_depot_first_no_duplicates(self):
        inst = make_trivial_instance()
        state = build_current_state(inst, planning_time=0)
        self.assertEqual(state["node_ids"][0], "D")
        self.assertEqual(len(state["node_ids"]), len(set(state["node_ids"])))

    def test_each_vehicle_has_private_virtual_start_even_at_customer_node(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["current_stop"] = "A"
        state = build_current_state(inst, planning_time=0, state_version=7)
        start_id = state["start_node_by_vehicle"]["V1"]
        self.assertEqual(state["state_version"], 7)
        self.assertIn("A", [o["id"] for o in state["orders"]])
        self.assertNotEqual(start_id, "A")
        self.assertIn(start_id, state["node_ids"])
        self.assertEqual(state["time_matrix"][start_id]["B"], inst["time_matrix"]["A"]["B"])

    def test_on_road_position_requires_and_uses_updated_matrix_row(self):
        inst = make_trivial_instance()
        current_position = "ROAD_V1_SNAPSHOT_9"
        inst["vehicles"][0]["current_stop"] = current_position
        inst["time_matrix"][current_position] = {"D": 17, "A": 8, "B": 13, current_position: 0}
        for node, row in inst["time_matrix"].items():
            row[current_position] = {"D": 16, "A": 7, "B": 12, current_position: 0}[node]

        state = build_current_state(inst, planning_time=9)
        start_id = state["start_node_by_vehicle"]["V1"]
        self.assertEqual(state["time_matrix"][start_id]["A"], 8)
        self.assertEqual(state["time_matrix"][start_id]["B"], 13)
        self.assertEqual(state["vehicles"][0]["start_time"], 9)


class TestOrToolsOptimizer(unittest.TestCase):
    def test_serves_all_orders_when_capacity_allows(self):
        inst = make_trivial_instance()
        plan = solve_or_tools(inst, time_limit_sec=TL)
        self.assertEqual(plan["unserved"], [])
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})

    def test_result_plan_is_feasible(self):
        inst = make_trivial_instance()
        plan = solve_or_tools(inst, time_limit_sec=TL)
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"], msg=result["violations"])

    def test_unserved_when_capacity_insufficient_for_all(self):
        inst = make_trivial_instance()
        inst["vehicles"] = [{
            "id": "V1", "capacity": 5, "remaining_capacity": 5,
            "status": "AVAILABLE", "current_stop": "D", "start_time": 0,
        }]
        plan = solve_or_tools(inst, time_limit_sec=TL)
        total_served = sum(len(r) for r in plan["routes"].values())
        self.assertEqual(total_served, 1)
        self.assertEqual(len(plan["unserved"]), 1)
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["metrics"]["num_unserved"], 1)

    def test_skips_unavailable_vehicle(self):
        inst = make_trivial_instance()
        inst["vehicles"] = [
            {"id": "V1", "capacity": 100, "remaining_capacity": 100,
             "status": "UNAVAILABLE", "current_stop": "D", "start_time": 0},
            {"id": "V2", "capacity": 100, "remaining_capacity": 100,
             "status": "AVAILABLE", "current_stop": "D", "start_time": 0},
        ]
        plan = solve_or_tools(inst, time_limit_sec=TL)
        self.assertNotIn("V1", plan["routes"])  # V1 UNAVAILABLE -> bị loại khỏi fleet ngay ở current_state
        self.assertEqual(set(plan["routes"]["V2"]), {"A", "B"})

    def test_future_release_order_excluded_from_plan(self):
        inst = make_trivial_instance()
        inst["orders"][1]["release_time"] = 15
        plan = solve_or_tools(inst, planning_time=0, time_limit_sec=TL)
        self.assertEqual(plan["routes"]["V1"], ["A"])
        self.assertEqual(plan["unserved"], [])  # B chưa released -> không tính unserved
        result = validate_plan(inst, plan, planning_time=0)
        self.assertTrue(result["feasible"], msg=result["violations"])

    def test_respects_hard_ready_time_via_waiting(self):
        inst = make_trivial_instance()
        inst["orders"][0]["ready_time"] = 50  # xe đến A lúc 10 -> phải chờ tới 50
        plan = solve_or_tools(inst, time_limit_sec=TL)
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"])
        events_a = [e for e in result["per_vehicle"]["V1"] if e["order_id"] == "A"][0]
        self.assertAlmostEqual(events_a["start_service"], 50)

    def test_vehicle_snapshot_time_tau_is_fixed_in_time_dimension(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["start_time"] = 30
        plan = solve_or_tools(inst, planning_time=50, time_limit_sec=TL)
        result = validate_plan(inst, plan, planning_time=50)
        self.assertTrue(result["feasible"], msg=result["violations"])
        event_a = next(e for e in result["per_vehicle"]["V1"] if e["order_id"] == "A")
        self.assertGreaterEqual(event_a["start_service"], 60)

    def test_active_customer_at_vehicle_origin_remains_serviceable(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["current_stop"] = "A"
        plan = solve_or_tools(inst, time_limit_sec=TL)
        self.assertEqual(plan["unserved"], [])
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})
        self.assertEqual(plan["base_state_version"], 0)
        self.assertTrue(validate_plan(inst, plan)["feasible"])

    def test_solver_uses_on_road_start_matrix_at_snapshot_time(self):
        inst = make_trivial_instance()
        current_position = "ROAD_V1_SNAPSHOT_9"
        inst["vehicles"][0]["current_stop"] = current_position
        inst["time_matrix"][current_position] = {"D": 17, "A": 8, "B": 13, current_position: 0}
        for node, row in inst["time_matrix"].items():
            row[current_position] = {"D": 16, "A": 7, "B": 12, current_position: 0}[node]

        plan = solve_or_tools(inst, planning_time=9, time_limit_sec=TL)
        result = validate_plan(inst, plan, planning_time=9)
        self.assertTrue(result["feasible"], msg=result["violations"])
        route = plan["routes"]["V1"]
        first_order = route[0]
        first_event = result["per_vehicle"]["V1"][0]
        expected_start = 9 + inst["time_matrix"][current_position][first_order]
        self.assertAlmostEqual(first_event["start_service"], expected_start)

    def test_closed_route_cost_matches_optimal_regardless_of_direction(self):
        # Route KHÉP KÍN (quay về depot): D->A->B->D và D->B->A->D dài BẰNG
        # NHAU (40=40) trên đường thẳng — khác route hở. Test đúng là so cost
        # với optimal đã biết tay, không ép 1 thứ tự cụ thể.
        inst = make_trivial_instance()
        plan = solve_or_tools(inst, time_limit_sec=TL)
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})
        result = validate_plan(inst, plan)
        self.assertAlmostEqual(result["metrics"]["total_travel_time"], 40)

    def test_scaling_factor_preserves_decimal_precision(self):
        # Instance với travel-time proxy có phần thập phân (như Solomon)
        inst = {
            "instance_id": "decimal_test", "scenario_id": "decimal_test", "source": "synthetic",
            "matrix_version": 0,
            "depot": {"id": "D", "x": 0.0, "y": 0.0},
            "vehicles": [{
                "id": "V1", "capacity": 100, "remaining_capacity": 100,
                "status": "AVAILABLE", "current_stop": "D", "start_time": 0.0,
            }],
            "orders": [
                {"id": "A", "x": 10.45, "y": 0.0, "demand": 5, "release_time": 0.0, "ready_time": 0.0,
                 "deadline": 1000.0, "service_time": 1.25, "status": "PENDING"},
                {"id": "B", "x": 20.85, "y": 0.0, "demand": 5, "release_time": 0.0, "ready_time": 0.0,
                 "deadline": 1000.0, "service_time": 2.50, "status": "PENDING"},
            ],
            "time_matrix": {
                "D": {"D": 0.0, "A": 10.45, "B": 20.85},
                "A": {"D": 10.45, "A": 0.0, "B": 10.40},
                "B": {"D": 20.85, "A": 10.40, "B": 0.0},
            },
        }
        plan = solve_or_tools(inst, time_limit_sec=TL, scaling_factor=100)
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"])
        # D -> A -> B -> D = 10.45 + 10.40 + 20.85 = 41.70
        self.assertAlmostEqual(result["metrics"]["total_travel_time"], 41.70, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
