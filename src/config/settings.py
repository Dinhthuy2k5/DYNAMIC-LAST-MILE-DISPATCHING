# config/settings.py
BETA_LATENESS = 10.0
TIME_LIMIT_SEC = 5
SCALING_FACTOR = 100

# đúng bảng Problem Specification v1 Mục 7 — nguồn duy nhất, không hardcode lại nơi khác
TRIGGER_LATENESS_INCREASE_MIN = 10
TRIGGER_COST_DEGRADATION_PCT = 0.05
TRIGGER_ROUTE_CHANGE_GUARD_PCT = 0.30