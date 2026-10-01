"""
inspect_tw.py - xem format thực tế của time_window trong real package_data
"""
import json, sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.join(os.path.dirname(__file__),
                    "real_data", "almrrc2021-data-training", "model_build_inputs")

route_id = sys.argv[1] if len(sys.argv) > 1 else "RouteID_00143bdd-0a6b-49ec-bb35-36593d303e77"

with open(os.path.join(BASE, "package_data.json"), encoding="utf-8") as f:
    package_data = json.load(f)

stops = package_data.get(route_id, {})
print(f"Route: {route_id}, stops in package_data: {len(stops)}")

float_tw = 0
str_tw = 0
null_tw = 0
seen = 0
for stop_id, pkgs in stops.items():
    for pkg_id, pkg in pkgs.items():
        tw = pkg.get("time_window", {})
        start = tw.get("start_time_utc")
        end   = tw.get("end_time_utc")
        seen += 1
        if start is None:
            null_tw += 1
        elif isinstance(start, float):
            float_tw += 1
            if float_tw <= 3:
                print(f"  FLOAT tw: stop={stop_id} pkg={pkg_id} start={start!r} end={end!r}")
        elif isinstance(start, str):
            str_tw += 1
            if str_tw <= 3:
                print(f"  STR tw:   stop={stop_id} pkg={pkg_id} start={start!r} end={end!r}")

print(f"\nTotal packages: {seen}")
print(f"  string tw : {str_tw}")
print(f"  float tw  : {float_tw}  <-- likely NaN")
print(f"  null tw   : {null_tw}")
