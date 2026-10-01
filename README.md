# W2 — Data foundation + baseline

**v3 update:** baseline and validator now score closed routes, including the
return leg to the depot. The planner and validator only consider orders released
at the snapshot time (`--at-time`, default 0). Amazon package time windows at a
shared stop are combined by intersection. Checked-in reports were regenerated;
the test suite now has 21 tests.

**v2 update:** schema/instance_schema.json đã sửa lại cho khớp đúng Domain Model
(Thiết kế hệ thống, Mục 4.1) — thêm `scenario_id`, `order.release_time`,
`order.status`, `vehicle.status`, `vehicle.remaining_capacity`; đổi tên
`due_time`→`deadline`, `start_location`→`current_stop`. `validator.py` giờ
check capacity theo `remaining_capacity` (Q_k còn lại) thay vì `capacity` gốc,
và chặn order gán cho vehicle `UNAVAILABLE`. Tất cả 18 unit test (14 cũ + 4 mới
cho field vừa thêm) pass; baseline chạy lại cho metrics giống hệt bản trước
(đổi field, không đổi logic).

Deliverable theo kế hoạch: **Normalize Amazon; instance schema; Solomon subset;
baseline no-replan + Greedy Insertion; feasibility validator → "Data + baseline
chạy"**.

## Cấu trúc

```
schema/instance_schema.json     # canonical instance schema (JSON Schema draft-07)
data/solomon/                   # Solomon-format sample (synthetic, xem giới hạn bên dưới)
data/amazon_sample/             # Amazon Last-Mile-format sample (synthetic, xem giới hạn bên dưới)
data/normalized/                # output đã normalize về canonical schema
src/parse_solomon.py            # Solomon .txt -> canonical schema
src/normalize_amazon.py         # route_data/package_data/travel_times.json -> canonical schema
src/validator.py                # feasibility validator (instance + plan)
src/greedy_insertion.py         # baseline B1 — Cheapest Insertion
src/run_baseline.py             # orchestrator: load -> validate -> Greedy -> validate plan -> report
tests/test_pipeline.py          # 14 unit test, có đáp án biết trước tay
output/                         # report + plan sinh ra khi chạy run_baseline.py
```

## Chạy thử

```bash
cd src
python3 run_baseline.py ../data/normalized/solomon_sample_15.json --out ../output
python3 run_baseline.py ../data/normalized/amazon_sample_route01.json --out ../output
python3 -m pytest ../tests/ -v      # hoặc: python3 ../tests/test_pipeline.py
```

Kết quả đã chạy thử (xem `output/*.report.json`): cả 2 nguồn dữ liệu ra plan
**feasible = True**, không vi phạm hard constraint; 21 unit test pass.

## GIỚI HẠN QUAN TRỌNG — đọc trước khi dùng cho W3 trở đi

1. **Dữ liệu Amazon thật đã có trong `real_data/`.** Bộ training nằm tại
   `real_data/almrrc2021-data-training/model_build_inputs/` với ba file
   `route_data.json`, `package_data.json`, `travel_times.json`. Dùng route ID
   thật để kiểm tra normalizer, ví dụ:
   ```bash
   python src/normalize_amazon.py ./real_data/almrrc2021-data-training/model_build_inputs RouteID_00143bdd-0a6b-49ec-bb35-36593d303e77
   ```
   Lưu ý `travel_times.json` khoảng 1.8 GB; script hiện đọc cả ba JSON vào bộ
   nhớ, nên cần RAM lớn. `data/amazon_sample/` vẫn là sample synthetic để chạy
   smoke test nhanh.

2. **Solomon cũng là file synthetic đúng ĐỊNH DẠNG**, không phải bộ instance
   C101/R101 gốc (tránh rủi ro chép sai số liệu benchmark chính thức từ trí
   nhớ). Muốn benchmark thật: tải từ
   http://web.cba.neu.edu/~msolomon/problems.htm hoặc VRP-REP, bỏ file `.txt`
   cùng định dạng vào `data/solomon/` — `parse_solomon.py` không cần sửa.

3. **1 route Amazon = 1 vehicle** hiện tại (đúng cấu trúc dataset gốc: mỗi
   route là 1 xe đã chạy). Muốn có fleet nhiều xe thật cho dynamic scenario
   (cần cho W4 trở đi — New Order/Breakdown chỉ có ý nghĩa khi có ≥2 xe), cần
   gộp nhiều `route_id` cùng station — **chưa làm ở W2**, cố ý để ngoài scope,
   cần bổ sung trước khi dùng cho mô phỏng dynamic.

4. Demand của order Amazon dùng **thể tích (cm³)** vì `executor_capacity_cm3`
   là đơn vị capacity gốc của dataset — khác Solomon dùng demand đơn vị trừu
   tượng. Khi trộn 2 nguồn dữ liệu trong cùng 1 benchmark (W10), cần chuẩn hóa
   lại đơn vị capacity cho nhất quán.

5. `greedy_insertion.py` hiện tính lại `simulate_route` cho từng vị trí chèn
   (đúng đắn nhưng chưa tối ưu tốc độ) — đủ nhanh cho instance nhỏ ở W2
   (< 0.01s), cần benchmark lại độ phức tạp khi test ở scale 100K/1M (W10).

## Việc tiếp theo (W3)

Theo Problem Specification v1: W3 = "Static optimizer + validator + current-
state builder" — dùng `validator.py` này làm nền, thêm OR-Tools (P-CI + GLS)
làm baseline B2 để so sánh với Greedy Insertion (B1) đã có ở đây.
