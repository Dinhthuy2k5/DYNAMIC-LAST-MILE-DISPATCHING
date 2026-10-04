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

    routes = {v["id"]: [] for v in vehicles}
    unassigned = [o["id"] for o in instance["orders"] if o["id"] in active_order_ids(instance, planning_time)]
    unserved = []

    while unassigned:
        best = None  # (score, vehicle_id, position, order_id)

        for oid in unassigned:
            for vehicle in vehicles:
                if vehicle["status"] == "UNAVAILABLE":
                    continue  # Ràng buộc cứng: theo bất biến nghiệp vụ Mục 4.5, xe hỏng không nhận order mới.
                route = routes[vehicle["id"]]
                if not _capacity_ok(route, oid, vehicle, orders_by_id):
                    continue  # HARD: capacity không đủ -> không xét vị trí nào trên xe này

                base_events, base_travel = simulate_route(
                    vehicle, route, instance, planning_time=planning_time
                )
                base_lateness = sum(e["lateness"] for e in base_events)

                # thử mọi vị trí chèn 0..len(route)
                for pos in range(len(route) + 1):
                    candidate_route = route[:pos] + [oid] + route[pos:]
                    events, travel = simulate_route(
                        vehicle, candidate_route, instance, planning_time=planning_time
                    )
                    new_lateness = sum(e["lateness"] for e in events)

                    delta_travel = travel - base_travel
                    delta_lateness = new_lateness - base_lateness

                    score = delta_travel + BETA_LATENESS * delta_lateness

                    if best is None or score < best[0]:
                        best = (score, vehicle["id"], pos, oid)

        if best is None:
            # còn order nhưng không xe nào đủ capacity -> unserved, đúng z_i=1 trong model
            unserved.extend(unassigned)
            break

        _, vid, pos, oid = best
        routes[vid] = routes[vid][:pos] + [oid] + routes[vid][pos:]
        unassigned.remove(oid)

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
