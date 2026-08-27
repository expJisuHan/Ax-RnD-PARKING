from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from src.analyzer import ParkingAnalyzer, next_slot_id
from src.config_store import DEFAULT_CONFIG
from src.occupancy import VehicleFootprint, polygon_area


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_footprint(x: float, y: float, width: float = 60, height: float = 40) -> VehicleFootprint:
    polygon = np.asarray(
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
        dtype=np.float32,
    )
    return VehicleFootprint(polygon=polygon, confidence=0.8, class_name="car")


class FakeTensor:
    def __init__(self, values) -> None:
        self._values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class FakeBoxes:
    def __init__(self, class_ids, confidences) -> None:
        self.cls = FakeTensor(class_ids)
        self.conf = FakeTensor(confidences)


class FakeMasks:
    def __init__(self, polygons) -> None:
        self.xy = polygons


class FakePrediction:
    def __init__(self, masks, boxes) -> None:
        self.masks = masks
        self.boxes = boxes


class FakeYOLO:
    """Mimics the slice of the ultralytics API that ParkingAnalyzer consumes."""

    names = {0: "person", 2: "car", 5: "bus", 7: "truck"}

    def __init__(self, prediction: FakePrediction) -> None:
        self.prediction = prediction
        self.predict_kwargs: dict | None = None

    def predict(self, **kwargs):
        self.predict_kwargs = kwargs
        return [self.prediction]


def mask_rectangle(x: float, y: float, width: float, height: float) -> np.ndarray:
    return np.asarray(
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
        dtype=np.float32,
    )


class DetectFootprintsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = ParkingAnalyzer(PROJECT_ROOT)
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)
        self.config = {**DEFAULT_CONFIG, "slots": []}

    def use_model(self, model) -> None:
        self.analyzer._load_model = lambda path: (model, None)

    def test_masks_become_footprints_with_class_and_confidence(self) -> None:
        model = FakeYOLO(
            FakePrediction(
                masks=FakeMasks([mask_rectangle(100, 100, 80, 50), mask_rectangle(300, 120, 120, 70)]),
                boxes=FakeBoxes([2, 7], [0.91, 0.77]),
            )
        )
        self.use_model(model)
        footprints, model_ready, error = self.analyzer.detect_footprints(self.image, self.config)

        self.assertTrue(model_ready)
        self.assertIsNone(error)
        self.assertEqual(len(footprints), 2)
        self.assertEqual([item.class_name for item in footprints], ["car", "truck"])
        self.assertAlmostEqual(footprints[0].confidence, 0.91, places=5)
        self.assertEqual(footprints[0].polygon.shape, (4, 2))
        # Vehicle classes only, forwarded as YOLO class ids.
        self.assertEqual(sorted(model.predict_kwargs["classes"]), [2, 5, 7])

    def test_missing_masks_yield_no_footprints(self) -> None:
        self.use_model(FakeYOLO(FakePrediction(masks=None, boxes=None)))
        footprints, model_ready, _ = self.analyzer.detect_footprints(self.image, self.config)
        self.assertTrue(model_ready)
        self.assertEqual(footprints, [])

    def test_analyze_end_to_end_flags_occlusion(self) -> None:
        # A truck fills the frame beside A2; nothing is detected inside A2 itself.
        self.use_model(
            FakeYOLO(
                FakePrediction(
                    masks=FakeMasks([mask_rectangle(60, 200, 200, 120)]),
                    boxes=FakeBoxes([7], [0.88]),
                )
            )
        )
        config = {
            **self.config,
            "slots": [
                {"id": "A1", "points": [[60, 200], [260, 200], [260, 320], [60, 320]]},
                {"id": "A2", "points": [[280, 210], [420, 210], [420, 320], [280, 320]]},
                {"id": "B9", "points": [[10, 10], [80, 10], [80, 70], [10, 70]]},
            ],
        }
        result = self.analyzer.analyze(self.image, config)
        by_id = {slot["id"]: slot for slot in result["slots"]}

        self.assertTrue(result["model_ready"])
        self.assertEqual(result["detected_vehicles"], 1)
        self.assertEqual(by_id["A2"]["status"], "unknown")
        self.assertTrue(by_id["A2"]["occlusion_risk"])
        self.assertEqual(by_id["A2"]["occluding_class"], "truck")
        # A slot far from the truck stays empty rather than being downgraded.
        self.assertEqual(by_id["B9"]["status"], "empty")
        self.assertFalse(by_id["B9"]["occlusion_risk"])

    def test_suggest_slots_uses_real_detection_path(self) -> None:
        self.use_model(
            FakeYOLO(
                FakePrediction(
                    masks=FakeMasks([mask_rectangle(300, 150, 90, 60), mask_rectangle(80, 150, 90, 60)]),
                    boxes=FakeBoxes([2, 2], [0.82, 0.64]),
                )
            )
        )
        result = self.analyzer.suggest_slots(self.image, self.config)
        self.assertTrue(result["model_ready"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [candidate["suggested_id"] for candidate in result["candidates"]], ["A1", "A2"]
        )
        for candidate in result["candidates"]:
            self.assertEqual(len(candidate["points"]), 4)
            self.assertEqual(candidate["vehicle_class"], "car")


class NextSlotIdTests(unittest.TestCase):
    def test_skips_ids_already_in_use(self) -> None:
        self.assertEqual(next_slot_id(set()), "A1")
        self.assertEqual(next_slot_id({"A1", "A2"}), "A3")
        self.assertEqual(next_slot_id({"A2"}), "A1")


class SuggestSlotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = ParkingAnalyzer(PROJECT_ROOT)
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)
        self.config = {**DEFAULT_CONFIG, "slots": []}

    def suggest(self, footprints, config=None):
        # Detection is exercised by the API smoke test; here we pin the footprints.
        self.analyzer.detect_footprints = lambda image, cfg: (footprints, True, None)
        return self.analyzer.suggest_slots(self.image, config or self.config)

    def test_candidates_are_padded_and_ordered_left_to_right(self) -> None:
        result = self.suggest([make_footprint(300, 100), make_footprint(60, 100)])
        self.assertEqual(result["count"], 2)
        ids = [candidate["suggested_id"] for candidate in result["candidates"]]
        self.assertEqual(ids, ["A1", "A2"])
        leftmost = result["candidates"][0]["points"]
        self.assertLess(min(point[0] for point in leftmost), 60)

    def test_padding_ratio_grows_candidate_area(self) -> None:
        base = self.suggest([make_footprint(100, 100)], {**self.config, "slot_padding_ratio": 0})
        padded = self.suggest([make_footprint(100, 100)], {**self.config, "slot_padding_ratio": 0.2})
        self.assertGreater(
            polygon_area(padded["candidates"][0]["points"]),
            polygon_area(base["candidates"][0]["points"]),
        )

    def test_candidates_stay_inside_the_frame(self) -> None:
        result = self.suggest(
            [make_footprint(0, 0)], {**self.config, "slot_padding_ratio": 1.0}
        )
        for x, y in result["candidates"][0]["points"]:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x, 639)
            self.assertLessEqual(y, 479)

    def test_suggested_ids_avoid_existing_slots(self) -> None:
        config = {
            **self.config,
            "slots": [{"id": "A1", "points": [[0, 0], [10, 0], [10, 10], [0, 10]]}],
        }
        result = self.suggest([make_footprint(100, 100)], config)
        self.assertEqual(result["candidates"][0]["suggested_id"], "A2")

    def test_missing_model_reports_not_ready(self) -> None:
        self.analyzer.detect_footprints = lambda image, cfg: ([], False, "model missing")
        result = self.analyzer.suggest_slots(self.image, self.config)
        self.assertFalse(result["model_ready"])
        self.assertEqual(result["count"], 0)

    def test_overlapping_candidates_are_deduplicated(self) -> None:
        result = self.suggest([make_footprint(100, 100), make_footprint(105, 105)])

        self.assertEqual(result["count"], 1)


if __name__ == "__main__":
    unittest.main()
