"""route_geometry_service.py — lấy hình học (polyline) + distance thật cho FE vẽ map.

CHỦ Ý THIẾT KẾ: KHÔNG tính geometry cho mọi cặp node (O(N^2), lãng phí — phần
lớn cặp không bao giờ xuất hiện trong plan thật). Chỉ gọi routing_client cho
CÁC CẠNH THỰC SỰ CÓ TRONG PLAN đã solve xong — O(num_orders + num_vehicles).

Đây là lý do route_matrix (dùng cho optimizer, time_matrix) và geometry
(dùng cho FE, distance + polyline) được tách thành 2 service khác nhau, gọi ở
2 THỜI ĐIỂM khác nhau: time_matrix cần CÓ TRƯỚC khi solve (current_state.py
dùng nó), geometry chỉ cần SAU khi đã có plan.

Cache theo (from_id, to_id) vì giữa 2 lần re-plan liên tiếp (W4+), phần lớn
cạnh không đổi — không cần gọi lại routing_client cho các cạnh đã có.
"""
from domain.entities import snapshot_payload


def _node_coords(instance):
    """node_id -> (lat, lng), suy từ depot + orders trong snapshot.

    Vehicle.current_stop KHÔNG tự có tọa độ trong domain model hiện tại (chỉ
    là ID) — nếu nó không trùng depot/order nào (vị trí xe live, xem
    application/planning/live_position.py), người gọi phải tự bổ sung qua
    tham số extra_coords của fetch_geometry_for_plan().
    """
    coords = {instance["depot"]["id"]: (instance["depot"]["y"], instance["depot"]["x"])}
    for order in instance["orders"]:
        coords[order["id"]] = (order["y"], order["x"])
    return coords


def _plan_edges(plan, instance):
    """Trích các cạnh (from_id, to_id) THỰC SỰ xuất hiện trong plan, theo đúng
    quy ước route khép kín của validator.py: vehicle.current_stop -> stop đầu
    -> ... -> stop cuối -> depot."""
    vehicles_by_id = {v["id"]: v for v in instance["vehicles"]}
    depot_id = instance["depot"]["id"]
    edges = []

    for vid, route in plan["routes"].items():
        if not route:
            continue
        vehicle = vehicles_by_id.get(vid)
        current = vehicle["current_stop"] if vehicle else depot_id
        for stop_id in route:
            edges.append((current, stop_id))
            current = stop_id
        edges.append((current, depot_id))

    return edges


def fetch_geometry_for_plan(plan, instance, routing_client, cache=None, extra_coords=None):
    """Trả về cache đã điền {(from_id,to_id): {"distance_m","duration_s","geometry"}}
    cho mọi cạnh trong plan. extra_coords: {node_id: (lat,lng)} cho node không
    có trong depot/orders (vd vị trí xe live chưa resolve)."""
    instance = snapshot_payload(instance)
    cache = cache if cache is not None else {}
    coords = _node_coords(instance)
    if extra_coords:
        coords.update(extra_coords)

    edges = _plan_edges(plan, instance)
    missing_coords = [nid for edge in edges for nid in edge if nid not in coords]
    if missing_coords:
        raise ValueError(
            f"Không rõ tọa độ cho node: {sorted(set(missing_coords))}. "
            "Nếu đây là vị trí xe live, truyền qua extra_coords={node_id: (lat,lng)}."
        )

    for from_id, to_id in edges:
        key = (from_id, to_id)
        if key in cache:
            continue
        result = routing_client.directions([coords[from_id], coords[to_id]])
        cache[key] = {
            "distance_m": result.distance_m,
            "duration_s": result.duration_s,
            "geometry": result.geometry,
        }

    return cache


def plan_total_distance_m(plan, instance, geometry_cache):
    """Tổng distance thật (mét) của plan, dùng geometry_cache đã fetch sẵn —
    bổ sung cho total_travel_time (giây, dùng trong validator) khi cần hiển
    thị quãng đường thay vì thời gian."""
    instance = snapshot_payload(instance)
    edges = _plan_edges(plan, instance)
    total = 0.0
    for edge in edges:
        if edge not in geometry_cache:
            raise KeyError(f"Cạnh {edge} chưa có trong geometry_cache — gọi fetch_geometry_for_plan trước.")
        total += geometry_cache[edge]["distance_m"]
    return total
