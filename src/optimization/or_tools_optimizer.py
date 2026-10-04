"""
or_tools_optimizer.py — Baseline B2 (static optimizer), đúng chốt ở Problem
Specification v1 Mục 5: OR-Tools Parallel Cheapest Insertion (first solution)
+ Guided Local Search (local search), weighted-sum Z = alpha*unserved +
beta*lateness + gamma*travel (Mục 4), với RouteChangeCost KHÔNG nằm trong
solver (đo ngoài, Mục 6 — chưa dùng ở W3 vì W3 là static, một lần solve,
chưa có "plan cũ" để so route-change).

Ranh giới trách nhiệm (Problem Specification v1 Mục 5, bảng OR-Tools vs
project):
- OR-Tools cung cấp: routing model, PARALLEL_CHEAPEST_INSERTION,
  GUIDED_LOCAL_SEARCH, time limit, soft-upper-bound cho deadline,
  disjunction cho phép bỏ qua node (unserved).
- Project tự thiết kế: current_state_builder (đã tách riêng ở
  current_state.py), mapping input/output giữa canonical schema <-> OR-Tools
  index, chọn tham số alpha/beta/gamma.

GHI CHÚ QUAN TRỌNG VỀ ALPHA/BETA/GAMMA: Problem Specification v1 Mục 4 chốt
CƠ CHẾ (weighted-sum, alpha >> beta >> gamma) nhưng KHÔNG chốt con số cụ thể
-- "sẽ được benchmark/sensitivity-test ở W7". Giá trị default dưới đây là
PLACEHOLDER hợp lý (alpha đủ lớn so với tổng travel cost tối đa có thể của
instance, beta là 1 hằng số cố định vừa phải), KHÔNG PHẢI con số đã tuned.
Đừng diễn giải các con số này là kết quả benchmark.

GHI CHÚ VỀ ĐƠN VỊ: OR-Tools dùng số nguyên cho mọi transit/cumul. Mọi giá trị
travel_time/demand/ready_time/deadline/service_time trong canonical schema
(có thể là số thực) được làm tròn về số nguyên gần nhất khi đưa vào solver —
chấp nhận được ở quy mô giây/mét của bài toán này, nhưng cần nhớ khi so sánh
độ chính xác tuyệt đối với Greedy Insertion (vốn tính bằng số thực).
"""
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from application.planning.current_state import build_current_state
from domain.entities import DeliveryPlan, snapshot_payload

GAMMA = 1.0  # trọng số travel cost — neo = 1, alpha/beta tính tương đối theo gamma này
DEFAULT_BETA = 10.0  # placeholder: 1 đơn vị thời gian trễ "đắt" bằng 10 đơn vị travel
DEFAULT_TIME_LIMIT_SEC = 5  # khớp khung "1-5s mỗi lần re-plan" đã chốt ở Problem Spec Mục 7
DEFAULT_SCALING_FACTOR = 100  # nhân 100 để bảo toàn 2 chữ số thập phân (vd Solomon: 14.14 -> 1414)


def solve_or_tools(instance, planning_time=0.0, beta=DEFAULT_BETA,
                    alpha=None, time_limit_sec=DEFAULT_TIME_LIMIT_SEC,
                    scaling_factor=DEFAULT_SCALING_FACTOR, state_version=None):
    """
    Trả về plan CÙNG FORMAT với greedy_insertion() — {"routes": {...}, "unserved": [...]}
    — để có thể validate_plan() y hệt baseline B1, so sánh trực tiếp.

    scaling_factor: Hệ số phóng đại trước khi round thành int64 cho OR-Tools.
      - Với Solomon (giá trị proxy Euclidean e.g. 14.14), scaling_factor=100 bảo toàn 2 chữ số thập phân.
      - Với Amazon (thời gian tính bằng giây nguyên, capacity cm3 lớn), scaling_factor=1 hoặc 100 đều chuẩn.
      - Objective weights (alpha, beta, gamma=1) được giữ đúng tỉ lệ tương đối khi scale.
    """
    instance = snapshot_payload(instance)
    state = build_current_state(instance, planning_time, state_version=state_version)

    def _candidate(routes, unserved):
        return DeliveryPlan.candidate(
            routes, unserved, state["state_version"], state["matrix_version"]
        ).to_candidate_dict()

    node_ids = state["node_ids"]
    orders_by_id = {o["id"]: o for o in state["orders"]}
    vehicles = state["vehicles"]
    n = len(node_ids)
    num_vehicles = len(vehicles)

    if num_vehicles == 0:
        # không còn xe khả dụng -> toàn bộ active order thành unserved, không gọi solver
        return _candidate({}, [o["id"] for o in state["orders"]])
    if not state["orders"]:
        return _candidate({v["id"]: [] for v in vehicles}, [])

    scale = float(scaling_factor)

    def _scale(x):
        return int(round(x * scale))

    def _round_int(x):
        return int(round(x))

    time_matrix = state["time_matrix"]
    travel_time_matrix = [[_scale(time_matrix[node_ids[i]][node_ids[j]]) for j in range(n)] for i in range(n)]

    service = [0] * n
    for idx, nid in enumerate(node_ids):
        if nid in orders_by_id:
            service[idx] = _scale(orders_by_id[nid]["service_time"])

    demand = [0] * n
    for idx, nid in enumerate(node_ids):
        if nid in orders_by_id:
            demand[idx] = _round_int(orders_by_id[nid]["demand"])

    # Mỗi xe bắt đầu tại một node chỉ dùng trong solver, tách biệt mọi khách hàng.
    starts = [node_ids.index(state["start_node_by_vehicle"][v["id"]]) for v in vehicles]
    ends = [node_ids.index(state["depot_id"])] * num_vehicles

    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # --- travel cost (gamma term) ---
    def travel_time_cb(i, j):
        return travel_time_matrix[manager.IndexToNode(i)][manager.IndexToNode(j)]
    travel_time_idx = routing.RegisterTransitCallback(travel_time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(travel_time_idx)

    # --- time dimension (ready_time hard lower-bound, deadline soft upper-bound = beta term) ---
    # QUAN TRỌNG: callback thời gian PHẢI tách riêng khỏi travel_time_cb — nếu dùng
    # chung 1 callback cho cả cost lẫn Time dimension, service_time sẽ bị cộng
    # nhầm vào travel cost (gamma), làm méo objective.
    def time_cb(i, j):
        fi, tj = manager.IndexToNode(i), manager.IndexToNode(j)
        return travel_time_matrix[fi][tj] + service[fi]
    time_idx = routing.RegisterTransitCallback(time_cb)

    max_start_time = max(_scale(v["start_time"]) for v in vehicles)
    horizon = max_start_time + sum(max(row) for row in travel_time_matrix) + sum(service) + _scale(10_000)
    routing.AddDimension(time_idx, horizon, horizon, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    # τ_k: chiều thời gian của mỗi route bắt đầu tại thời gian hiện tại của xe,
    # không dùng giá trị solver tự chọn hay thời điểm 0 của kịch bản.
    for vehicle_idx, vehicle in enumerate(vehicles):
        start_cumul = time_dim.CumulVar(routing.Start(vehicle_idx))
        tau_k = _scale(vehicle["start_time"])
        start_cumul.SetRange(tau_k, tau_k)

    for idx, nid in enumerate(node_ids):
        if nid not in orders_by_id:
            continue
        o = orders_by_id[nid]
        var_idx = manager.NodeToIndex(idx)
        ready = max(o["ready_time"], o["release_time"])  # HARD — đúng simulate_route trong validator.py
        time_dim.CumulVar(var_idx).SetMin(_scale(ready))
        time_dim.SetCumulVarSoftUpperBound(var_idx, _scale(o["deadline"]), _round_int(beta))  # SOFT

    # --- capacity dimension (HARD — theo remaining_capacity, không phải capacity gốc) ---
    def demand_cb(i):
        return demand[manager.IndexToNode(i)]
    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    capacities = [_round_int(v["remaining_capacity"]) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, capacities, True, "Capacity")

    # --- cho phép bỏ qua order (unserved, z_i=1) với penalty = alpha ---
    if alpha is None:
        alpha_scaled = _round_int(sum(max(row) for row in travel_time_matrix) * n * 10)  # đủ lớn so với mọi phương án travel
    else:
        alpha_scaled = _scale(alpha)
    for idx, nid in enumerate(node_ids):
        if nid in orders_by_id:
            routing.AddDisjunction([manager.NodeToIndex(idx)], alpha_scaled)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(time_limit_sec)

    solution = routing.SolveWithParameters(params)

    if solution is None:
        # Solver không tìm được lời giải nào (kể cả bỏ qua order) trong time_limit
        # -> coi toàn bộ active order là unserved, đúng tinh thần "fail-safe"
        # (không bao giờ để hệ thống crash vì solver thất bại).
        return _candidate(
            {v["id"]: [] for v in vehicles}, [o["id"] for o in state["orders"]]
        )

    routes = {}
    visited = set()
    for v_idx, vehicle in enumerate(vehicles):
        route = []
        idx = routing.Start(v_idx)
        idx = solution.Value(routing.NextVar(idx))  # bỏ qua node start (= current_stop, không phải order)
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            nid = node_ids[node]
            if nid in orders_by_id:
                route.append(nid)
                visited.add(nid)
            idx = solution.Value(routing.NextVar(idx))
        routes[vehicle["id"]] = route

    unserved = [o["id"] for o in state["orders"] if o["id"] not in visited]

    return _candidate(routes, unserved)


if __name__ == "__main__":
    import json
    import sys
    import time

    path = sys.argv[1] if len(sys.argv) > 1 else "data/normalized/solomon_sample_15.json"
    instance = json.load(open(path))
    t0 = time.perf_counter()
    plan = solve_or_tools(instance)
    elapsed = time.perf_counter() - t0
    print(f"solved in {elapsed:.3f}s")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
