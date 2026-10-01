"""
validator.py — Feasibility validator cho canonical instance + plan.

Đúng theo Problem Specification v1 (Mục 3):
- ready_time (a_i) = HARD  -> không được phục vụ trước; đến sớm thì CHỜ (không phải lỗi).
- deadline  (b_i) = SOFT   -> trễ vẫn hợp lệ, chỉ bị tính lateness (phạt ở objective),
                               KHÔNG bị liệt vào violations.
- capacity  = HARD.
- route continuity = HARD (route phải bắt đầu từ đúng current_stop của vehicle;
                            mỗi order chỉ được phục vụ đúng 1 lần hoặc nằm trong unserved).

Plan format kỳ vọng:
{
  "routes": { "<vehicle_id>": ["<order_id>", "<order_id>", ...] },   # thứ tự ghé thăm
  "unserved": ["<order_id>", ...]
}
"""


def validate_instance(instance):
    """Kiểm tra cấu trúc dữ liệu instance (không liên quan đến plan)."""
    issues = []
    order_ids = [o["id"] for o in instance["orders"]]
    if len(order_ids) != len(set(order_ids)):
        issues.append("Trùng order id trong instance.")

    dm = instance["distance_matrix"]
    all_node_ids = {instance["depot"]["id"]} | set(order_ids) | {v["current_stop"] for v in instance["vehicles"]}
    for nid in all_node_ids:
        if nid not in dm:
            issues.append(f"Node '{nid}' không có hàng trong distance_matrix.")
            continue
        for other in all_node_ids:
            if other not in dm[nid]:
                issues.append(f"distance_matrix['{nid}'] thiếu cột đến '{other}'.")

    for o in instance["orders"]:
        if o["ready_time"] > o["deadline"]:
            issues.append(f"Order {o['id']}: ready_time ({o['ready_time']}) > deadline ({o['deadline']}).")
        if o["demand"] < 0:
            issues.append(f"Order {o['id']}: demand âm.")

    for v in instance["vehicles"]:
        if v["capacity"] < 0:
            issues.append(f"Vehicle {v['id']}: capacity âm.")
        if v["remaining_capacity"] > v["capacity"] + 1e-9:
            issues.append(f"Vehicle {v['id']}: remaining_capacity ({v['remaining_capacity']}) > capacity gốc ({v['capacity']}).")

    return issues


def active_order_ids(instance, planning_time=0.0):
    """Orders released by planning_time and not in a terminal state."""
    terminal = {"DELIVERED", "CANCELLED"}
    return {
        o["id"] for o in instance["orders"]
        if o["release_time"] <= planning_time and o["status"] not in terminal
    }


def simulate_route(vehicle, order_seq, instance):
    """
    Mô phỏng 1 route theo thứ tự order_seq (list order_id) của 1 vehicle.
    Trả về danh sách stop-event: [{order_id, arrival, wait, start_service, depart, lateness}, ...]
    và tổng travel_time của route.
    """
    orders_by_id = {o["id"]: o for o in instance["orders"]}
    dm = instance["distance_matrix"]

    events = []
    current_node = vehicle["current_stop"]
    current_time = vehicle["start_time"]
    total_travel = 0.0

    for oid in order_seq:
        o = orders_by_id[oid]
        travel = dm[current_node][oid]
        arrival = current_time + travel
        start_service = max(arrival, o["ready_time"], o["release_time"])  # không service trước release/ready
        wait = start_service - arrival
        lateness = max(0.0, start_service - o["deadline"])  # SOFT: chỉ ghi nhận, không chặn
        depart = start_service + o["service_time"]

        events.append({
            "order_id": oid, "arrival": arrival, "wait": wait,
            "start_service": start_service, "depart": depart, "lateness": lateness,
        })
        total_travel += travel
        current_node = oid
        current_time = depart

    # DVRPTW routes return to the depot; include this final leg in route cost.
    if order_seq:
        total_travel += dm[current_node][instance["depot"]["id"]]

    return events, total_travel


def validate_plan(instance, plan, planning_time=0.0):
    """
    Trả về:
    {
      "feasible": bool,
      "violations": [str, ...],       # chỉ chứa vi phạm HARD constraint
      "metrics": {
        "total_travel_time": float,
        "total_lateness": float,       # SOFT, chỉ để báo cáo/objective, không ảnh hưởng feasible
        "num_late_orders": int,
        "num_unserved": int,
        "vehicles_used": int,
      },
      "per_vehicle": { vehicle_id: [stop-event, ...] }
    }
    """
    violations = []
    orders_by_id = {o["id"]: o for o in instance["orders"]}
    vehicles_by_id = {v["id"]: v for v in instance["vehicles"]}

    all_order_ids = active_order_ids(instance, planning_time)
    served_ids = []
    for route in plan["routes"].values():
        served_ids.extend(route)
    unserved_ids = set(plan.get("unserved", []))

    # continuity / coverage: mỗi order đúng 1 lần (served hoặc unserved), không thiếu không thừa
    if len(served_ids) != len(set(served_ids)):
        violations.append("Có order bị lặp lại ở nhiều route hoặc trong cùng 1 route.")
    covered = set(served_ids) | unserved_ids
    missing = all_order_ids - covered
    if missing:
        violations.append(f"Order chưa được xử lý (không ở route nào, không trong unserved): {sorted(missing)}")
    extra = covered - all_order_ids
    if extra:
        violations.append(f"Plan tham chiếu order không tồn tại trong instance: {sorted(extra)}")
    overlap = set(served_ids) & unserved_ids
    if overlap:
        violations.append(f"Order vừa được route phục vụ vừa nằm trong unserved: {sorted(overlap)}")

    total_travel_time = 0.0
    total_lateness = 0.0
    num_late_orders = 0
    per_vehicle = {}
    vehicles_used = 0

    for vid, route in plan["routes"].items():
        if not route:
            per_vehicle[vid] = []
            continue
        if vid not in vehicles_by_id:
            violations.append(f"Plan tham chiếu vehicle không tồn tại: {vid}")
            continue

        vehicle = vehicles_by_id[vid]

        # HARD: vehicle UNAVAILABLE không được nhận order (business invariant, Mục 4.5)
        if vehicle["status"] == "UNAVAILABLE":
            violations.append(f"Vehicle {vid}: đang UNAVAILABLE nhưng được gán {len(route)} order trong plan.")

        events, travel = simulate_route(vehicle, route, instance)
        per_vehicle[vid] = events
        vehicles_used += 1
        total_travel_time += travel

        # HARD: capacity — so với remaining_capacity (Q_k còn lại tại snapshot này),
        # KHÔNG phải capacity gốc, đúng Problem Specification v1 Mục 1.
        load = sum(orders_by_id[oid]["demand"] for oid in route)
        if load > vehicle["remaining_capacity"] + 1e-9:
            violations.append(
                f"Vehicle {vid}: tổng demand {load} vượt remaining_capacity {vehicle['remaining_capacity']}."
            )

        for ev in events:
            if ev["arrival"] < orders_by_id[ev["order_id"]]["ready_time"] - 1e-9 and ev["wait"] < -1e-9:
                # về lý thuyết không thể xảy ra vì start_service = max(arrival, ready_time),
                # giữ kiểm tra này như một invariant an toàn (defensive check)
                violations.append(f"Order {ev['order_id']}: được service trước ready_time (lỗi mô phỏng).")
            if ev["lateness"] > 1e-9:
                num_late_orders += 1
                total_lateness += ev["lateness"]

    metrics = {
        "total_travel_time": round(total_travel_time, 3),
        "total_lateness": round(total_lateness, 3),
        "num_late_orders": num_late_orders,
        "num_unserved": len(unserved_ids & all_order_ids),
        "vehicles_used": vehicles_used,
    }

    return {
        "feasible": len(violations) == 0,
        "violations": violations,
        "metrics": metrics,
        "per_vehicle": per_vehicle,
    }
