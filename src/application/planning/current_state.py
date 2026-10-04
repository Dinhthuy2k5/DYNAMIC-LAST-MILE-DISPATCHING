"""Xây dựng biểu diễn đầu vào cho solver từ một snapshot vận hành.

ID node nghiệp vụ và ID node của solver được tách riêng. Mỗi xe khả dụng có
một virtual start node riêng để vị trí hiện tại không bị nhầm thành khách hàng,
kể cả khi xe đang ở đúng vị trí của khách hàng đó. Nếu xe đang trên đường, bộ
tạo snapshot phải cung cấp ID ``current_stop`` và cập nhật hàng/cột tương ứng
trong ma trận thời gian di chuyển trước khi gọi hàm này.
"""
from validation.validator import active_order_ids
from domain.entities import snapshot_payload


def _virtual_start_id(vehicle_id, reserved_ids):
    """Trả về ID node tổng hợp duy nhất, không trùng với ID nghiệp vụ."""
    candidate = f"__virtual_start__:{vehicle_id}"
    while candidate in reserved_ids:
        candidate += ":_"
    reserved_ids.add(candidate)
    return candidate


def _require_matrix_pairs(time_matrix, source_ids):
    """Báo lỗi rõ ràng nếu vị trí bắt đầu hiện tại không có dữ liệu ma trận."""
    for source in source_ids:
        if source not in time_matrix:
            raise ValueError(f"time_matrix thiếu hàng cho node nguồn '{source}'.")
        for target in source_ids:
            if target not in time_matrix[source]:
                raise ValueError(
                    f"time_matrix['{source}'] thiếu travel time đến '{target}'."
                )


def build_current_state(instance, planning_time=0.0, state_version=None):
    """Tạo danh sách đơn active, xe khả dụng, virtual start và ma trận cho solver.

    ``state_version`` là metadata điều phối (nhãn snapshot v trong mô hình),
    không phải quyết định định tuyến. Tham số truyền trực tiếp được ưu tiên
    hơn trường trong instance; instance tĩnh W2/W3 mặc định có version 0.
    """
    instance = snapshot_payload(instance)
    if state_version is None:
        state_version = instance.get("state_version", 0)
    if not isinstance(state_version, int) or isinstance(state_version, bool) or state_version < 0:
        raise ValueError("state_version phải là số nguyên không âm.")
    matrix_version = instance.get("matrix_version")
    if not isinstance(matrix_version, int) or isinstance(matrix_version, bool) or matrix_version < 0:
        raise ValueError("matrix_version phải là số nguyên không âm.")

    active_ids = active_order_ids(instance, planning_time)
    active_orders = [o for o in instance["orders"] if o["id"] in active_ids]
    source_vehicles = [v for v in instance["vehicles"] if v["status"] != "UNAVAILABLE"]

    depot_id = instance["depot"]["id"]
    source_by_solver_node = {depot_id: depot_id}
    for order in active_orders:
        if order["id"] == depot_id:
            raise ValueError("order.id không được trùng depot.id.")
        source_by_solver_node[order["id"]] = order["id"]

    reserved_ids = set(source_by_solver_node)
    vehicles = []
    start_node_by_vehicle = {}
    source_ids = {depot_id, *(o["id"] for o in active_orders)}

    for vehicle in source_vehicles:
        current_position_id = vehicle["current_stop"]
        source_ids.add(current_position_id)
        virtual_start_id = _virtual_start_id(vehicle["id"], reserved_ids)
        source_by_solver_node[virtual_start_id] = current_position_id
        start_node_by_vehicle[vehicle["id"]] = virtual_start_id

        # Thời điểm snapshot là cận dưới của thời gian xe; không cho xe rời vị
        # trí hiện tại trước thời điểm snapshot.
        vehicle_state = dict(vehicle)
        vehicle_state["start_time"] = max(float(vehicle["start_time"]), float(planning_time))
        vehicles.append(vehicle_state)

    raw_time_matrix = instance["time_matrix"]
    _require_matrix_pairs(raw_time_matrix, source_ids)

    node_ids = [depot_id]
    node_ids.extend(o["id"] for o in active_orders if o["id"] != depot_id)
    node_ids.extend(start_node_by_vehicle[v["id"]] for v in vehicles)

    # Tạo hàng/cột ma trận cho các virtual start ID chỉ dùng trong solver.
    # Đây chỉ là sao chép/ánh xạ lại, không phải ước lượng: dữ liệu ma trận của
    # current_stop phải mô tả sẵn thời gian đi từ/đến vị trí xe tại snapshot.
    solver_matrix = {
        solver_from: {
            solver_to: raw_time_matrix[source_by_solver_node[solver_from]][source_by_solver_node[solver_to]]
            for solver_to in node_ids
        }
        for solver_from in node_ids
    }

    return {
        "planning_time": float(planning_time),
        "state_version": state_version,
        "matrix_version": matrix_version,
        "depot_id": depot_id,
        "node_ids": node_ids,
        "start_node_by_vehicle": start_node_by_vehicle,
        "orders": active_orders,
        "vehicles": vehicles,
        "time_matrix": solver_matrix,
    }


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/normalized/solomon_sample_15.json"
    planning_time = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    instance = json.load(open(path))
    state = build_current_state(instance, planning_time)
    print(f"state_version={state['state_version']} | planning_time={planning_time} "
          f"| active orders={len(state['orders'])} | usable vehicles={len(state['vehicles'])} "
          f"| nodes={len(state['node_ids'])}")
