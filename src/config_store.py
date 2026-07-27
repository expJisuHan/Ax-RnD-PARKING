from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "camera_id": "phone_camera_01",
    "analysis_interval_minutes": 5,
    "snapshot_retention_count": 10,
    "occupancy_threshold": 0.15,
    "unknown_threshold": 0.05,
    "confidence_threshold": 0.25,
    "image_size": 960,
    "model_path": "models/yolov8n-seg.pt",
    "frame_width": 0,
    "frame_height": 0,
    "slots": [],
}


class ConfigValidationError(ValueError):
    pass


def _as_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigValidationError(f"{field_name} must be a number.")
    return float(value)


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigValidationError("Configuration must be a JSON object.")

    config = deepcopy(DEFAULT_CONFIG)
    config.update(raw)

    interval = _as_number(config["analysis_interval_minutes"], "analysis_interval_minutes")
    if interval <= 0:
        raise ConfigValidationError("analysis_interval_minutes must be greater than 0.")
    config["analysis_interval_minutes"] = interval

    retention = config["snapshot_retention_count"]
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 1:
        raise ConfigValidationError("snapshot_retention_count must be an integer of 1 or more.")

    occupancy = _as_number(config["occupancy_threshold"], "occupancy_threshold")
    unknown = _as_number(config["unknown_threshold"], "unknown_threshold")
    confidence = _as_number(config["confidence_threshold"], "confidence_threshold")
    if not 0 < occupancy <= 1:
        raise ConfigValidationError("occupancy_threshold must be between 0 and 1.")
    if not 0 <= unknown < occupancy:
        raise ConfigValidationError("unknown_threshold must be below occupancy_threshold.")
    if not 0 < confidence <= 1:
        raise ConfigValidationError("confidence_threshold must be between 0 and 1.")

    image_size = config["image_size"]
    if isinstance(image_size, bool) or not isinstance(image_size, int) or image_size < 320:
        raise ConfigValidationError("image_size must be an integer of 320 or more.")

    slots = config.get("slots")
    if not isinstance(slots, list):
        raise ConfigValidationError("slots must be an array.")

    normalized_slots: list[dict[str, Any]] = []
    slot_ids: set[str] = set()
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict):
            raise ConfigValidationError(f"slots[{index}] must be an object.")
        slot_id = str(slot.get("id", "")).strip()
        if not slot_id:
            raise ConfigValidationError(f"slots[{index}].id is required.")
        if slot_id in slot_ids:
            raise ConfigValidationError(f"Duplicate slot id: {slot_id}")

        points = slot.get("points")
        if not isinstance(points, list) or len(points) != 4:
            raise ConfigValidationError(f"{slot_id} must contain exactly four points.")

        normalized_points: list[list[float]] = []
        for point_index, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 2:
                raise ConfigValidationError(
                    f"{slot_id}.points[{point_index}] must be [x, y]."
                )
            x = _as_number(point[0], f"{slot_id}.points[{point_index}][0]")
            y = _as_number(point[1], f"{slot_id}.points[{point_index}][1]")
            if x < 0 or y < 0:
                raise ConfigValidationError(f"{slot_id} point coordinates cannot be negative.")
            normalized_points.append([round(x, 2), round(y, 2)])

        slot_ids.add(slot_id)
        normalized_slots.append({"id": slot_id, "points": normalized_points})

    config["slots"] = normalized_slots
    config["camera_id"] = str(config.get("camera_id", DEFAULT_CONFIG["camera_id"])).strip()
    config["model_path"] = str(config.get("model_path", DEFAULT_CONFIG["model_path"])).strip()
    config["frame_width"] = max(0, int(config.get("frame_width", 0)))
    config["frame_height"] = max(0, int(config.get("frame_height", 0)))
    return config


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            config = deepcopy(DEFAULT_CONFIG)
            self.save(config)
            return config
        with self.path.open("r", encoding="utf-8") as config_file:
            return validate_config(json.load(config_file))

    def save(self, raw: dict[str, Any]) -> dict[str, Any]:
        config = validate_config(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as config_file:
            json.dump(config, config_file, ensure_ascii=False, indent=2)
            config_file.write("\n")
        temporary_path.replace(self.path)
        return config
