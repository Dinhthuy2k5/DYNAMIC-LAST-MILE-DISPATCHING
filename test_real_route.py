"""
test_real_route.py — Chạy Greedy Insertion (B1) và OR-Tools (B2) trên dữ liệu thật.

Hỗ trợ 2 nguồn dữ liệu:
  - amazon : 1 route_id từ almrrc2021 real_data (mặc định, 1 xe)
  - solomon: file .txt định dạng Solomon VRPTW    (nhiều xe)

Cách dùng:
  # Amazon – tự chọn route (1 xe)
  python test_real_route.py

  # Amazon – chỉ định route cụ thể + OR-Tools time limit
  python test_real_route.py --route RouteID_xxxx --time-limit 30

  # Solomon – nhiều xe
  python test_real_route.py --source solomon --file data/solomon/SAMPLE_SOLOMON_FORMAT_15.txt

  # Solomon – nhiều xe + OR-Tools time limit dài hơn
  python test_real_route.py --source solomon --file data/solomon/SAMPLE_SOLOMON_FORMAT_15.txt --time-limit 60
"""

import argparse
import io
import json
import os
import sys
import time

# Fix encoding trên Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Đưa src/ vào sys.path để dùng absolute package imports
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from adapters.datasets.amazon.normalize_amazon import normalize_route, normalize_route_fleet
from adapters.datasets.solomon.parse_solomon import parse_solomon_file
from validation.validator import validate_instance, validate_plan
from optimization.greedy_insertion import greedy_insertion
from optimization.or_tools_optimizer import solve_or_tools

REAL_DATA_BASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "real_data", "almrrc2021-data-training", "model_build_inputs",
)


# ──────────────────────────────────────────────
# Amazon helpers
# ──────────────────────────────────────────────

def _pick_amazon_route(route_data, min_dropoffs=5, max_dropoffs=30):
    """Chọn route đầu tiên có số Dropoff hợp lý."""
    for rid, r in route_data.items():
        n = sum(1 for s in r["stops"].values() if s.get("type", "").lower() == "dropoff")
        if min_dropoffs <= n <= max_dropoffs:
            return rid, n
    for rid, r in route_data.items():
        n = sum(1 for s in r["stops"].values() if s.get("type", "") != "Station")
        if n > 0:
            return rid, n
    return list(route_data.keys())[0], 0


def _pick_amazon_routes_from_station(route_data, station_id=None, num_vehicles=3,
                                     min_drops=5, max_drops=30):
    """Trả về list route_id cùng station, mỗi route có số dropoff hợp lý."""
    from collections import defaultdict
    station_groups = defaultdict(list)
    for rid, r in route_data.items():
        sid = next((s for s, v in r["stops"].items() if v.get("type") == "Station"), None)
        if sid:
            station_groups[sid].append(rid)

    if station_id:
        candidates = station_groups.get(station_id, [])
    else:
        # Chọn station có nhiều route nhất
        station_id, candidates = max(station_groups.items(), key=lambda x: len(x[1]))

    # Lọc route có số dropoff hợp lý
    filtered = [
        rid for rid in candidates
        if min_drops <= sum(1 for s in route_data[rid]["stops"].values()
                           if s.get("type") == "Dropoff") <= max_drops
    ]
    selected = filtered[:num_vehicles] if filtered else candidates[:num_vehicles]
    return station_id, selected


def load_amazon_instance(route_id=None):
    route_data, package_data, travel_times = _load_amazon_raw_data()

    if route_id is None:
        route_id, n_drops = _pick_amazon_route(route_data)
        print(f"  Auto-selected: {route_id}  ({n_drops} Dropoff stops)")
    else:
        stops = route_data[route_id]["stops"]
        n_drops = sum(1 for s in stops.values() if s.get("type", "") != "Station")
        print(f"  Using route: {route_id}  ({n_drops} non-Station stops)")
        print(f"  Route trong travel_times: {route_id in travel_times}")

    print("\n=== [4] Normalize → canonical instance (1 xe) ===")
    snapshot = normalize_route(route_id, route_data, package_data, travel_times)
    return snapshot


def load_solomon_instance(file_path):
    print(f"=== [1] Đọc Solomon file: {file_path} ===")
    snapshot = parse_solomon_file(file_path)
    return snapshot


def _load_amazon_raw_data(route_id_hint=None):
    """Load 3 file JSON lớn của Amazon, trả về (route_data, package_data, travel_times)."""
    print("=== [1] Loading route_data.json ===")
    t0 = time.perf_counter()
    with open(os.path.join(REAL_DATA_BASE, "route_data.json"), encoding="utf-8") as f:
        route_data = json.load(f)
    print(f"  Loaded {len(route_data)} routes in {time.perf_counter() - t0:.2f}s")

    print("\n=== [2] Loading package_data.json ===")
    t0 = time.perf_counter()
    with open(os.path.join(REAL_DATA_BASE, "package_data.json"), encoding="utf-8") as f:
        package_data = json.load(f)
    print(f"  Loaded in {time.perf_counter() - t0:.2f}s")

    print("\n=== [3] Loading travel_times.json (1.8 GB – có thể mất vài phút) ===")
    t0 = time.perf_counter()
    with open(os.path.join(REAL_DATA_BASE, "travel_times.json"), encoding="utf-8") as f:
        travel_times = json.load(f)
    print(f"  Loaded in {time.perf_counter() - t0:.2f}s")
    return route_data, package_data, travel_times


def load_amazon_multi_instance(num_vehicles=3, route_id=None, max_orders=None):
    """Tạo fleet N xe tổng hợp từ order/matrix của một route Amazon duy nhất."""
    route_data, package_data, travel_times = _load_amazon_raw_data()

    print("\n=== [4] Chọn route nguồn cho fleet tổng hợp ===")
    if route_id is None:
        route_id, n_drops = _pick_amazon_route(route_data)
        print(f"  Auto-selected: {route_id}  ({n_drops} Dropoff stops)")
    else:
        n_drops = sum(1 for stop in route_data[route_id]["stops"].values()
                      if stop.get("type") == "Dropoff")
        print(f"  Using route: {route_id}  ({n_drops} Dropoff stops)")
    print(f"  Fleet: {num_vehicles} xe cùng depot/capacity; order không bị nhân bản")
    if max_orders is not None:
        print(f"  Giới hạn tập order chung: {max_orders}")

    print("\n=== [5] Normalize một route → fleet nhiều xe ===")
    t0 = time.perf_counter()
    snapshot = normalize_route_fleet(
        route_id, num_vehicles, route_data, package_data, travel_times,
        max_orders=max_orders,
    )
    print(f"  Done in {time.perf_counter() - t0:.2f}s")
    return snapshot


# ──────────────────────────────────────────────
# Core benchmark runner
# ──────────────────────────────────────────────

def print_instance_summary(snapshot):
    d = snapshot.to_dict()
    print(f"  instance_id : {d['instance_id']}")
    print(f"  source      : {d['source']}")
    print(f"  Orders      : {len(d['orders'])}")
    print(f"  Vehicles    : {len(d['vehicles'])}")
    if d["vehicles"]:
        caps = [v["capacity"] for v in d["vehicles"]]
        print(f"  Capacity/xe : min={min(caps):.0f}  max={max(caps):.0f}")
    if d["orders"]:
        o0 = d["orders"][0]
        print(f"  Sample order: id={o0['id']}  demand={o0['demand']:.0f}"
              f"  ready={o0['ready_time']}  deadline={o0['deadline']}"
              f"  service={o0['service_time']}s")


def run_benchmark(snapshot, time_limit_sec=10, out_dir="output"):
    instance = snapshot.to_dict()

    print("\n=== [V] Validate instance structure ===")
    issues = validate_instance(instance)
    if issues:
        for i in issues:
            print(f"  [ISSUE] {i}")
        return
    print("  OK – no structural issues")

    # Lưu normalized snapshot
    norm_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", "normalized", f"{instance['instance_id']}.json",
    )
    os.makedirs(os.path.dirname(norm_path), exist_ok=True)
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(instance, f, indent=2, ensure_ascii=False)
    print(f"  Saved normalized instance: {norm_path}")

    print("\n=== [B1] Greedy Insertion ===")
    t0 = time.perf_counter()
    plan_b1 = greedy_insertion(instance, planning_time=0.0)
    elapsed_b1 = time.perf_counter() - t0
    res_b1 = validate_plan(instance, plan_b1, planning_time=0.0)
    print(f"  Runtime: {elapsed_b1:.4f}s | feasible: {res_b1['feasible']}")
    print(f"  Travel: {res_b1['metrics']['total_travel_time']}s"
          f" | Lateness: {res_b1['metrics']['total_lateness']}s"
          f" | Unserved: {res_b1['metrics']['num_unserved']}"
          f" | Vehicles used: {res_b1['metrics']['vehicles_used']}")

    print(f"\n=== [B2] OR-Tools (time_limit={time_limit_sec}s) ===")
    t0 = time.perf_counter()
    plan_b2 = solve_or_tools(instance, planning_time=0.0, time_limit_sec=time_limit_sec)
    elapsed_b2 = time.perf_counter() - t0
    res_b2 = validate_plan(instance, plan_b2, planning_time=0.0)
    print(f"  Runtime: {elapsed_b2:.4f}s | feasible: {res_b2['feasible']}")
    print(f"  Travel: {res_b2['metrics']['total_travel_time']}s"
          f" | Lateness: {res_b2['metrics']['total_lateness']}s"
          f" | Unserved: {res_b2['metrics']['num_unserved']}"
          f" | Vehicles used: {res_b2['metrics']['vehicles_used']}")

    print(f"\n=== SO SÁNH B1 (Greedy) vs B2 (OR-Tools) | {instance['instance_id']} ===")
    header = f"{'':28}{'B1 Greedy':>18}{'B2 OR-Tools':>18}"
    print(header)
    rows = [
        ("feasible",              res_b1["feasible"],                     res_b2["feasible"]),
        ("total_travel_time (s)", res_b1["metrics"]["total_travel_time"], res_b2["metrics"]["total_travel_time"]),
        ("total_lateness (soft)", res_b1["metrics"]["total_lateness"],    res_b2["metrics"]["total_lateness"]),
        ("num_unserved",          res_b1["metrics"]["num_unserved"],       res_b2["metrics"]["num_unserved"]),
        ("vehicles_used",         res_b1["metrics"]["vehicles_used"],      res_b2["metrics"]["vehicles_used"]),
        ("runtime_sec",           round(elapsed_b1, 4),                   round(elapsed_b2, 4)),
    ]
    for name, v1, v2 in rows:
        print(f"{name:28}{str(v1):>18}{str(v2):>18}")

    for label, r in [("B1", res_b1), ("B2", res_b2)]:
        for v in r["violations"]:
            print(f"  [{label} VIOLATION] {v}")

    t1 = res_b1["metrics"]["total_travel_time"]
    t2 = res_b2["metrics"]["total_travel_time"]
    if res_b1["feasible"] and res_b2["feasible"] and t1 > 0:
        gap = (t1 - t2) / t1 * 100
        sign = "+tốt hơn" if gap > 0 else "-tệ hơn"
        print(f"\nB2 so với B1: {sign} {abs(gap):.1f}% travel_time")

    os.makedirs(out_dir, exist_ok=True)
    iid = instance["instance_id"]
    out_b1 = os.path.join(out_dir, f"{iid}.B1_greedy.plan.json")
    out_b2 = os.path.join(out_dir, f"{iid}.B2_ortools.plan.json")
    with open(out_b1, "w", encoding="utf-8") as f:
        json.dump({"plan": plan_b1, "metrics": res_b1["metrics"]}, f, indent=2, ensure_ascii=False)
    with open(out_b2, "w", encoding="utf-8") as f:
        json.dump({"plan": plan_b2, "metrics": res_b2["metrics"]}, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved B1 plan : {out_b1}")
    print(f"  Saved B2 plan : {out_b2}")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test B1/B2 trên dữ liệu thật (Amazon 1 xe, Amazon nhiều xe, hoặc Solomon nhiều xe)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  # Solomon nhiều xe (nhanh, không cần load 1.8 GB)
  python test_real_route.py --source solomon

  # Amazon 1 xe – tự chọn route
  python test_real_route.py --source amazon

  # Amazon 1 xe – chỉ định route
  python test_real_route.py --source amazon --route RouteID_xxxx

  # Amazon nhiều xe tổng hợp từ một route; 3 xe, tối đa 30 order chung
  python test_real_route.py --source amazon --multi-vehicle --num-vehicles 3 --max-orders 30

  # Chỉ định route thật làm nguồn
  python test_real_route.py --source amazon --multi-vehicle --route RouteID_xxxx --num-vehicles 5
        """,
    )
    parser.add_argument("--source", choices=["amazon", "solomon"], default="amazon",
                        help="Nguồn dữ liệu. Mặc định: amazon")
    # Amazon 1 xe
    parser.add_argument("--route", default=None,
                        help="[Amazon] Route ID nguồn; dùng được cho 1 xe hoặc fleet tổng hợp")
    # Amazon nhiều xe
    parser.add_argument("--multi-vehicle", action="store_true",
                        help="[Amazon] Tạo N xe cùng depot/capacity từ một route")
    parser.add_argument("--num-vehicles", type=int, default=3,
                        help="[Amazon multi] Số xe tổng hợp. Mặc định: 3")
    parser.add_argument("--max-orders", type=int, default=None,
                        help="[Amazon multi] Giới hạn tổng số order trong instance – dùng để test nhanh")
    # Solomon
    parser.add_argument("--file", default=None,
                        help="[Solomon] Đường dẫn tới file .txt")
    # Chung
    parser.add_argument("--time-limit", type=int, default=10,
                        help="Time limit (giây) cho OR-Tools. Mặc định: 10")
    parser.add_argument("--out", default="output",
                        help="Thư mục lưu kết quả JSON. Mặc định: output/")
    args = parser.parse_args()

    if args.time_limit <= 0:
        parser.error("--time-limit phải lớn hơn 0.")
    if args.num_vehicles <= 0:
        parser.error("--num-vehicles phải lớn hơn 0.")
    if args.max_orders is not None and args.max_orders <= 0:
        parser.error("--max-orders phải lớn hơn 0.")
    if args.source == "solomon" and (args.multi_vehicle or args.route or args.max_orders is not None):
        parser.error("Các tùy chọn --multi-vehicle/--route/--max-orders chỉ dùng với --source amazon.")

    if args.source == "amazon":
        if args.multi_vehicle:
            snapshot = load_amazon_multi_instance(
                num_vehicles=args.num_vehicles,
                route_id=args.route,
                max_orders=args.max_orders,
            )
        else:
            snapshot = load_amazon_instance(route_id=args.route)
    else:
        file_path = args.file
        if file_path is None:
            file_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "data", "solomon", "SAMPLE_SOLOMON_FORMAT_15.txt",
            )
            print(f"  --file không được chỉ định, dùng mặc định: {file_path}")
        snapshot = load_solomon_instance(file_path)

    print_instance_summary(snapshot)
    run_benchmark(snapshot, time_limit_sec=args.time_limit, out_dir=args.out)


if __name__ == "__main__":
    main()
