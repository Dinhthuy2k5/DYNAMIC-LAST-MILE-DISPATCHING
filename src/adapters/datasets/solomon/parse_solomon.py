"""
parse_solomon.py — đọc file định dạng Solomon VRPTW (.txt) và trả về canonical
instance schema (schema/instance_schema.json).

Quy ước Solomon chuẩn:
- Customer 0 = depot.
- File gốc không có travel time; project dùng khoảng cách Euclidean làm proxy,
  theo giả định tốc độ 1 đơn vị tọa độ trên một đơn vị thời gian.
- READY TIME / DUE DATE của customer 0 (depot) là horizon chung, không phải
  time window của một order.
"""
import math
import re
from domain.entities import RoutingSnapshot


def _euclidean(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def parse_solomon_file(path, instance_id=None):
    with open(path, "r") as f:
        raw_lines = [ln.rstrip("\n") for ln in f]

    non_empty = [ln for ln in raw_lines if ln.strip() != ""]
    name = non_empty[0].strip()

    # tìm dòng "NUMBER     CAPACITY" rồi lấy dòng số liệu ngay sau đó
    veh_header_idx = next(i for i, ln in enumerate(non_empty) if ln.strip().upper().startswith("NUMBER"))
    veh_number, veh_capacity = map(int, non_empty[veh_header_idx + 1].split())

    # tìm dòng header CUST NO. ... rồi đọc toàn bộ dòng số liệu phía sau
    cust_header_idx = next(i for i, ln in enumerate(non_empty) if ln.strip().upper().startswith("CUST NO"))

    customers = []  # (id:int, x, y, demand, ready, due, service)
    for ln in non_empty[cust_header_idx + 1:]:
        parts = ln.split()
        if len(parts) != 7:
            continue  # bỏ qua dòng rác/không đúng 7 cột
        if not re.match(r"^-?\d+$", parts[0]):
            continue
        cust_no, x, y, demand, ready, due, service = map(int, parts)
        customers.append((cust_no, x, y, demand, ready, due, service))

    if not customers or customers[0][0] != 0:
        raise ValueError(f"{path}: không tìm thấy depot (customer 0) hoặc dữ liệu sai định dạng")

    depot_row = customers[0]
    depot = {"id": "0", "x": float(depot_row[1]), "y": float(depot_row[2])}

    orders = []
    for row in customers[1:]:
        cust_no, x, y, demand, ready, due, service = row
        orders.append({
            "id": str(cust_no),
            "x": float(x), "y": float(y),
            "demand": float(demand),
            "release_time": 0.0,  # Solomon: mọi order biết từ đầu (instance tĩnh)
            "ready_time": float(ready),
            "deadline": float(due),
            "service_time": float(service),
            "status": "PENDING",
        })

    vehicles = [
        {
            "id": f"V{k+1}", "capacity": float(veh_capacity), "remaining_capacity": float(veh_capacity),
            "status": "AVAILABLE", "current_stop": "0", "start_time": 0.0,
        }
        for k in range(veh_number)
    ]

    # Solomon không có ma trận thời gian riêng; dùng khoảng cách Euclid làm proxy
    # travel time theo quy ước hiện tại (tốc độ giả định bằng 1 đơn vị tọa độ/đơn vị thời gian).
    nodes = [("0", (depot["x"], depot["y"]))] + [(o["id"], (o["x"], o["y"])) for o in orders]
    time_matrix = {}
    for id_i, p_i in nodes:
        time_matrix[id_i] = {}
        for id_j, p_j in nodes:
            time_matrix[id_i][id_j] = 0.0 if id_i == id_j else _euclidean(p_i, p_j)

    iid = instance_id or name
    canonical_data = {
        "instance_id": iid,
        "scenario_id": iid,  # instance tĩnh độc lập -> scenario_id = instance_id
        "matrix_version": 0,
        "source": "solomon",
        "depot": depot,
        "vehicles": vehicles,
        "orders": orders,
        "time_matrix": time_matrix,
    }
    return RoutingSnapshot.from_dict(canonical_data)


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/solomon/SAMPLE_SOLOMON_FORMAT_15.txt"
    inst = parse_solomon_file(path)
    print(json.dumps(inst.to_dict(), indent=2, ensure_ascii=False))
