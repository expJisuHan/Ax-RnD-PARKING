from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .occupancy import VehicleFootprint, evaluate_slots


TARGET_CLASSES = {"car", "truck", "bus", "motorcycle"}


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

    def analyze(self, image: np.ndarray, config: dict[str, Any]) -> dict[str, Any]:
        model, model_error = self._load_model(config["model_path"])
        footprints: list[VehicleFootprint] = []

        if model is not None:
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
                    footprints.append(
                        VehicleFootprint(
                            polygon=footprint,
                            confidence=float(confidence),
                            class_name=str(model.names[class_id]),
                        )
                    )

        evaluation = evaluate_slots(
            config["slots"],
            footprints,
            config["occupancy_threshold"],
            config["unknown_threshold"],
            model_ready=model is not None,
        )
        return {
            **evaluation,
            "model_ready": model is not None,
            "model_error": model_error,
            "detected_vehicles": len(footprints),
        }


def decode_image(image_bytes: bytes) -> np.ndarray:
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Uploaded file is not a valid image.")
    return image
