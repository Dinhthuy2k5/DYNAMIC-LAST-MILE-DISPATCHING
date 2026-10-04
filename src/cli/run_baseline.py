"""
run_baseline.py — Baseline "no-replan": giải MỘT LẦN bằng Greedy Insertion (B1)
tại t=0 trên toàn bộ order đã biết, KHÔNG bao giờ re-plan kể cả khi có dynamic
event xảy ra sau đó. Đây là baseline dùng để so sánh ở W5-W9 khi có
event-driven re-optimization (đúng vai trò đã ghi trong Thiết kế hệ thống,
Mục 9 test design: baseline "no-replan" vs "re-plan").

W2 chỉ cần baseline này chạy đúng và feasibility validator xác nhận plan hợp lệ
— OR-Tools/GLS chưa xuất hiện ở đây (đúng scope W1: "P-CI + GLS" chỉ áp dụng
từ W3 static optimizer trở đi).
"""
import argparse
import json
import sys
import time

from optimization.greedy_insertion import greedy_insertion
from validation.validator import validate_instance, validate_plan
from domain.codec import load_snapshot


def run(instance_path, output_dir=None, planning_time=0.0):
    instance = load_snapshot(instance_path)

    report = {"instance_id": instance.instance_id, "source": instance.source}

    struct_issues = validate_instance(instance)
    report["instance_structural_issues"] = struct_issues
    if struct_issues:
        report["status"] = "ABORTED_INVALID_INSTANCE"
        return report, None

    t0 = time.perf_counter()
    plan = greedy_insertion(instance, planning_time=planning_time)
    elapsed = time.perf_counter() - t0

    result = validate_plan(instance, plan, planning_time=planning_time)
    report["status"] = "OK" if result["feasible"] else "INFEASIBLE_PLAN"
    report["feasible"] = result["feasible"]
    report["violations"] = result["violations"]
    report["metrics"] = result["metrics"]
    report["metrics"]["greedy_insertion_runtime_sec"] = round(elapsed, 4)
    report["metrics"]["num_orders"] = len(instance.orders)
    report["metrics"]["num_vehicles_available"] = len(instance.vehicles)
    report["planning_time"] = planning_time

    if output_dir:
        stem = instance.instance_id
        with open(f"{output_dir}/{stem}.plan.json", "w") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        with open(f"{output_dir}/{stem}.report.json", "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    return report, plan


def print_report(report):
    print(f"=== Baseline no-replan | instance={report['instance_id']} (source={report['source']}) ===")
    print(f"status: {report['status']}")
    if report.get("instance_structural_issues"):
        for i in report["instance_structural_issues"]:
            print(f"  [INSTANCE ISSUE] {i}")
        return
    print(f"feasible: {report['feasible']}")
    for v in report["violations"]:
        print(f"  [VIOLATION] {v}")
    m = report["metrics"]
    print(f"  orders: {m['num_orders']} | vehicles available: {m['num_vehicles_available']} | vehicles used: {m['vehicles_used']}")
    print(f"  unserved: {m['num_unserved']}")
    print(f"  total_travel_time: {m['total_travel_time']}")
    print(f"  total_lateness (soft): {m['total_lateness']}  | late orders: {m['num_late_orders']}")
    print(f"  greedy insertion runtime: {m['greedy_insertion_runtime_sec']}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_path")
    parser.add_argument("--out", default=None, help="thư mục lưu plan + report (json)")
    parser.add_argument("--at-time", type=float, default=0.0,
                        help="thời điểm snapshot để xét release_time (mặc định: 0)")
    args = parser.parse_args()

    report, plan = run(args.instance_path, args.out, planning_time=args.at_time)
    print_report(report)
    sys.exit(0 if report["status"] == "OK" else 1)
