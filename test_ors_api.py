import os
from dotenv import load_dotenv

# Đảm bảo import từ src
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from adapters.routing.openrouteservice_client import OpenRouteServiceClient, RoutingClientError

def test_ors():
    load_dotenv()
    api_key = os.environ.get("ORS_API_KEY")
    if not api_key:
        print("LỖI: Không tìm thấy ORS_API_KEY trong môi trường hoặc file .env")
        return

    print("Khởi tạo OpenRouteServiceClient...")
    try:
        client = OpenRouteServiceClient(api_key=api_key)
        
        # Test 1: Directions (Vẽ đường giữa 2 điểm ở HN hoặc HCM)
        print("\n--- Test Directions ---")
        coords = [
            (21.028511, 105.804817), # HN Điểm A
            (21.024500, 105.820000)  # HN Điểm B
        ]
        res_dir = client.directions(coords)
        print(f"Khoảng cách: {res_dir.distance_m} m")
        print(f"Thời gian: {res_dir.duration_s} s")
        print(f"Số điểm polyline: {len(res_dir.geometry)}")
        print("Trạng thái: THÀNH CÔNG")

        # Test 2: Matrix
        print("\n--- Test Matrix ---")
        sources = [(21.028511, 105.804817), (21.030000, 105.810000)]
        destinations = [(21.024500, 105.820000)]
        res_matrix = client.matrix(sources, destinations)
        print(f"Ma trận thời gian (giây): {res_matrix.durations_s}")
        print(f"Ma trận khoảng cách (mét): {res_matrix.distances_m}")
        print("Trạng thái: THÀNH CÔNG")

    except RoutingClientError as e:
        print(f"LỖI TỪ CLIENT: {e}")
    except Exception as e:
        print(f"LỖI KHÔNG XÁC ĐỊNH: {e}")

if __name__ == "__main__":
    test_ors()
