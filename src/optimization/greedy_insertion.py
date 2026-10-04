"""
greedy_insertion.py — Baseline B1: Greedy (Cheapest) Insertion, đúng pseudocode
đã chốt trong tài liệu "Các phương pháp giải bài toán DVRPTW" (Mục 3.2) và
Problem Specification v1 (Mục 5).

Feasibility khi chèn: CHỈ capacity là điều kiện chặn cứng (đúng nguyên tắc
ready_time=hard chỉ gây CHỜ chứ không cấm chèn; deadline=soft không cấm chèn).
Điểm chọn vị trí chèn = delta_travel_time + BETA_LATENESS * delta_lateness,
khớp với trọng số beta trong Z_solver weighted-sum đã chốt (Mục 4 của
Problem Specification v1) — ở baseline B1 dùng beta tượng trưng nhỏ vì mục
tiêu B1 là một baseline đơn giản, không phải bản giữ chuẩn cho benchmark trọng số.
"""
from validation.validator import active_order_ids, simulate_route
from domain.entities import DeliveryPlan, snapshot_payload

BETA_LATENESS = 1.0  # trọng số quy đổi 1 đơn vị lateness ra "chi phí" so với travel_time


def _capacity_ok(route, new_order_id, vehicle, orders_by_id):
    load = sum(orders_by_id[oid]["demand"] for oid in route) + orders_by_id[new_order_id]["demand"]
    return load <= vehicle["remaining_capacity"] + 1e-9  # Q_k còn lại, không phải capacity gốc


def greedy_insertion(instance, planning_time=0.0):
    """
    Trả về plan: {"routes": {vehicle_id: [order_id,...]}, "unserved": [order_id,...]}
    """
    instance = snapshot_payload(instance)
    orders_by_id = {o["id"]: o for o in instance["orders"]}
    vehicles = instance["vehicles"]
    time_matrix = instance["time_matrix"]
    depot_id = instance["depot"]["id"]

    routes = {v["id"]: [] for v in vehicles}
    unassigned = [o["id"] for o in instance["orders"] if o["id"] in active_order_ids(instance, planning_time)]
    unserved = []

    vehicles_by_id = {v["id"]: v for v in vehicles}
    cache = {oid: {} for oid in unassigned}  # cache[oid][vid] = (score, pos)

    def update_cache_for_vehicle(vid):
        vehicle = vehicles_by_id[vid]
        if vehicle["status"] == "UNAVAILABLE":
            for oid in unassigned:
                cache[oid].pop(vid, None)
            return

        route = routes[vid]
        
        # Pre-calculate state before each position in the route
        state_at = []
        curr_node = vehicle["current_stop"]
        curr_time = max(float(vehicle["start_time"]), float(planning_time))
        acc_travel = 0.0
        acc_late = 0.0
        
        for roid in route:
            state_at.append((curr_node, curr_time, acc_travel, acc_late))
            o = orders_by_id[roid]
            trav = time_matrix[curr_node][roid]
            arr = curr_time + trav
            start_svc = max(arr, o["ready_time"], o["release_time"])
            acc_late += max(0.0, start_svc - o["deadline"])
            acc_travel += trav
            curr_node = roid
            curr_time = start_svc + o["service_time"]
            
        state_at.append((curr_node, curr_time, acc_travel, acc_late))
        base_travel = acc_travel + (time_matrix[curr_node][depot_id] if route else 0.0)
        base_lateness = acc_late
        
        for oid in unassigned:
            if not _capacity_ok(route, oid, vehicle, orders_by_id):
                cache[oid].pop(vid, None)
                continue
                
            best_for_this = None
            o_insert = orders_by_id[oid]
            
            for pos in range(len(route) + 1):
                curr_n, curr_t, acc_trav, acc_l = state_at[pos]
                
                # simulate insertion of oid
                trav = time_matrix[curr_n][oid]
                arr = curr_t + trav
                start_svc = max(arr, o_insert["ready_time"], o_insert["release_time"])
                acc_l += max(0.0, start_svc - o_insert["deadline"])
                acc_trav += trav
                curr_n = oid
                curr_t = start_svc + o_insert["service_time"]
                
                # simulate remainder of the route
                for roid in route[pos:]:
                    o_next = orders_by_id[roid]
                    trav = time_matrix[curr_n][roid]
                    arr = curr_t + trav
                    start_svc = max(arr, o_next["ready_time"], o_next["release_time"])
                    acc_l += max(0.0, start_svc - o_next["deadline"])
                    acc_trav += trav
                    curr_n = roid
                    curr_t = start_svc + o_next["service_time"]
                    
                acc_trav += time_matrix[curr_n][depot_id]
                
                score = (acc_trav - base_travel) + BETA_LATENESS * (acc_l - base_lateness)
                
                if best_for_this is None or score < best_for_this[0]:
                    best_for_this = (score, pos)
                    
            if best_for_this:
                cache[oid][vid] = best_for_this
            else:
                cache[oid].pop(vid, None)

    # Initialize cache for all vehicles
    for v in vehicles:
        update_cache_for_vehicle(v["id"])

    while unassigned:
        best = None  # (score, vehicle_id, pos, order_id)
        
        for oid in unassigned:
            for vid, (score, pos) in cache[oid].items():
                if best is None or score < best[0]:
                    best = (score, vid, pos, oid)
                    
        if best is None:
            unserved.extend(unassigned)
            break
            
        _, vid, pos, oid = best
        routes[vid].insert(pos, oid)
        unassigned.remove(oid)
        del cache[oid]
        
        # Only the modified vehicle needs to recalculate its valid insertions
        update_cache_for_vehicle(vid)

    return DeliveryPlan.candidate(
        routes, unserved, instance.get("state_version", 0), instance["matrix_version"]
    ).to_candidate_dict()


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/normalized/solomon_sample_15.json"
    instance = json.load(open(path))
    plan = greedy_insertion(instance)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
