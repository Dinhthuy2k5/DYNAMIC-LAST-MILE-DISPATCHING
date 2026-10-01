"""
test_pipeline.py — unit test cho validator.py + greedy_insertion.py, dùng instance
nhỏ tự tạo tay (biết trước đáp án đúng) để kiểm chứng logic, không chỉ chạy
"không crash".

Chạy: python3 -m pytest tests/ -v   (hoặc python3 tests/test_pipeline.py)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from validator import validate_instance, validate_plan, simulate_route  # noqa: E402
from greedy_insertion import greedy_insertion  # noqa: E402
from normalize_amazon import normalize_route  # noqa: E402


def make_trivial_instance():
    """
    Depot tại (0,0). 2 order thẳng hàng trên trục X: A tại x=10, B tại x=20.
    1 xe, capacity đủ cho cả 2. distance = |x1-x2| (đường thẳng, dựng tay để
    dễ kiểm tra bằng tay: đi 0->A->B->? chỉ cần A trước B là tối ưu vì cùng hướng).
    """
    return {
        "instance_id": "trivial", "scenario_id": "trivial", "source": "synthetic",
        "depot": {"id": "D", "x": 0, "y": 0},
        "vehicles": [{
            "id": "V1", "capacity": 100, "remaining_capacity": 100,
            "status": "AVAILABLE", "current_stop": "D", "start_time": 0,
        }],
        "orders": [
            {"id": "A", "x": 10, "y": 0, "demand": 5, "release_time": 0, "ready_time": 0,
             "deadline": 1000, "service_time": 0, "status": "PENDING"},
            {"id": "B", "x": 20, "y": 0, "demand": 5, "release_time": 0, "ready_time": 0,
             "deadline": 1000, "service_time": 0, "status": "PENDING"},
        ],
        "distance_matrix": {
            "D": {"D": 0, "A": 10, "B": 20},
            "A": {"D": 10, "A": 0, "B": 10},
            "B": {"D": 20, "A": 10, "B": 0},
        },
    }


class TestValidatorStructure(unittest.TestCase):
    def test_valid_instance_has_no_issues(self):
        issues = validate_instance(make_trivial_instance())
        self.assertEqual(issues, [])

    def test_missing_distance_matrix_entry_detected(self):
        inst = make_trivial_instance()
        del inst["distance_matrix"]["A"]["B"]
        issues = validate_instance(inst)
        self.assertTrue(any("thiếu cột" in i for i in issues))

    def test_ready_after_due_detected(self):
        inst = make_trivial_instance()
        inst["orders"][0]["ready_time"] = 500
        inst["orders"][0]["deadline"] = 100
        issues = validate_instance(inst)
        self.assertTrue(any("ready_time" in i and "deadline" in i for i in issues))


class TestSimulateRoute(unittest.TestCase):
    def test_arrival_time_exact(self):
        inst = make_trivial_instance()
        vehicle = inst["vehicles"][0]
        events, total_travel = simulate_route(vehicle, ["A", "B"], inst)
        # D->A = 10, A->B = 10 => arrival A=10, arrival B=20
        self.assertAlmostEqual(events[0]["arrival"], 10)
        self.assertAlmostEqual(events[1]["arrival"], 20)
        # D->A->B->D = 10 + 10 + 20, including the depot return leg.
        self.assertAlmostEqual(total_travel, 40)

    def test_wait_when_arrive_before_ready_time(self):
        inst = make_trivial_instance()
        inst["orders"][0]["ready_time"] = 50  # xe đến lúc 10 nhưng phải chờ tới 50
        vehicle = inst["vehicles"][0]
        events, _ = simulate_route(vehicle, ["A"], inst)
        self.assertAlmostEqual(events[0]["arrival"], 10)
        self.assertAlmostEqual(events[0]["start_service"], 50)
        self.assertAlmostEqual(events[0]["wait"], 40)

    def test_lateness_when_deadline_exceeded_but_not_blocking(self):
        inst = make_trivial_instance()
        inst["orders"][1]["deadline"] = 5  # B đến lúc 20 nhưng deadline=5 -> trễ 15, KHÔNG chặn
        vehicle = inst["vehicles"][0]
        events, _ = simulate_route(vehicle, ["A", "B"], inst)
        self.assertAlmostEqual(events[1]["lateness"], 15)


class TestValidatePlan(unittest.TestCase):
    def test_feasible_plan_passes(self):
        inst = make_trivial_instance()
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["violations"], [])
        self.assertAlmostEqual(result["metrics"]["total_travel_time"], 40)

    def test_capacity_violation_detected(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["remaining_capacity"] = 6  # tổng demand A+B = 10 > 6
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        result = validate_plan(inst, plan)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("capacity" in v for v in result["violations"]))

    def test_missing_order_detected(self):
        inst = make_trivial_instance()
        plan = {"routes": {"V1": ["A"]}, "unserved": []}  # quên xử lý B
        result = validate_plan(inst, plan)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("chưa được xử lý" in v for v in result["violations"]))

    def test_duplicate_order_detected(self):
        inst = make_trivial_instance()
        plan = {"routes": {"V1": ["A", "A", "B"]}, "unserved": []}
        result = validate_plan(inst, plan)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("lặp lại" in v for v in result["violations"]))


class TestGreedyInsertion(unittest.TestCase):
    def test_serves_all_orders_when_capacity_allows(self):
        inst = make_trivial_instance()
        plan = greedy_insertion(inst)
        self.assertEqual(plan["unserved"], [])
        served = plan["routes"]["V1"]
        self.assertEqual(set(served), {"A", "B"})

    def test_route_cost_on_straight_line_includes_depot_return(self):
        # Với route khép kín, D->A->B->D và D->B->A->D đều dài 40.
        inst = make_trivial_instance()
        plan = greedy_insertion(inst)
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})
        events, travel = simulate_route(inst["vehicles"][0], plan["routes"]["V1"], inst)
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(travel, 40)

    def test_result_plan_is_feasible(self):
        inst = make_trivial_instance()
        plan = greedy_insertion(inst)
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"], msg=result["violations"])

    def test_unserved_when_capacity_insufficient_for_all(self):
        inst = make_trivial_instance()
        inst["vehicles"] = [{
            "id": "V1", "capacity": 5, "remaining_capacity": 5,
            "status": "AVAILABLE", "current_stop": "D", "start_time": 0,
        }]
        # capacity chỉ đủ cho 1 trong 2 order (mỗi order demand=5)
        plan = greedy_insertion(inst)
        total_served = sum(len(r) for r in plan["routes"].values())
        self.assertEqual(total_served, 1)
        self.assertEqual(len(plan["unserved"]), 1)
        result = validate_plan(inst, plan)
        self.assertTrue(result["feasible"])  # unserved hợp lệ, không phải lỗi
        self.assertEqual(result["metrics"]["num_unserved"], 1)


class TestNewDomainFields(unittest.TestCase):
    """Test riêng cho scenario_id/status/remaining_capacity/release_time mới thêm
    ở schema v2 — kiểm tra code THỰC SỰ dùng đúng field mới, không chỉ đổi tên."""

    def test_capacity_nominal_vs_remaining_are_distinct(self):
        # capacity gốc=100 (thừa sức) nhưng remaining_capacity=6 (gần hết vì đang chở dở)
        # -> phải bị chặn theo remaining_capacity, KHÔNG được dùng nhầm capacity gốc.
        inst = make_trivial_instance()
        inst["vehicles"][0]["capacity"] = 100
        inst["vehicles"][0]["remaining_capacity"] = 6
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}  # tổng demand = 10 > 6
        result = validate_plan(inst, plan)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("remaining_capacity" in v for v in result["violations"]))

    def test_greedy_insertion_skips_unavailable_vehicle(self):
        inst = make_trivial_instance()
        inst["vehicles"] = [
            {"id": "V1", "capacity": 100, "remaining_capacity": 100,
             "status": "UNAVAILABLE", "current_stop": "D", "start_time": 0},
            {"id": "V2", "capacity": 100, "remaining_capacity": 100,
             "status": "AVAILABLE", "current_stop": "D", "start_time": 0},
        ]
        plan = greedy_insertion(inst)
        self.assertEqual(plan["routes"]["V1"], [])  # V1 UNAVAILABLE -> không được gán gì
        self.assertEqual(set(plan["routes"]["V2"]), {"A", "B"})

    def test_validate_plan_flags_order_on_unavailable_vehicle(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["status"] = "UNAVAILABLE"
        plan = {"routes": {"V1": ["A", "B"]}, "unserved": []}
        result = validate_plan(inst, plan)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("UNAVAILABLE" in v for v in result["violations"]))

    def test_remaining_capacity_greater_than_capacity_is_structural_issue(self):
        inst = make_trivial_instance()
        inst["vehicles"][0]["capacity"] = 10
        inst["vehicles"][0]["remaining_capacity"] = 50  # vô lý: còn lại > gốc
        issues = validate_instance(inst)
        self.assertTrue(any("remaining_capacity" in i for i in issues))

    def test_future_release_order_is_not_planned_or_counted_as_unserved(self):
        inst = make_trivial_instance()
        inst["orders"][1]["release_time"] = 15
        plan = greedy_insertion(inst, planning_time=0)
        self.assertEqual(plan["routes"]["V1"], ["A"])
        self.assertEqual(plan["unserved"], [])
        result = validate_plan(inst, plan, planning_time=0)
        self.assertTrue(result["feasible"], msg=result["violations"])
        self.assertEqual(result["metrics"]["num_unserved"], 0)

    def test_released_order_is_included_at_snapshot_time(self):
        inst = make_trivial_instance()
        inst["orders"][1]["release_time"] = 15
        plan = greedy_insertion(inst, planning_time=15)
        self.assertEqual(set(plan["routes"]["V1"]), {"A", "B"})
        self.assertTrue(validate_plan(inst, plan, planning_time=15)["feasible"])


class TestAmazonNormalization(unittest.TestCase):
    def test_stop_time_window_is_intersection_of_package_windows(self):
        route_data = {
            "R1": {
                "date_YYYY_MM_DD": "2021-01-01",
                "departure_time_utc": "08:00:00",
                "executor_capacity_cm3": 1000,
                "stops": {
                    "DEPOT": {"type": "Station", "lng": 0, "lat": 0},
                    "S1": {"type": "Dropoff", "lng": 1, "lat": 1},
                },
            }
        }
        package_data = {"R1": {"S1": {
            "P1": {"dimensions": {"depth_cm": 1, "height_cm": 1, "width_cm": 1},
                   "planned_service_time_seconds": 2,
                   "time_window": {"start_time_utc": "2021-01-01 09:00:00", "end_time_utc": "2021-01-01 12:00:00"}},
            "P2": {"dimensions": {"depth_cm": 1, "height_cm": 1, "width_cm": 1},
                   "planned_service_time_seconds": 3,
                   "time_window": {"start_time_utc": "2021-01-01 10:00:00", "end_time_utc": "2021-01-01 11:00:00"}},
        }}}
        travel_times = {"R1": {"DEPOT": {"DEPOT": 0, "S1": 60}, "S1": {"DEPOT": 60, "S1": 0}}}

        instance = normalize_route("R1", route_data, package_data, travel_times)
        stop = instance["orders"][0]
        self.assertEqual(stop["ready_time"], 7200)
        self.assertEqual(stop["deadline"], 10800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
