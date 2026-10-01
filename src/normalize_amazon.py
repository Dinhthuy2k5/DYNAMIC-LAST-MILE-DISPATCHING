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

GIỚI HẠN CHƯA LÀM Ở W2 (cố ý, ngoài scope deliverable W2 "Normalize Amazon;
instance schema; Solomon subset; baseline no-replan + Greedy Insertion;
feasibility validator"): gộp nhiều route_id cùng station thành một fleet
nhiều vehicle thật sự cho dynamic scenario. Cần làm việc này trước khi dùng
dữ liệu Amazon cho W4 trở đi (mô phỏng dynamic event cần > 1 vehicle để New
Order/Breakdown có ý nghĩa) — ghi chú lại để không quên, không tự ý mở rộng
scope ở đây.
"""
import json
from datetime import datetime

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

    dm_raw = travel_times[route_id]
    distance_matrix = {i: {j: float(t) for j, t in row.items()} for i, row in dm_raw.items()}

    return {
        "instance_id": route_id,
        "scenario_id": route_id,  # instance tĩnh độc lập -> scenario_id = instance_id
        "source": "amazon",
        "depot": depot,
        "vehicles": [vehicle],
        "orders": orders,
        "distance_matrix": distance_matrix,
    }


if __name__ == "__main__":
    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else "data/amazon_sample"
    route_data = json.load(open(f"{base}/route_data.json"))
    package_data = json.load(open(f"{base}/package_data.json"))
    travel_times = json.load(open(f"{base}/travel_times.json"))

    route_id = sys.argv[2] if len(sys.argv) > 2 else next(iter(route_data))
    inst = normalize_route(route_id, route_data, package_data, travel_times)
    print(json.dumps(inst, indent=2, ensure_ascii=False))
