"""
Sinh một instance nhỏ ĐÚNG ĐỊNH DẠNG FILE Solomon VRPTW (header VEHICLE/CUSTOMER,
cột CUST_NO/XCOORD/YCOORD/DEMAND/READY_TIME/DUE_DATE/SERVICE_TIME) để test parser.

QUAN TRỌNG: đây KHÔNG PHẢI bộ instance Solomon gốc (C101/R101/...) — số liệu ở đây
là synthetic, sinh có seed cố định để tái lập được, chỉ dùng để kiểm chứng
parse_solomon.py đọc đúng cấu trúc file. Khi cần benchmark thật, tải bộ Solomon
gốc từ http://web.cba.neu.edu/~msolomon/problems.htm hoặc VRP-REP và đặt file
.txt cùng định dạng vào thư mục này — parser không cần sửa gì thêm.
"""
import random

random.seed(20235437)  # cố định theo student id cho tái lập được

N_CUSTOMERS = 15
VEHICLE_NUMBER = 5
VEHICLE_CAPACITY = 200

lines = []
lines.append("SAMPLE_SOLOMON_FORMAT_15")
lines.append("")
lines.append("VEHICLE")
lines.append("NUMBER     CAPACITY")
lines.append(f"{VEHICLE_NUMBER:>5d}{VEHICLE_CAPACITY:>15d}")
lines.append("")
lines.append("CUSTOMER")
lines.append("CUST NO.   XCOORD.   YCOORD.    DEMAND   READY TIME   DUE DATE   SERVICE TIME")
lines.append("")

# depot = customer 0, time window rộng bao trùm toàn bộ horizon
HORIZON = 1000
lines.append(f"{0:>5d}{50:>10d}{50:>10d}{0:>10d}{0:>10d}{HORIZON:>10d}{0:>10d}")

for i in range(1, N_CUSTOMERS + 1):
    x = random.randint(0, 100)
    y = random.randint(0, 100)
    demand = random.randint(5, 30)
    ready = random.randint(0, HORIZON - 200)
    due = ready + random.randint(60, 250)
    due = min(due, HORIZON)
    service = random.choice([10, 15, 20])
    lines.append(f"{i:>5d}{x:>10d}{y:>10d}{demand:>10d}{ready:>10d}{due:>10d}{service:>10d}")

with open("SAMPLE_SOLOMON_FORMAT_15.txt", "w") as f:
    f.write("\n".join(lines) + "\n")

print("Đã sinh data/solomon/SAMPLE_SOLOMON_FORMAT_15.txt")
