from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .occupancy import (
    VehicleFootprint,
    evaluate_slots,
    expand_polygon,
    polygon_area,
    polygon_overlap_ratio,
)


TARGET_CLASSES = {"car", "truck", "bus", "motorcycle"}


def next_slot_id(existing_ids: set[str], prefix: str = "A") -> str:
    index = 1
    while f"{prefix}{index}" in existing_ids:
        index += 1
    return f"{prefix}{index}"


class ParkingAnalyzer:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._model: Any = None
        self._model_path: Path | None = None
        self._load_error: str | None = None

    def _resolve_model_path(self, configured_path: str) -> Path:
        path = Path(configured_path)
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def _load_model(self, configured_path: str) -> tuple[Any | None, str | None]:
        model_path = self._resolve_model_path(configured_path)
        if self._model is not None and self._model_path == model_path:
            return self._model, None
        if self._model_path == model_path and self._load_error:
            return None, self._load_error

        self._model = None
        self._model_path = model_path
        self._load_error = None
        if not model_path.exists():
            self._load_error = f"YOLO model file not found: {model_path}"
            return None, self._load_error

        try:
            from ultralytics import YOLO

            self._model = YOLO(str(model_path))
        except Exception as exc:  # Dependency and runtime failures share one API state.
            self._load_error = f"Unable to load YOLO model: {exc}"
            return None, self._load_error
        return self._model, None

    @staticmethod
    def _footprint_from_mask(mask_polygon: np.ndarray) -> np.ndarray | None:
        contour = np.asarray(mask_polygon, dtype=np.float32).reshape(-1, 2)
        if len(contour) < 3:
            return None

        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.float32)
        bottom_two = box[np.argsort(box[:, 1])[-2:]]
        if bottom_two[0][0] > bottom_two[1][0]:
            bottom_two = bottom_two[::-1]

        left, right = bottom_two
        ground_width = right - left
        width = float(np.linalg.norm(ground_width))
        if width < 2:
            return None

        normal = np.array([-ground_width[1], ground_width[0]], dtype=np.float32) / width
        if normal[1] > 0:
            normal = -normal
        footprint_length = max(12.0, min(160.0, width * 1.8))
        return np.array(
            [left, right, right + normal * footprint_length, left + normal * footprint_length],
            dtype=np.float32,
        )

    @staticmethod
    def _display_polygon_from_mask(mask_polygon: np.ndarray) -> np.ndarray | None:
        """Keep the detected vehicle contour for a non-rectangular slot proposal."""
        contour = np.asarray(mask_polygon, dtype=np.float32).reshape(-1, 2)
        if len(contour) < 3:
            return None
        perimeter = cv2.arcLength(contour, True)
        # Reduce model noise while preserving the curved silhouette in the UI.
        epsilon = max(1.5, perimeter * 0.012)
        simplified = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(simplified) < 4:
            simplified = cv2.convexHull(contour).reshape(-1, 2)
        return simplified.astype(np.float32)

    def detect_footprints(
        self, image: np.ndarray, config: dict[str, Any]
    ) -> tuple[list[VehicleFootprint], bool, str | None]:
        """Run YOLO segmentation once and return vehicle ground footprints."""
        model, model_error = self._load_model(config["model_path"])
        footprints: list[VehicleFootprint] = []
        if model is None:
            return footprints, False, model_error

        target_class_ids = [
            class_id
            for class_id, class_name in model.names.items()
            if class_name in TARGET_CLASSES
        ]
        prediction = model.predict(
            source=image,
            classes=target_class_ids,
            conf=config["confidence_threshold"],
            imgsz=config["image_size"],
            verbose=False,
        )[0]

        if prediction.masks is not None and prediction.boxes is not None:
            polygons = prediction.masks.xy
            class_ids = prediction.boxes.cls.cpu().numpy().astype(int)
            confidences = prediction.boxes.conf.cpu().numpy()
            for polygon, class_id, confidence in zip(polygons, class_ids, confidences):
                footprint = self._footprint_from_mask(np.asarray(polygon))
                if footprint is None:
                    continue
                display_polygon = self._display_polygon_from_mask(np.asarray(polygon))
                footprints.append(
                    VehicleFootprint(
                        polygon=footprint,
                        confidence=float(confidence),
                        class_name=str(model.names[class_id]),
                        mask_polygon=display_polygon,
                    )
                )
        return footprints, True, None

    def analyze(self, image: np.ndarray, config: dict[str, Any]) -> dict[str, Any]:
        footprints, model_ready, model_error = self.detect_footprints(image, config)

        evaluation = evaluate_slots(
            config["slots"],
            footprints,
            config["occupancy_threshold"],
            config["unknown_threshold"],
            model_ready=model_ready,
            occlusion_guard=bool(config.get("occlusion_guard", True)),
            occlusion_neighbor_ratio=float(config.get("occlusion_neighbor_ratio", 0.8)),
            large_vehicle_area_ratio=float(config.get("large_vehicle_area_ratio", 1.6)),
        )
        return {
            **evaluation,
            "model_ready": model_ready,
            "model_error": model_error,
            "detected_vehicles": len(footprints),
        }

    def suggest_slots(self, image: np.ndarray, config: dict[str, Any]) -> dict[str, Any]:
        """Turn every detected vehicle into a parking slot polygon proposal.

        A footprint measured from a real parked car already carries the perspective
        distortion of the camera, so it fits the lane far better than corners a person
        estimates by eye on a diagonal view.
        """
        footprints, model_ready, model_error = self.detect_footprints(image, config)
        padding_ratio = float(config.get("slot_padding_ratio", 0.1))

        height = int(image.shape[0]) or 1
        width = int(image.shape[1]) or 1
        row_bucket = max(1.0, height / 8.0)

        entries: list[tuple[float, float, dict[str, Any]]] = []
        existing_polygons = [slot["points"] for slot in config.get("slots", [])]
        for footprint in footprints:
            source_polygon = footprint.mask_polygon if footprint.mask_polygon is not None else footprint.polygon
            polygon = expand_polygon(source_polygon, padding_ratio)
            # Padding can push corners past the frame, but stored slots must stay in bounds.
            polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
            polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)
            area = polygon_area(polygon)
            if area <= 0:
                continue
            # A candidate represents one vehicle's parking area. Exclude an area
            # that duplicates a configured slot or a nearby detected vehicle.
            if any(polygon_overlap_ratio(polygon, other) > 0.05 for other in existing_polygons):
                continue
            centroid = polygon.mean(axis=0)
            entries.append(
                (
                    float(centroid[1] // row_bucket),
                    float(centroid[0]),
                    {
                        "points": [[round(float(x), 2), round(float(y), 2)] for x, y in polygon],
                        "confidence": round(float(footprint.confidence), 4),
                        "vehicle_class": footprint.class_name,
                        "area": round(area, 2),
                    },
                )
            )

        entries.sort(key=lambda entry: (entry[0], entry[1]))

        used_ids = {str(slot["id"]) for slot in config.get("slots", [])}
        candidates: list[dict[str, Any]] = []
        accepted_polygons: list[list[list[float]]] = []
        for index, (_, _, candidate) in enumerate(entries):
            if any(
                polygon_overlap_ratio(candidate["points"], other) > 0.05
                for other in accepted_polygons
            ):
                continue
            suggested_id = next_slot_id(used_ids)
            used_ids.add(suggested_id)
            accepted_polygons.append(candidate["points"])
            candidates.append({"index": index, "suggested_id": suggested_id, **candidate})

        return {
            "model_ready": model_ready,
            "model_error": model_error,
            "padding_ratio": padding_ratio,
            "count": len(candidates),
            "candidates": candidates,
        }


def decode_image(image_bytes: bytes) -> np.ndarray:
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Uploaded file is not a valid image.")
    return image
