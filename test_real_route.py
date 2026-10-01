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

from normalize_amazon import normalize_route
from validator import validate_instance, validate_plan
from greedy_insertion import greedy_insertion


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
    instance = normalize_route(target_route, route_data, package_data, travel_times)
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

    print("\n=== [6] Run Greedy Insertion (Baseline B1) ===")
    t0 = time.perf_counter()
    plan = greedy_insertion(instance, planning_time=0.0)
    elapsed = time.perf_counter() - t0
    print(f"  Done in {elapsed:.4f}s")
    served = sum(len(r) for r in plan["routes"].values())
    print(f"  Served   : {served} orders")
    print(f"  Unserved : {len(plan['unserved'])}")

    print("\n=== [7] Validate plan ===")
    result = validate_plan(instance, plan, planning_time=0.0)
    print(f"  feasible          : {result['feasible']}")
    for v in result["violations"]:
        print(f"  [VIOLATION] {v}")
    m = result["metrics"]
    print(f"  total_travel_time : {m['total_travel_time']}")
    print(f"  total_lateness    : {m['total_lateness']}  ({m['num_late_orders']} orders late)")
    print(f"  vehicles_used     : {m['vehicles_used']}")

    out_path = os.path.join(os.path.dirname(__file__),
                            "output", f"{target_route}.real_test.plan.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"instance_id": target_route, "plan": plan, "validation": result},
                  f, indent=2, ensure_ascii=False)
    print(f"\n  Output saved: {out_path}")


if __name__ == "__main__":
    main()
