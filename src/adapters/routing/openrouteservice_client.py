"""Implementation RoutingClient cho OpenRouteService (ORS).

Đăng ký API key miễn phí tại https://openrouteservice.org/dev/#/signup
(free tier: ~2000 request/ngày, 40 request/phút, matrix tối đa ~2500 cặp
nguồn×đích/request — đã xử lý bằng cách chia batch trong matrix()).

Đặt key vào biến môi trường ORS_API_KEY, hoặc truyền thẳng qua constructor.
"""
import os

import requests

from .base import DirectionsResult, MatrixResult, RoutingClient, RoutingClientError

DEFAULT_BASE_URL = "https://api.openrouteservice.org"
DEFAULT_PROFILE = "driving-car"
# ORS free tier giới hạn khoảng 2500 cặp nguồn×đích mỗi request matrix —
# giữ biên an toàn, chia nhỏ destinations nếu vượt.
MAX_PAIRS_PER_MATRIX_REQUEST = 2000


class OpenRouteServiceClient(RoutingClient):
    def __init__(self, api_key=None, profile=DEFAULT_PROFILE, base_url=DEFAULT_BASE_URL,
                 timeout_s=15, session=None):
        self.api_key = api_key or os.environ.get("ORS_API_KEY")
        if not self.api_key:
            raise RoutingClientError(
                "Thiếu ORS API key. Đăng ký miễn phí tại "
                "https://openrouteservice.org/dev/#/signup rồi đặt biến môi trường "
                "ORS_API_KEY, hoặc truyền api_key= khi khởi tạo client."
            )
        self.profile = profile
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._session = session or requests.Session()

    def _headers(self):
        return {
            "Authorization": self.api_key,  # ORS dùng raw key, KHÔNG prefix "Bearer "
            "Content-Type": "application/json; charset=utf-8",
        }

    def _post(self, path, body):
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.post(url, json=body, headers=self._headers(), timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise RoutingClientError(f"Lỗi mạng khi gọi ORS {path}: {exc}") from exc

        if resp.status_code == 401:
            raise RoutingClientError("ORS API key không hợp lệ (401).")
        if resp.status_code == 403:
            raise RoutingClientError("ORS từ chối request (403) — kiểm tra quota hoặc quyền key.")
        if resp.status_code == 429:
            raise RoutingClientError("ORS rate limit (429) — free tier ~40 request/phút, 2000/ngày.")
        if resp.status_code >= 400:
            raise RoutingClientError(f"ORS {path} trả lỗi {resp.status_code}: {resp.text[:300]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise RoutingClientError(f"ORS {path} trả response không phải JSON hợp lệ.") from exc

    def matrix(self, sources, destinations):
        if not sources or not destinations:
            raise ValueError("sources và destinations không được rỗng.")

        # ORS nhận 1 danh sách locations + index sources/destinations trỏ vào đó
        # (không gửi 2 danh sách tách biệt) — và dùng [lng, lat], ngược (lat, lng).
        all_coords = list(sources) + list(destinations)
        locations = [[lng, lat] for lat, lng in all_coords]
        source_idx = list(range(len(sources)))
        dest_idx = list(range(len(sources), len(sources) + len(destinations)))

        # Chia batch nếu vượt giới hạn free tier — chia theo destinations, giữ nguyên sources.
        durations = [[None] * len(destinations) for _ in sources]
        distances = [[None] * len(destinations) for _ in sources]

        max_dest_per_batch = max(1, MAX_PAIRS_PER_MATRIX_REQUEST // max(1, len(sources)))
        for batch_start in range(0, len(destinations), max_dest_per_batch):
            batch_dest_idx = dest_idx[batch_start: batch_start + max_dest_per_batch]
            body = {
                "locations": locations,
                "sources": source_idx,
                "destinations": batch_dest_idx,
                "metrics": ["duration", "distance"],
                "units": "m",
            }
            data = self._post(f"/v2/matrix/{self.profile}", body)
            batch_durations = data.get("durations")
            batch_distances = data.get("distances")
            if batch_durations is None:
                raise RoutingClientError(f"ORS matrix response thiếu 'durations': {data}")
            for i in range(len(sources)):
                for j, col in enumerate(range(batch_start, batch_start + len(batch_dest_idx))):
                    durations[i][col] = batch_durations[i][j]
                    distances[i][col] = (batch_distances[i][j] if batch_distances is not None else None)

        missing = [(i, j) for i in range(len(sources)) for j in range(len(destinations))
                   if durations[i][j] is None]
        if missing:
            i, j = missing[0]
            raise RoutingClientError(
                f"ORS không tìm được route cho cặp sources[{i}]={sources[i]} -> "
                f"destinations[{j}]={destinations[j]} (có thể điểm nằm ngoài vùng dữ liệu đường)."
            )

        return MatrixResult(
            durations_s=tuple(tuple(row) for row in durations),
            distances_m=tuple(tuple(row) for row in distances),
        )

    def directions(self, coordinates):
        if len(coordinates) < 2:
            raise ValueError("directions() cần ít nhất 2 điểm.")
        body = {"coordinates": [[lng, lat] for lat, lng in coordinates]}
        data = self._post(f"/v2/directions/{self.profile}/geojson", body)

        features = data.get("features")
        if not features:
            raise RoutingClientError(f"ORS directions không trả về route nào: {data}")
        feature = features[0]
        summary = feature["properties"]["summary"]
        coords_lng_lat = feature["geometry"]["coordinates"]

        return DirectionsResult(
            distance_m=float(summary["distance"]),
            duration_s=float(summary["duration"]),
            geometry=tuple((lat, lng) for lng, lat in coords_lng_lat),
        )
