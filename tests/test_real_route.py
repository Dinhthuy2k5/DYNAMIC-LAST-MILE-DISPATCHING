"""
test_real_route.py - normalize + greedy_insertion on 1 real Amazon route.
"""
import json, sys, os, time
import io

# Fix encoding on Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.join(os.path.dirname(__file__),
                    "real_data", "almrrc2021-data-training", "model_build_inputs")
SRC  = os.path.join(os.path.dirname(__file__), "src")
sys.path.insert(0, SRC)

from adapters.datasets.amazon.normalize_amazon import normalize_route
from validation.validator import validate_instance, validate_plan
from optimization.greedy_insertion import greedy_insertion
from optimization.or_tools_optimizer import solve_or_tools


def inspect_stops(route_data, n=5):
    """In ra cấu trúc stops của vài route đầu để debug."""
    for rid, r in list(route_data.items())[:n]:
        types = set(s.get("type", "?") for s in r["stops"].values())
        print(f"  {rid}: {len(r['stops'])} stops, types={types}")


def pick_route(route_data, min_dropoffs=5, max_dropoffs=30):
    """Chọn route đầu tiên có số Dropoff hợp lý."""
    for rid, r in route_data.items():
        n = sum(1 for s in r["stops"].values()
                if s.get("type", "").lower() in ("dropoff",))
        if min_dropoffs <= n <= max_dropoffs:
            return rid, n
    # fallback: lấy route đầu tiên có bất kỳ dropoff nào
    for rid, r in route_data.items():
        n = sum(1 for s in r["stops"].values()
                if s.get("type", "") != "Station")
        if n > 0:
            return rid, n
    return list(route_data.keys())[0], 0


def main():
    target_route = sys.argv[1] if len(sys.argv) > 1 else None

    print("=== [1] Loading route_data.json ===")
    t0 = time.perf_counter()
    with open(os.path.join(BASE, "route_data.json"), encoding="utf-8") as f:
        route_data = json.load(f)
    print(f"  Loaded {len(route_data)} routes in {time.perf_counter()-t0:.2f}s")

    print("  Inspecting first 5 routes stop types:")
    inspect_stops(route_data)

    if target_route is None:
        target_route, n_drops = pick_route(route_data)
        print(f"  Auto-selected: {target_route}  ({n_drops} non-Station stops)")
    else:
        stops = route_data[target_route]["stops"]
        n_drops = sum(1 for s in stops.values() if s.get("type", "") != "Station")
        print(f"  Using route: {target_route}  ({n_drops} non-Station stops)")

    print("\n=== [2] Loading package_data.json ===")
    t0 = time.perf_counter()
    with open(os.path.join(BASE, "package_data.json"), encoding="utf-8") as f:
        package_data = json.load(f)
    print(f"  Loaded in {time.perf_counter()-t0:.2f}s")

    print("\n=== [3] Loading travel_times.json (1.8 GB - may take a few minutes) ===")
    t0 = time.perf_counter()
    with open(os.path.join(BASE, "travel_times.json"), encoding="utf-8") as f:
        travel_times = json.load(f)
    print(f"  Loaded in {time.perf_counter()-t0:.2f}s")
    print(f"  Routes in travel_times: {len(travel_times)}")
    print(f"  Target in travel_times: {target_route in travel_times}")

    print("\n=== [4] Normalize route -> canonical instance ===")
    instance = normalize_route(target_route, route_data, package_data, travel_times).to_dict()
    print(f"  instance_id : {instance['instance_id']}")
    print(f"  Orders      : {len(instance['orders'])}")
    print(f"  Vehicles    : {len(instance['vehicles'])}")
    print(f"  Capacity    : {instance['vehicles'][0]['capacity']}")
    print(f"  Depot       : {instance['depot']['id']}")
    if instance['orders']:
        o0 = instance['orders'][0]
        print(f"  Sample order: id={o0['id']}  demand={o0['demand']:.0f}cm3"
              f"  ready={o0['ready_time']}  deadline={o0['deadline']}"
              f"  service={o0['service_time']}s")

    print("\n=== [5] Validate instance structure ===")
    issues = validate_instance(instance)
    if issues:
        for i in issues:
            print(f"  [ISSUE] {i}")
    else:
        print("  OK - no structural issues")

    # Lưu file normalized instance để sau này có thể chạy compare_b1_b2.py trực tiếp trong 2s
    norm_path = os.path.join(os.path.dirname(__file__), "data", "normalized", f"{target_route}.json")
    os.makedirs(os.path.dirname(norm_path), exist_ok=True)
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(instance, f, indent=2, ensure_ascii=False)
    print(f"  Saved normalized instance: {norm_path}")

    print("\n=== [6] Run Baseline B1 (Greedy Insertion) ===")
    t0 = time.perf_counter()
    plan_b1 = greedy_insertion(instance, planning_time=0.0)
    elapsed_b1 = time.perf_counter() - t0
    res_b1 = validate_plan(instance, plan_b1, planning_time=0.0)
    print(f"  B1 runtime: {elapsed_b1:.4f}s | feasible: {res_b1['feasible']}")
    print(f"  Travel: {res_b1['metrics']['total_travel_time']}s | Lateness: {res_b1['metrics']['total_lateness']}s")

    print("\n=== [7] Run Baseline B2 (OR-Tools P-CI + Guided Local Search) ===")
    time_limit_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    print(f"  Solving with OR-Tools (time_limit = {time_limit_sec}s)...")
    t0 = time.perf_counter()
    plan_b2 = solve_or_tools(instance, planning_time=0.0, time_limit_sec=time_limit_sec)
    elapsed_b2 = time.perf_counter() - t0
    res_b2 = validate_plan(instance, plan_b2, planning_time=0.0)
    print(f"  B2 runtime: {elapsed_b2:.4f}s | feasible: {res_b2['feasible']}")
    print(f"  Travel: {res_b2['metrics']['total_travel_time']}s | Lateness: {res_b2['metrics']['total_lateness']}s")

    print(f"\n=== SO SÁNH B1 (Greedy) vs B2 (OR-Tools) trên Route Thật: {target_route} ===")
    header = f"{'':28}{'B1 Greedy':>18}{'B2 OR-Tools':>18}"
    print(header)
    rows = [
        ("feasible", res_b1["feasible"], res_b2["feasible"]),
        ("total_travel_time", res_b1["metrics"]["total_travel_time"], res_b2["metrics"]["total_travel_time"]),
        ("total_lateness (soft)", res_b1["metrics"]["total_lateness"], res_b2["metrics"]["total_lateness"]),
        ("num_unserved", res_b1["metrics"]["num_unserved"], res_b2["metrics"]["num_unserved"]),
        ("vehicles_used", res_b1["metrics"]["vehicles_used"], res_b2["metrics"]["vehicles_used"]),
        ("runtime_sec", round(elapsed_b1, 4), round(elapsed_b2, 4)),
    ]
    for name, v1, v2 in rows:
        print(f"{name:28}{str(v1):>18}{str(v2):>18}")

    t1, t2 = res_b1["metrics"]["total_travel_time"], res_b2["metrics"]["total_travel_time"]
    if res_b1["feasible"] and res_b2["feasible"] and t1 > 0:
        gap = (t1 - t2) / t1 * 100
        sign = "+tốt hơn" if gap > 0 else "-tệ hơn"
        print(f"\nB2 so với B1: {sign} {abs(gap):.1f}% travel_time")

    out_b1 = os.path.join(os.path.dirname(__file__), "output", f"{target_route}.B1_greedy.plan.json")
    out_b2 = os.path.join(os.path.dirname(__file__), "output", f"{target_route}.B2_ortools.plan.json")
    with open(out_b1, "w", encoding="utf-8") as f:
        json.dump({"plan": plan_b1, "metrics": res_b1["metrics"]}, f, indent=2, ensure_ascii=False)
    with open(out_b2, "w", encoding="utf-8") as f:
        json.dump({"plan": plan_b2, "metrics": res_b2["metrics"]}, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved B1 plan: {out_b1}")
    print(f"  Saved B2 plan: {out_b2}")


if __name__ == "__main__":
    main()
