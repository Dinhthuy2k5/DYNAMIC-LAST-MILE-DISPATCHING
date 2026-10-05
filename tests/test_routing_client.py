"""
test_routing_client.py — test OpenRouteServiceClient bằng mock HTTP (không gọi
mạng thật, không cần API key thật). Kiểm tra: build đúng request body (đổi
(lat,lng) -> [lng,lat] đúng chỗ), parse đúng response, chia batch khi vượt
giới hạn, và xử lý lỗi (401/429/thiếu durations/null = không tìm được route).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adapters.routing.base import RoutingClientError  # noqa: E402
from adapters.routing.openrouteservice_client import (  # noqa: E402
    OpenRouteServiceClient, MAX_PAIRS_PER_MATRIX_REQUEST,
)


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class TestClientConstruction(unittest.TestCase):
    def test_raises_without_api_key(self):
        env_backup = os.environ.pop("ORS_API_KEY", None)
        try:
            with self.assertRaises(RoutingClientError):
                OpenRouteServiceClient(api_key=None)
        finally:
            if env_backup is not None:
                os.environ["ORS_API_KEY"] = env_backup

    def test_accepts_explicit_api_key(self):
        client = OpenRouteServiceClient(api_key="fake-key", session=MagicMock())
        self.assertEqual(client.api_key, "fake-key")

    def test_reads_api_key_from_env(self):
        os.environ["ORS_API_KEY"] = "env-key"
        try:
            client = OpenRouteServiceClient(session=MagicMock())
            self.assertEqual(client.api_key, "env-key")
        finally:
            del os.environ["ORS_API_KEY"]


class TestMatrix(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = OpenRouteServiceClient(api_key="fake-key", session=self.session)

    def test_builds_request_with_lng_lat_order_and_indices(self):
        self.session.post.return_value = _fake_response(200, {
            "durations": [[0.0, 120.5]],
            "distances": [[0.0, 980.0]],
        })

        sources = [(10.0, 20.0)]        # (lat, lng)
        destinations = [(10.0, 20.0), (11.0, 21.0)]
        self.client.matrix(sources, destinations)

        call = self.session.post.call_args
        self.assertEqual(call.args[0], "https://api.openrouteservice.org/v2/matrix/driving-car")
        body = call.kwargs["json"]
        # locations phải là [lng, lat], sources trước, destinations sau
        self.assertEqual(body["locations"], [[20.0, 10.0], [20.0, 10.0], [21.0, 11.0]])
        self.assertEqual(body["sources"], [0])
        self.assertEqual(body["destinations"], [1, 2])
        self.assertEqual(call.kwargs["headers"]["Authorization"], "fake-key")

    def test_parses_durations_and_distances_correctly(self):
        self.session.post.return_value = _fake_response(200, {
            "durations": [[0.0, 300.0], [300.0, 0.0]],
            "distances": [[0.0, 5000.0], [5000.0, 0.0]],
        })
        result = self.client.matrix([(0, 0), (1, 1)], [(0, 0), (1, 1)])
        self.assertEqual(result.durations_s, ((0.0, 300.0), (300.0, 0.0)))
        self.assertEqual(result.distances_m, ((0.0, 5000.0), (5000.0, 0.0)))

    def test_splits_into_batches_when_exceeding_limit(self):
        n_dest = MAX_PAIRS_PER_MATRIX_REQUEST + 50  # buộc phải >1 batch với 1 source
        destinations = [(float(i), float(i)) for i in range(n_dest)]

        def fake_post(url, json, headers, timeout):
            batch_size = len(json["destinations"])
            return _fake_response(200, {
                "durations": [[1.0] * batch_size],
                "distances": [[10.0] * batch_size],
            })
        self.session.post.side_effect = fake_post

        result = self.client.matrix([(0.0, 0.0)], destinations)
        self.assertEqual(len(result.durations_s[0]), n_dest)
        self.assertGreater(self.session.post.call_count, 1)  # xác nhận thật sự chia nhiều request

    def test_null_entry_raises_clear_error(self):
        self.session.post.return_value = _fake_response(200, {
            "durations": [[0.0, None]],
            "distances": [[0.0, None]],
        })
        with self.assertRaises(RoutingClientError) as ctx:
            self.client.matrix([(0, 0)], [(0, 0), (99, 99)])
        self.assertIn("không tìm được route", str(ctx.exception))

    def test_401_raises_clear_error(self):
        self.session.post.return_value = _fake_response(401, {}, "unauthorized")
        with self.assertRaises(RoutingClientError) as ctx:
            self.client.matrix([(0, 0)], [(1, 1)])
        self.assertIn("API key", str(ctx.exception))

    def test_429_raises_clear_error(self):
        self.session.post.return_value = _fake_response(429, {}, "rate limited")
        with self.assertRaises(RoutingClientError) as ctx:
            self.client.matrix([(0, 0)], [(1, 1)])
        self.assertIn("rate limit", str(ctx.exception))

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            self.client.matrix([], [(0, 0)])
        with self.assertRaises(ValueError):
            self.client.matrix([(0, 0)], [])


class TestDirections(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = OpenRouteServiceClient(api_key="fake-key", session=self.session)

    def test_builds_request_and_parses_geometry(self):
        self.session.post.return_value = _fake_response(200, {
            "features": [{
                "properties": {"summary": {"distance": 1500.0, "duration": 180.0}},
                "geometry": {"coordinates": [[20.0, 10.0], [20.5, 10.5], [21.0, 11.0]]},
            }]
        })

        result = self.client.directions([(10.0, 20.0), (11.0, 21.0)])

        call = self.session.post.call_args
        self.assertEqual(
            call.args[0],
            "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        )
        self.assertEqual(call.kwargs["json"]["coordinates"], [[20.0, 10.0], [21.0, 11.0]])

        self.assertEqual(result.distance_m, 1500.0)
        self.assertEqual(result.duration_s, 180.0)
        # geometry phải đổi lại về (lat, lng)
        self.assertEqual(result.geometry, ((10.0, 20.0), (10.5, 20.5), (11.0, 21.0)))

    def test_rejects_single_point(self):
        with self.assertRaises(ValueError):
            self.client.directions([(10.0, 20.0)])

    def test_empty_features_raises(self):
        self.session.post.return_value = _fake_response(200, {"features": []})
        with self.assertRaises(RoutingClientError):
            self.client.directions([(10.0, 20.0), (11.0, 21.0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
