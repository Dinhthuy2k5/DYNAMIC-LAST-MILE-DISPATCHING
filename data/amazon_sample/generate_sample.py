"""
Sinh route_data.json / package_data.json / travel_times.json ĐÚNG CẤU TRÚC FIELD
của bộ 2021 Amazon Last Mile Routing Research Challenge (đã tra cứu qua Amazon
Science + AWS Open Data Registry: route_data.json, package_data.json,
travel_times.json, khóa theo route_id -> stop_id -> package_id).

QUAN TRỌNG — đây KHÔNG PHẢI dữ liệu driver thật của Amazon. Sandbox này không
có quyền truy cập bucket S3 "amazon-last-mile-challenges" (ngoài danh sách
domain được phép), nên không tải được ~3.1GB dữ liệu gốc. Dữ liệu ở đây là
synthetic, sinh đúng cấu trúc field thật để kiểm chứng normalize_amazon.py.

Khi có dữ liệu thật: tải bằng
    aws s3 sync --no-sign-request s3://amazon-last-mile-challenges/almrrc2021/ ./real_data/
rồi trỏ normalize_amazon.py vào 3 file route_data.json/package_data.json/travel_times.json
thật — không cần sửa code, vì field name đã khớp đúng theo tài liệu gốc.
"""
import json
import random

random.seed(20235437)

ROUTE_ID = "RouteID_SAMPLE01"
N_DROPOFFS = 10
STATION_CODE = "DHU1"
DATE = "2026-03-02"
DEPARTURE_TIME = "08:00:00"
CAPACITY_CM3 = 4247527  # đúng độ lớn thường thấy trong dataset thật (executor_capacity_cm3)

# ---- route_data.json ----
stops = {
    "StopID_STATION": {"lat": 47.6101, "lng": -122.2015, "type": "Station", "zone_id": None}
}
for i in range(1, N_DROPOFFS + 1):
    stops[f"StopID_{i:03d}"] = {
        "lat": round(47.60 + random.uniform(-0.05, 0.05), 6),
        "lng": round(-122.20 + random.uniform(-0.05, 0.05), 6),
        "type": "Dropoff",
        "zone_id": f"A-{random.randint(1,9)}.{random.choice('ABC')}",
    }

route_data = {
    ROUTE_ID: {
        "station_code": STATION_CODE,
        "date_YYYY_MM_DD": DATE,
        "departure_time_utc": DEPARTURE_TIME,
        "executor_capacity_cm3": CAPACITY_CM3,
        "route_score": "High",
        "stops": stops,
    }
}

# ---- package_data.json ----
package_data = {ROUTE_ID: {}}
for i in range(1, N_DROPOFFS + 1):
    stop_id = f"StopID_{i:03d}"
    n_pkg = random.randint(1, 3)
    pkgs = {}
    for p in range(1, n_pkg + 1):
        has_tw = random.random() < 0.4  # phần lớn stop KHÔNG có time window, đúng đặc điểm dataset thật
        if has_tw:
            start_h = random.randint(9, 15)
            tw = {
                "start_time_utc": f"{DATE} {start_h:02d}:00:00",
                "end_time_utc": f"{DATE} {start_h + 2:02d}:00:00",
            }
        else:
            tw = {"start_time_utc": None, "end_time_utc": None}
        pkgs[f"PackageID_{i:03d}_{p}"] = {
            "scan_status": "DELIVERED",
            "time_window": tw,
            "planned_service_time_seconds": random.choice([30, 45, 60, 90]),
            "dimensions": {
                "depth_cm": random.randint(10, 40),
                "height_cm": random.randint(10, 40),
                "width_cm": random.randint(10, 40),
            },
        }
    package_data[ROUTE_ID][stop_id] = pkgs

# ---- travel_times.json ----
# giữ đúng cấu trúc route_id -> stop_id -> stop_id -> seconds
node_ids = list(stops.keys())
coords = {sid: (s["lat"], s["lng"]) for sid, s in stops.items()}


def haversine_seconds(a, b):
    # xấp xỉ: 1 độ lat/lng ~ 111km, tốc độ trung bình xe tải trong khu dân cư ~ 25km/h
    import math
    dlat = (a[0] - b[0]) * 111.0
    dlng = (b[1] - a[1]) * 111.0 * math.cos(math.radians(a[0]))
    km = math.hypot(dlat, dlng)
    return round(km / 25.0 * 3600, 1)


travel_times = {ROUTE_ID: {}}
for i_id in node_ids:
    travel_times[ROUTE_ID][i_id] = {}
    for j_id in node_ids:
        travel_times[ROUTE_ID][i_id][j_id] = 0.0 if i_id == j_id else haversine_seconds(coords[i_id], coords[j_id])

with open("route_data.json", "w") as f:
    json.dump(route_data, f, indent=2)
with open("package_data.json", "w") as f:
    json.dump(package_data, f, indent=2)
with open("travel_times.json", "w") as f:
    json.dump(travel_times, f, indent=2)

print(f"Đã sinh route_data.json / package_data.json / travel_times.json cho {ROUTE_ID} "
      f"({N_DROPOFFS} dropoff stop)")
