"""live_position.py — vá time_matrix khi vị trí xe là tọa độ GPS tùy ý, KHÔNG
trùng bất kỳ node nào sẵn có trong snapshot (depot/order).

Đây CHƯA PHẢI vấn đề của build_current_state() (application/planning/
current_state.py) — hàm đó giả định vehicle["current_stop"] ĐÃ LÀ một key hợp
lệ trong time_matrix (xem docstring của nó). Module này chạy TRƯỚC
build_current_state(), là nơi DUY NHẤT trong hệ thống gọi routing_client để
"dạy" cho time_matrix biết thêm 1 điểm mới — build_current_state() vẫn giữ
nguyên tắc KHÔNG phụ thuộc network I/O.

Dùng khi nào: snapshot tĩnh ban đầu (W2/W3) không cần — mọi xe ở đúng depot,
đã có sẵn trong time_matrix. Chỉ cần khi mô phỏng/vận hành thật (W4+) báo vị
trí xe bằng GPS giữa route, không phải 1 trong các stop_id đã biết.
"""
from domain.entities import snapshot_payload


def _live_position_id(vehicle_id, reserved_ids):
    candidate = f"__live_position__:{vehicle_id}"
    while candidate in reserved_ids:
        candidate += ":_"
    reserved_ids.add(candidate)
    return candidate


_LIVE_PREFIX = "__live_position__:"


def patch_time_matrix_for_live_vehicles(instance, vehicle_positions, routing_client):
    """vehicle_positions: {vehicle_id: (lat, lng)} — CHỈ cho các xe có vị trí
    live chưa có trong time_matrix. Xe nào current_stop đã khớp depot/order
    thì không cần đưa vào đây.

    Trả về instance dict MỚI (không sửa instance gốc) với:
    - time_matrix đã có đủ hàng/cột 2 chiều giữa vị trí live <-> mọi node cũ
      (và giữa các vị trí live với nhau, nếu >1 xe live cùng lúc).
    - vehicles[*]["current_stop"] được set đúng bằng ID ảo mới cho các xe
      trong vehicle_positions.
    - matrix_version tăng thêm 1 — plan tạo ra SAU lần vá này phải mang đúng
      version mới, không được lẫn với plan dựa trên matrix trước khi vá.

    HÀM NÀY KHÔNG CÓ TRẠNG THÁI GIỮA CÁC LẦN GỌI: nếu instance truyền vào đã
    từng được vá ở lần gọi trước (còn sót node "__live_position__:..." trong
    time_matrix từ snapshot cũ), các node đó bị LOẠI BỎ trước khi tính toán —
    mỗi lần vá luôn xuất phát lại từ baseline chỉ gồm depot + order (tọa độ
    luôn resolve được), tránh lỗi không tìm thấy tọa độ cho node ảo cũ. Muốn
    patch cho vehicle nào ở lần gọi này, phải đưa vehicle đó vào
    vehicle_positions — không tự "nhớ" lại vị trí live của lần trước.

    Sau khi gọi hàm này, instance trả về sẵn sàng đưa thẳng vào
    build_current_state() như bình thường.
    """
    if not vehicle_positions:
        return instance

    instance = dict(snapshot_payload(instance))

    # Loại bỏ mọi node "__live_position__:*" còn sót từ lần vá trước (cả làm
    # key lẫn làm cột trong các hàng khác) — baseline luôn chỉ gồm depot/order,
    # tọa độ luôn resolve được qua instance["depot"]/instance["orders"].
    time_matrix = {
        k: {k2: v2 for k2, v2 in v.items() if not k2.startswith(_LIVE_PREFIX)}
        for k, v in instance["time_matrix"].items()
        if not k.startswith(_LIVE_PREFIX)
    }

    existing_ids = list(time_matrix.keys())
    existing_coords = [
        (instance["depot"]["y"], instance["depot"]["x"])
        if nid == instance["depot"]["id"] else
        next((o["y"], o["x"]) for o in instance["orders"] if o["id"] == nid)
        for nid in existing_ids
    ] if existing_ids else []

    reserved_ids = set(existing_ids)
    live_ids = []
    live_coords = []
    vid_to_live_id = {}
    for vid, coord in vehicle_positions.items():
        live_id = _live_position_id(vid, reserved_ids)
        vid_to_live_id[vid] = live_id
        live_ids.append(live_id)
        live_coords.append(coord)

    # 2 lệnh gọi có hướng (live->existing, existing->live) thay vì 1 ma trận
    # đầy đủ (live+existing)^2 — tránh tính lại existing->existing vốn đã có sẵn.
    if existing_ids:
        live_to_existing = routing_client.matrix(live_coords, existing_coords)
        existing_to_live = routing_client.matrix(existing_coords, live_coords)
    else:
        live_to_existing = existing_to_live = None

    # live <-> live (khi có >1 xe live cùng lúc)
    live_to_live = routing_client.matrix(live_coords, live_coords) if len(live_ids) > 1 else None

    for i, lid in enumerate(live_ids):
        time_matrix.setdefault(lid, {})
        time_matrix[lid][lid] = 0.0
        if existing_ids:
            for j, eid in enumerate(existing_ids):
                time_matrix[lid][eid] = live_to_existing.durations_s[i][j]
                time_matrix.setdefault(eid, {})[lid] = existing_to_live.durations_s[j][i]
        if live_to_live:
            for j, lid2 in enumerate(live_ids):
                if lid != lid2:
                    time_matrix[lid][lid2] = live_to_live.durations_s[i][j]

    instance["time_matrix"] = time_matrix
    instance["matrix_version"] = instance.get("matrix_version", 0) + 1
    instance["vehicles"] = [
        {**v, "current_stop": vid_to_live_id[v["id"]]} if v["id"] in vid_to_live_id else v
        for v in instance["vehicles"]
    ]
    return instance
