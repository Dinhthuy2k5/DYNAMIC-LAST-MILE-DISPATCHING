"""
compare_b1_b2.py — W3 exit criteria: chạy B1 (Greedy Insertion) và B2 (OR-Tools
P-CI + GLS) trên CÙNG 1 instance, validate bằng CÙNG 1 validator.py, in kết quả
song song. Đây là phép so sánh được nhắc tới xuyên suốt từ Problem Specification
v1 (Mục 5) đến Thiết kế hệ thống (Mục 9 test design: B1 vs B2).
"""
import argparse
import io
import sys
import time

# Đảm bảo in tiếng Việt có dấu không bị lỗi UnicodeEncodeError trên Windows console (CP1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from optimization.greedy_insertion import greedy_insertion
from optimization.or_tools_optimizer import solve_or_tools
from validation.validator import validate_instance, validate_plan
from domain.codec import load_snapshot


def run_one(label, solve_fn, instance, planning_time):
    t0 = time.perf_counter()
    plan = solve_fn(instance, planning_time=planning_time)
    elapsed = time.perf_counter() - t0
    result = validate_plan(instance, plan, planning_time=planning_time)
    return {
        "label": label,
        "runtime_sec": round(elapsed, 4),
        "feasible": result["feasible"],
        "violations": result["violations"],
        "metrics": result["metrics"],
    }, plan


def compare(instance_path, planning_time=0.0, time_limit_sec=5, scaling_factor=100):
    instance = load_snapshot(instance_path)

    struct_issues = validate_instance(instance)
    if struct_issues:
        print("ABORTED_INVALID_INSTANCE:", struct_issues)
        return None

    b1, b1_plan = run_one("B1 Greedy Insertion", greedy_insertion, instance, planning_time)
    b2, b2_plan = run_one(
        "B2 OR-Tools (P-CI + GLS)",
        lambda inst, planning_time: solve_or_tools(
            inst, planning_time=planning_time, time_limit_sec=time_limit_sec, scaling_factor=scaling_factor
        ),
        instance, planning_time,
    )

    print(f"=== So sánh B1 vs B2 | instance={instance.instance_id} (source={instance.source}) "
          f"| planning_time={planning_time} ===")
    header = f"{'':28}{'B1 Greedy':>18}{'B2 OR-Tools':>18}"
    print(header)
    rows = [
        ("feasible", b1["feasible"], b2["feasible"]),
        ("total_travel_time", b1["metrics"]["total_travel_time"], b2["metrics"]["total_travel_time"]),
        ("total_lateness (soft)", b1["metrics"]["total_lateness"], b2["metrics"]["total_lateness"]),
        ("num_unserved", b1["metrics"]["num_unserved"], b2["metrics"]["num_unserved"]),
        ("vehicles_used", b1["metrics"]["vehicles_used"], b2["metrics"]["vehicles_used"]),
        ("runtime_sec", b1["runtime_sec"], b2["runtime_sec"]),
    ]
    for name, v1, v2 in rows:
        print(f"{name:28}{str(v1):>18}{str(v2):>18}")

    for label, r in [("B1", b1), ("B2", b2)]:
        for v in r["violations"]:
            print(f"  [{label} VIOLATION] {v}")

    t1, t2 = b1["metrics"]["total_travel_time"], b2["metrics"]["total_travel_time"]
    if b1["feasible"] and b2["feasible"] and t1 > 0:
        gap = (t1 - t2) / t1 * 100
        sign = "+tốt hơn" if gap > 0 else "-tệ hơn"
        print(f"\nB2 so với B1: {sign} {abs(gap):.1f}% travel_time")

    return {"instance_id": instance.instance_id, "planning_time": planning_time, "B1": b1, "B2": b2}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_path")
    parser.add_argument("--at-time", type=float, default=0.0)
    parser.add_argument("--time-limit", type=int, default=5, help="time limit (giây) cho OR-Tools")
    parser.add_argument("--scaling-factor", type=int, default=100,
                        help="hệ số scale số thực cho OR-Tools (mặc định: 100, vd 14.14 -> 1414)")
    args = parser.parse_args()
    compare(args.instance_path, planning_time=args.at_time, time_limit_sec=args.time_limit,
            scaling_factor=args.scaling_factor)
