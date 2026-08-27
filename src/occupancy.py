from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


# Classes that can physically hide a neighbouring vehicle from the camera.
LARGE_VEHICLE_CLASSES = {"truck", "bus"}


@dataclass(frozen=True)
class VehicleFootprint:
    polygon: np.ndarray
    confidence: float
    class_name: str
    mask_polygon: np.ndarray | None = None


def convex_polygon(points: Any) -> np.ndarray:
    polygon = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(polygon) < 3:
        raise ValueError("A polygon requires at least three points.")
    return cv2.convexHull(polygon).reshape(-1, 2).astype(np.float32)


def polygon_area(points: Any) -> float:
    return float(cv2.contourArea(convex_polygon(points)))


def expand_polygon(points: Any, ratio: float) -> np.ndarray:
    """Scale a polygon around its centroid. ratio 0.1 grows each edge by 10%."""
    polygon = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(polygon) < 3:
        raise ValueError("A polygon requires at least three points.")
    if ratio == 0:
        return polygon.copy()
    centroid = polygon.mean(axis=0)
    return (centroid + (polygon - centroid) * (1.0 + float(ratio))).astype(np.float32)


def intersection_area(polygon_a: Any, polygon_b: Any) -> float:
    area, _ = cv2.intersectConvexConvex(convex_polygon(polygon_a), convex_polygon(polygon_b))
    return max(0.0, float(area))


def overlap_ratio(slot_polygon: Any, vehicle_polygon: Any) -> float:
    slot_area = polygon_area(slot_polygon)
    if slot_area <= 0:
        return 0.0
    return max(0.0, min(1.0, intersection_area(slot_polygon, vehicle_polygon) / slot_area))


def polygon_overlap_ratio(polygon_a: Any, polygon_b: Any) -> float:
    """Return shared area relative to the smaller polygon."""
    smaller_area = min(polygon_area(polygon_a), polygon_area(polygon_b))
    if smaller_area <= 0:
        return 0.0
    return max(0.0, min(1.0, intersection_area(polygon_a, polygon_b) / smaller_area))


def is_large_vehicle(
    footprint: VehicleFootprint,
    slot_area: float,
    large_vehicle_area_ratio: float,
) -> bool:
    if footprint.class_name in LARGE_VEHICLE_CLASSES:
        return True
    if slot_area <= 0:
        return False
    return polygon_area(footprint.polygon) >= slot_area * large_vehicle_area_ratio


def find_occluding_vehicle(
    slot_points: Any,
    footprints: list[VehicleFootprint],
    *,
    neighbor_ratio: float,
    large_vehicle_area_ratio: float,
) -> VehicleFootprint | None:
    """A large vehicle sitting just outside a slot can hide the car parked inside it.

    The slot is grown by ``neighbor_ratio`` and any large vehicle reaching into that
    ring is treated as a possible occluder, so the slot must not be called empty.
    """
    slot_area = polygon_area(slot_points)
    if slot_area <= 0:
        return None
    neighborhood = expand_polygon(slot_points, neighbor_ratio)
    for footprint in footprints:
        if not is_large_vehicle(footprint, slot_area, large_vehicle_area_ratio):
            continue
        if intersection_area(neighborhood, footprint.polygon) > 0:
            return footprint
    return None


def assign_vehicles_to_slots(
    slots: list[dict[str, Any]],
    footprints: list[VehicleFootprint],
) -> dict[int, tuple[int, float]]:
    """Assign each detected vehicle to at most one parking slot.

    A vehicle can overlap two perspective-skewed slots near a boundary.  Evaluating
    every slot independently makes that one vehicle occupy both slots.  Matching
    the strongest vehicle/slot overlaps first gives each vehicle and slot a single
    owner while keeping the existing score semantics intact.
    """
    ranked_matches: list[tuple[float, float, str, int, int]] = []
    for vehicle_index, footprint in enumerate(footprints):
        for slot_index, slot in enumerate(slots):
            score = overlap_ratio(slot["points"], footprint.polygon)
            if score <= 0:
                continue
            ranked_matches.append(
                (
                    score,
                    footprint.confidence,
                    str(slot.get("id", "")),
                    vehicle_index,
                    slot_index,
                )
            )

    # Confidence and ID make ties deterministic across repeated analyses.
    ranked_matches.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    assigned_vehicles: set[int] = set()
    assigned_slots: set[int] = set()
    assignments: dict[int, tuple[int, float]] = {}
    for score, _confidence, _slot_id, vehicle_index, slot_index in ranked_matches:
        if vehicle_index in assigned_vehicles or slot_index in assigned_slots:
            continue
        assigned_vehicles.add(vehicle_index)
        assigned_slots.add(slot_index)
        assignments[slot_index] = (vehicle_index, score)
    return assignments


def evaluate_slots(
    slots: list[dict[str, Any]],
    footprints: list[VehicleFootprint],
    occupancy_threshold: float,
    unknown_threshold: float,
    *,
    model_ready: bool,
    occlusion_guard: bool = True,
    occlusion_neighbor_ratio: float = 0.8,
    large_vehicle_area_ratio: float = 1.6,
) -> dict[str, Any]:
    assignments = assign_vehicles_to_slots(slots, footprints)
    results: list[dict[str, Any]] = []
    for slot_index, slot in enumerate(slots):
        best_score = 0.0
        best_confidence = 0.0
        best_class = None
        matched_vehicle_index = None
        if slot_index in assignments:
            matched_vehicle_index, best_score = assignments[slot_index]
            matched_vehicle = footprints[matched_vehicle_index]
            best_confidence = matched_vehicle.confidence
            best_class = matched_vehicle.class_name

        occluded_by = None
        if not model_ready:
            status = "unknown"
        elif best_score >= occupancy_threshold:
            status = "occupied"
        elif best_score >= unknown_threshold:
            status = "unknown"
        else:
            status = "empty"
            if occlusion_guard:
                occluded_by = find_occluding_vehicle(
                    slot["points"],
                    footprints,
                    neighbor_ratio=occlusion_neighbor_ratio,
                    large_vehicle_area_ratio=large_vehicle_area_ratio,
                )
                # No detection next to a large vehicle is more likely a hidden car
                # than an empty slot, so hold judgement instead of reporting empty.
                if occluded_by is not None:
                    status = "unknown"

        results.append(
            {
                "id": slot["id"],
                "status": status,
                "score": round(best_score, 4),
                "confidence": round(best_confidence, 4),
                "vehicle_class": best_class,
                "matched_vehicle_index": matched_vehicle_index,
                "occlusion_risk": occluded_by is not None,
                "occluding_class": occluded_by.class_name if occluded_by else None,
            }
        )

    occupied_count = sum(item["status"] == "occupied" for item in results)
    unknown_count = sum(item["status"] == "unknown" for item in results)
    occlusion_count = sum(bool(item["occlusion_risk"]) for item in results)
    total = len(results)
    occupancy_rate = round((occupied_count / total) * 100, 1) if total else 0.0
    return {
        "total_slots": total,
        "occupied_slots": occupied_count,
        "empty_slots": total - occupied_count - unknown_count,
        "unknown_slots": unknown_count,
        "occlusion_risk_slots": occlusion_count,
        "occupancy_rate": occupancy_rate,
        "slots": results,
    }
