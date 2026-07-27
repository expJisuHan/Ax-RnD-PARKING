from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class VehicleFootprint:
    polygon: np.ndarray
    confidence: float
    class_name: str


def convex_polygon(points: Any) -> np.ndarray:
    polygon = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(polygon) < 3:
        raise ValueError("A polygon requires at least three points.")
    return cv2.convexHull(polygon).reshape(-1, 2).astype(np.float32)


def overlap_ratio(slot_polygon: Any, vehicle_polygon: Any) -> float:
    slot = convex_polygon(slot_polygon)
    vehicle = convex_polygon(vehicle_polygon)
    slot_area = float(cv2.contourArea(slot))
    if slot_area <= 0:
        return 0.0
    intersection_area, _ = cv2.intersectConvexConvex(slot, vehicle)
    return max(0.0, min(1.0, float(intersection_area) / slot_area))


def evaluate_slots(
    slots: list[dict[str, Any]],
    footprints: list[VehicleFootprint],
    occupancy_threshold: float,
    unknown_threshold: float,
    *,
    model_ready: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for slot in slots:
        best_score = 0.0
        best_confidence = 0.0
        best_class = None
        for footprint in footprints:
            score = overlap_ratio(slot["points"], footprint.polygon)
            if score > best_score:
                best_score = score
                best_confidence = footprint.confidence
                best_class = footprint.class_name

        if not model_ready:
            status = "unknown"
        elif best_score >= occupancy_threshold:
            status = "occupied"
        elif best_score >= unknown_threshold:
            status = "unknown"
        else:
            status = "empty"

        results.append(
            {
                "id": slot["id"],
                "status": status,
                "score": round(best_score, 4),
                "confidence": round(best_confidence, 4),
                "vehicle_class": best_class,
            }
        )

    occupied_count = sum(item["status"] == "occupied" for item in results)
    unknown_count = sum(item["status"] == "unknown" for item in results)
    total = len(results)
    occupancy_rate = round((occupied_count / total) * 100, 1) if total else 0.0
    return {
        "total_slots": total,
        "occupied_slots": occupied_count,
        "empty_slots": total - occupied_count - unknown_count,
        "unknown_slots": unknown_count,
        "occupancy_rate": occupancy_rate,
        "slots": results,
    }
