"""
normalize_amazon.py — đọc route_data.json + package_data.json + travel_times.json
(đúng field của 2021 Amazon Last Mile Routing Research Challenge) cho MỘT route_id,
trả về canonical instance schema (schema/instance_schema.json).

Quy tắc mapping (ghi rõ vì dataset gốc không có sẵn khái niệm "order" VRPTW):
- Stop có type == "Station"  -> depot.
- Stop có type == "Dropoff"  -> 1 order, demand = tổng thể tích (cm3) các package
  tại stop đó (depth_cm * height_cm * width_cm), vì Amazon dùng executor_capacity_cm3
  làm đơn vị capacity (thể tích), không phải trọng lượng/số kiện.
- ready_time / deadline (giây, tính từ mốc departure_time_utc của route = t=0):
    - Nếu KHÔNG package nào ở stop có time_window -> ready=0, due=SENTINEL_NO_DUE
      (rất lớn) để soft-penalty ~ 0, đúng nguyên tắc "không có time window nghĩa
      là gần như không ràng buộc thời gian" đã ghi trong Problem Specification v1.
- Nếu có -> ready = start_time_utc muộn nhất, due = end_time_utc sớm nhất
  trong các package có time window tại stop đó, tức phần giao của các cửa sổ.
- service_time = tổng planned_service_time_seconds của mọi package tại stop.
- vehicle: dataset gốc là 1 route = 1 xe đã chạy sẵn (không phải fleet chưa gán)
  nên ở đây tạo đúng 1 vehicle ứng với route đó, capacity = executor_capacity_cm3.

Hàm normalize_multi_route bên dưới phục vụ benchmark fleet thử nghiệm. Đây là
instance tổng hợp từ nhiều route đã có lịch chạy riêng: solver được phép phân
bổ lại các đơn giữa xe. Travel time giữa hai route khác nhau là ước lượng từ
tọa độ, không phải dữ liệu đường đi Amazon; cần nêu rõ khi diễn giải kết quả.
"""
import json
from datetime import datetime
from domain.entities import RoutingSnapshot

SENTINEL_NO_DUE = 999999.0


def _parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def normalize_route(route_id, route_data, package_data, travel_times):
    route = route_data[route_id]
    stops = route["stops"]
    departure_dt = _parse_dt(f'{route["date_YYYY_MM_DD"]} {route["departure_time_utc"]}')

    station_id = next(sid for sid, s in stops.items() if s["type"] == "Station")
    depot = {"id": station_id, "x": stops[station_id]["lng"], "y": stops[station_id]["lat"]}

    orders = []
    pkgs_by_stop = package_data.get(route_id, {})
    for stop_id, stop in stops.items():
        if stop["type"] != "Dropoff":
            continue
        pkgs = pkgs_by_stop.get(stop_id, {})

        demand = 0.0
        service_time = 0.0
        tw_starts, tw_ends = [], []
        for pkg in pkgs.values():
            dims = pkg["dimensions"]
            demand += dims["depth_cm"] * dims["height_cm"] * dims["width_cm"]
            service_time += pkg.get("planned_service_time_seconds", 0.0) or 0.0
            tw = pkg.get("time_window", {})
            if (isinstance(tw.get("start_time_utc"), str)
                    and isinstance(tw.get("end_time_utc"), str)):
                tw_starts.append(_parse_dt(tw["start_time_utc"]))
                tw_ends.append(_parse_dt(tw["end_time_utc"]))

        if tw_starts:
            ready = (max(tw_starts) - departure_dt).total_seconds()
            due = (min(tw_ends) - departure_dt).total_seconds()
            ready = max(0.0, ready)  # không cho ready âm so với lúc xe xuất phát
        else:
            ready, due = 0.0, SENTINEL_NO_DUE

        orders.append({
            "id": stop_id,
            "x": stop["lng"], "y": stop["lat"],
            "demand": float(demand),
            "release_time": 0.0,  # snapshot tĩnh 1 lần (đúng bản chất route đã chạy xong) -> biết từ đầu
            "ready_time": float(ready),
            "deadline": float(due),
            "service_time": float(service_time),
            "status": "PENDING",
        })

    capacity = float(route["executor_capacity_cm3"])
    vehicle = {
        "id": route_id,
        "capacity": capacity,
        "remaining_capacity": capacity,  # snapshot đầu (t=0) -> chưa chở gì, bằng capacity gốc
        "status": "AVAILABLE",
        "current_stop": station_id,
        "start_time": 0.0,
    }

    raw_time_matrix = travel_times[route_id]
    time_matrix = {i: {j: float(t) for j, t in row.items()} for i, row in raw_time_matrix.items()}

    canonical_data = {
        "instance_id": route_id,
        "scenario_id": route_id,  # instance tĩnh độc lập -> scenario_id = instance_id
        "matrix_version": 0,
        "source": "amazon",
        "depot": depot,
        "vehicles": [vehicle],
        "orders": orders,
        "time_matrix": time_matrix,
    }
    return RoutingSnapshot.from_dict(canonical_data)


def normalize_route_fleet(route_id, num_vehicles, route_data, package_data,
                          travel_times, max_orders=None):
    """Tạo fleet tổng hợp bằng cách nhân bản xe của một route Amazon.

    Các order và time matrix lấy nguyên trạng từ đúng một route. Order không bị
    nhân bản; nhiều xe cùng depot/capacity sẽ cùng phục vụ một tập order chung.
    Nếu ``max_orders`` được đặt, cắt tập order một lần rồi rút gọn matrix tương ứng.
    """
    if num_vehicles <= 0:
        raise ValueError("num_vehicles phải lớn hơn 0.")
    if max_orders is not None and max_orders <= 0:
        raise ValueError("max_orders phải lớn hơn 0 nếu được chỉ định.")
    if route_id not in route_data:
        raise KeyError(f"Không tìm thấy route_id trong route_data: {route_id}")
    if route_id not in travel_times:
        raise KeyError(f"Không tìm thấy travel-time matrix cho route_id: {route_id}")

    base = normalize_route(route_id, route_data, package_data, travel_times).to_dict()
    if max_orders is not None:
        base["orders"] = base["orders"][:max_orders]

    node_ids = [base["depot"]["id"]] + [order["id"] for order in base["orders"]]
    raw_matrix = base["time_matrix"]
    missing = [node for node in node_ids if node not in raw_matrix]
    if missing:
        raise ValueError(f"Travel-time matrix của route {route_id} thiếu node: {missing[:5]}")
    base["time_matrix"] = {
        source: {target: float(raw_matrix[source][target]) for target in node_ids
                 if target in raw_matrix[source]}
        for source in node_ids
    }
    incomplete = [(source, target) for source in node_ids
                  for target in node_ids if target not in base["time_matrix"][source]]
    if incomplete:
        raise ValueError(
            f"Travel-time matrix của route {route_id} thiếu cặp node "
            f"{incomplete[0][0]} -> {incomplete[0][1]}"
        )

    template = base["vehicles"][0]
    base["vehicles"] = [
        {**template, "id": f"{route_id}:vehicle_{index + 1}"}
        for index in range(num_vehicles)
    ]
    base["instance_id"] = f"{route_id}_fleet_{num_vehicles}"
    base["scenario_id"] = base["instance_id"]
    return RoutingSnapshot.from_dict(base)



def normalize_multi_route(route_ids, route_data, package_data, travel_times,
                          instance_id=None, max_orders_per_vehicle=None):
    """Gộp nhiều route_id cùng station thành 1 fleet instance.

    Chiến lược:
    - Depot = station chung (phải cùng station_id; nếu khác thì dùng station của route đầu).
    - Mỗi route_id → 1 vehicle; capacity và stops giữ nguyên theo route gốc.
    - Stop ID được prefix ``<route_id>:<stop_id>`` để tránh đụng độ giữa các route
      (Amazon dùng stop ID cực ngắn như 'AB', 'AE' dễ trùng nhau).
    - Time matrix: merge tất cả sub-matrix của từng route lại. Travel time
      giữa stop thuộc 2 route khác nhau KHÔNG có trong dữ liệu gốc → dùng
      Euclidean distance (lat/lng) làm fallback proxy (tốc độ ~11 m/s ≈ 40 km/h).
    - Nếu ``max_orders_per_vehicle`` được đặt, cắt bớt order của mỗi xe để
      instance nhỏ hơn cho test nhanh.
    """
    import math

    def _euclidean_sec(lat1, lng1, lat2, lng2, speed_mps=11.0):
        # Haversine đơn giản hoá: 1 độ ≈ 111_000 m
        dy = (lat2 - lat1) * 111_000
        dx = (lng2 - lng1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
        return math.hypot(dx, dy) / speed_mps

    if not route_ids:
        raise ValueError("Cần ít nhất một route_id để tạo fleet Amazon.")
    if len(set(route_ids)) != len(route_ids):
        raise ValueError("route_ids bị trùng; mỗi route chỉ được ánh xạ thành một xe.")

    missing_routes = [rid for rid in route_ids if rid not in route_data]
    if missing_routes:
        raise KeyError(f"Không tìm thấy route_id trong route_data: {missing_routes}")
    missing_matrices = [rid for rid in route_ids if rid not in travel_times]
    if missing_matrices:
        raise KeyError(f"Không tìm thấy travel-time matrix cho route_id: {missing_matrices}")
    if max_orders_per_vehicle is not None and max_orders_per_vehicle <= 0:
        raise ValueError("max_orders_per_vehicle phải lớn hơn 0 nếu được chỉ định.")

    # Các xe trong một instance phải cùng depot vật lý; kiểm tra ID và tọa độ.
    first_route = route_data[route_ids[0]]
    first_stops = first_route["stops"]
    first_stations = [(sid, stop) for sid, stop in first_stops.items()
                      if stop.get("type") == "Station"]
    if len(first_stations) != 1:
        raise ValueError(
            f"Route {route_ids[0]} phải có đúng một Station; "
            f"tìm thấy {len(first_stations)}."
        )
    station_id, depot_stop = first_stations[0]
    depot = {"id": station_id, "x": depot_stop["lng"], "y": depot_stop["lat"]}
    depot_coord = (depot_stop["lat"], depot_stop["lng"])
    for rid in route_ids[1:]:
        stations = [(sid, stop) for sid, stop in route_data[rid]["stops"].items()
                    if stop.get("type") == "Station"]
        if len(stations) != 1:
            raise ValueError(f"Route {rid} phải có đúng một Station; tìm thấy {len(stations)}.")
        other_id, other = stations[0]
        if other_id != station_id:
            raise ValueError(
                f"Route {rid} không cùng depot với route đầu (cần: {station_id}, thực tế: {other_id}); "
                "hãy chọn các route cùng station."
            )

    vehicles = []
    all_orders = []
    # node_coords: id → (lat, lng) để tính cross-route travel
    node_coords = {station_id: depot_coord}

    for route_id in route_ids:
        route = route_data[route_id]
        stops = route["stops"]
        departure_dt = _parse_dt(f'{route["date_YYYY_MM_DD"]} {route["departure_time_utc"]}')
        pkgs_by_stop = package_data.get(route_id, {})

        orders_for_vehicle = []
        for stop_id, stop in stops.items():
            if stop["type"] != "Dropoff":
                continue
            pkgs = pkgs_by_stop.get(stop_id, {})
            demand = 0.0
            service_time = 0.0
            tw_starts, tw_ends = [], []
            for pkg in pkgs.values():
                dims = pkg["dimensions"]
                demand += dims["depth_cm"] * dims["height_cm"] * dims["width_cm"]
                service_time += pkg.get("planned_service_time_seconds", 0.0) or 0.0
                tw = pkg.get("time_window", {})
                if isinstance(tw.get("start_time_utc"), str) and isinstance(tw.get("end_time_utc"), str):
                    tw_starts.append(_parse_dt(tw["start_time_utc"]))
                    tw_ends.append(_parse_dt(tw["end_time_utc"]))

            if tw_starts:
                ready = max(0.0, (max(tw_starts) - departure_dt).total_seconds())
                due = (min(tw_ends) - departure_dt).total_seconds()
            else:
                ready, due = 0.0, SENTINEL_NO_DUE

            # prefix stop_id để tránh đụng độ giữa các route
            global_stop_id = f"{route_id}:{stop_id}"
            node_coords[global_stop_id] = (stop["lat"], stop["lng"])
            orders_for_vehicle.append({
                "id": global_stop_id,
                "x": stop["lng"], "y": stop["lat"],
                "demand": float(demand),
                "release_time": 0.0,
                "ready_time": float(ready),
                "deadline": float(due),
                "service_time": float(service_time),
                "status": "PENDING",
            })

        if max_orders_per_vehicle:
            orders_for_vehicle = orders_for_vehicle[:max_orders_per_vehicle]

        all_orders.extend(orders_for_vehicle)
        cap = float(route["executor_capacity_cm3"])
        vehicles.append({
            "id": route_id,
            "capacity": cap,
            "remaining_capacity": cap,
            "status": "AVAILABLE",
            "current_stop": station_id,
            "start_time": 0.0,
        })

    # Xây time matrix: ưu tiên dữ liệu gốc trong từng route, fallback Euclidean cross-route
    all_node_ids = [station_id] + [o["id"] for o in all_orders]

    # Bản đồ route gốc: global_stop_id → (route_id, local_stop_id)
    global_to_local = {}
    for route_id in route_ids:
        for stop_id in route_data[route_id]["stops"]:
            global_to_local[f"{route_id}:{stop_id}"] = (route_id, stop_id)
    global_to_local[station_id] = (None, station_id)  # depot không prefix

    def _local_id(gid, rid_context):
        """Trả về local ID trong travel_times của route rid_context."""
        if gid == station_id:
            return station_id
        r, local = global_to_local.get(gid, (None, gid))
        if r == rid_context:
            return local
        return None  # không có trong route này

    # Pre-load travel_times sub-matrix cho từng route
    tt = {rid: travel_times[rid] for rid in route_ids if rid in travel_times}

    time_matrix = {}
    for from_gid in all_node_ids:
        time_matrix[from_gid] = {}
        from_rid, from_local = global_to_local.get(from_gid, (None, from_gid))
        from_coord = node_coords.get(from_gid, depot_coord)
        for to_gid in all_node_ids:
            if from_gid == to_gid:
                time_matrix[from_gid][to_gid] = 0.0
                continue
            to_rid, to_local = global_to_local.get(to_gid, (None, to_gid))
            to_coord = node_coords.get(to_gid, depot_coord)

            # Thử tra cứu trong travel_times của route nguồn
            found = None
            if from_rid and from_rid in tt:
                row = tt[from_rid].get(from_local, {})
                if to_local and to_gid != station_id:
                    # to_local chỉ hợp lệ nếu cùng route
                    if to_rid == from_rid:
                        found = row.get(to_local)
                    elif to_gid == station_id:
                        found = row.get(station_id)
                else:
                    found = row.get(to_local)
            if found is None and from_gid == station_id and to_rid and to_rid in tt:
                # depot → stop: tra trong route của to
                found = tt[to_rid].get(station_id, {}).get(to_local)
            if found is None:
                # fallback: Euclidean
                found = _euclidean_sec(*from_coord, *to_coord)

            time_matrix[from_gid][to_gid] = float(found)

    iid = instance_id or ("amazon_fleet_" + "_".join(r[-8:] for r in route_ids))
    canonical_data = {
        "instance_id": iid,
        "scenario_id": iid,
        "matrix_version": 0,
        "source": "amazon",
        "depot": depot,
        "vehicles": vehicles,
        "orders": all_orders,
        "time_matrix": time_matrix,
    }
    return RoutingSnapshot.from_dict(canonical_data)


if __name__ == "__main__":

    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else "data/amazon_sample"
    route_data = json.load(open(f"{base}/route_data.json"))
    package_data = json.load(open(f"{base}/package_data.json"))
    travel_times = json.load(open(f"{base}/travel_times.json"))

    route_id = sys.argv[2] if len(sys.argv) > 2 else next(iter(route_data))
    inst = normalize_route(route_id, route_data, package_data, travel_times)
    print(json.dumps(inst.to_dict(), indent=2, ensure_ascii=False))
