"""Đọc/ghi canonical snapshot JSON tại ranh giới I/O của ứng dụng."""

import json
from pathlib import Path

from .entities import RoutingSnapshot


def load_snapshot(path: str | Path) -> RoutingSnapshot:
    with Path(path).open(encoding="utf-8") as stream:
        return RoutingSnapshot.from_dict(json.load(stream))


def save_snapshot(snapshot: RoutingSnapshot, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as stream:
        json.dump(snapshot.to_dict(), stream, indent=2, ensure_ascii=False)
