from __future__ import annotations

import unittest

import numpy as np

from src.occupancy import (
    VehicleFootprint,
    evaluate_slots,
    expand_polygon,
    overlap_ratio,
    polygon_area,
)


SLOT = {"id": "A1", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]}


def footprint(points, confidence=0.9, class_name="car") -> VehicleFootprint:
    return VehicleFootprint(np.asarray(points, dtype=np.float32), confidence, class_name)


class OccupancyTests(unittest.TestCase):
    def test_overlap_ratio_uses_slot_area(self) -> None:
        vehicle = [[0, 0], [50, 0], [50, 100], [0, 100]]
        self.assertAlmostEqual(overlap_ratio(SLOT["points"], vehicle), 0.5, places=3)

    def test_occupied_empty_and_unknown_states(self) -> None:
        cases = [
            (
                [[0, 0], [30, 0], [30, 100], [0, 100]],
                "occupied",
            ),
            (
                [[0, 0], [10, 0], [10, 100], [0, 100]],
                "unknown",
            ),
            (
                [[200, 200], [230, 200], [230, 230], [200, 230]],
                "empty",
            ),
        ]
        for polygon, expected in cases:
            with self.subTest(expected=expected):
                result = evaluate_slots(
                    [SLOT],
                    [VehicleFootprint(np.asarray(polygon, dtype=np.float32), 0.9, "car")],
                    occupancy_threshold=0.15,
                    unknown_threshold=0.05,
                    model_ready=True,
                )
                self.assertEqual(result["slots"][0]["status"], expected)

    def test_model_failure_returns_unknown(self) -> None:
        result = evaluate_slots(
            [SLOT],
            [],
            occupancy_threshold=0.15,
            unknown_threshold=0.05,
            model_ready=False,
        )
        self.assertEqual(result["slots"][0]["status"], "unknown")

    def test_one_vehicle_is_assigned_to_only_one_overlapping_slot(self) -> None:
        slots = [
            {"id": "A1", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]},
            {"id": "A2", "points": [[50, 0], [150, 0], [150, 100], [50, 100]]},
        ]
        vehicle = VehicleFootprint(
            np.asarray([[10, 10], [90, 10], [90, 90], [10, 90]], dtype=np.float32),
            0.9,
            "car",
        )

        result = evaluate_slots(
            slots,
            [vehicle],
            occupancy_threshold=0.15,
            unknown_threshold=0.05,
            model_ready=True,
        )

        self.assertEqual([slot["status"] for slot in result["slots"]], ["occupied", "empty"])
        self.assertEqual(result["slots"][0]["matched_vehicle_index"], 0)
        self.assertIsNone(result["slots"][1]["matched_vehicle_index"])


class PolygonHelperTests(unittest.TestCase):
    def test_expand_polygon_grows_area_around_centroid(self) -> None:
        expanded = expand_polygon(SLOT["points"], 0.5)
        self.assertAlmostEqual(polygon_area(expanded), polygon_area(SLOT["points"]) * 2.25, places=1)
        self.assertAlmostEqual(float(expanded.mean(axis=0)[0]), 50.0, places=3)

    def test_expand_polygon_with_zero_ratio_is_unchanged(self) -> None:
        expanded = expand_polygon(SLOT["points"], 0)
        self.assertAlmostEqual(polygon_area(expanded), polygon_area(SLOT["points"]), places=3)

    def test_expand_polygon_keeps_four_corners(self) -> None:
        expanded = expand_polygon(SLOT["points"], 1.0)
        self.assertEqual(expanded.shape, (4, 2))


class OcclusionGuardTests(unittest.TestCase):
    # A truck parked immediately to the right of A1, not overlapping it.
    TRUCK = [[110, 0], [300, 0], [300, 180], [110, 180]]
    FAR_TRUCK = [[900, 900], [1100, 900], [1100, 1080], [900, 1080]]

    def evaluate(self, footprints, **kwargs):
        return evaluate_slots(
            [SLOT],
            footprints,
            occupancy_threshold=0.15,
            unknown_threshold=0.05,
            model_ready=True,
            **kwargs,
        )

    def test_large_neighbor_downgrades_empty_to_unknown(self) -> None:
        result = self.evaluate([footprint(self.TRUCK, class_name="truck")])
        slot = result["slots"][0]
        self.assertEqual(slot["status"], "unknown")
        self.assertTrue(slot["occlusion_risk"])
        self.assertEqual(slot["occluding_class"], "truck")
        self.assertEqual(result["occlusion_risk_slots"], 1)

    def test_oversized_car_counts_as_large_vehicle(self) -> None:
        # Class is "car" but the footprint dwarfs the slot, so treat it as an occluder.
        result = self.evaluate([footprint(self.TRUCK, class_name="car")])
        self.assertEqual(result["slots"][0]["status"], "unknown")

    def test_distant_large_vehicle_leaves_slot_empty(self) -> None:
        result = self.evaluate([footprint(self.FAR_TRUCK, class_name="truck")])
        slot = result["slots"][0]
        self.assertEqual(slot["status"], "empty")
        self.assertFalse(slot["occlusion_risk"])

    def test_small_neighbor_leaves_slot_empty(self) -> None:
        small_car = [[110, 0], [150, 0], [150, 40], [110, 40]]
        result = self.evaluate([footprint(small_car, class_name="car")])
        self.assertEqual(result["slots"][0]["status"], "empty")

    def test_guard_can_be_disabled(self) -> None:
        result = self.evaluate(
            [footprint(self.TRUCK, class_name="truck")],
            occlusion_guard=False,
        )
        self.assertEqual(result["slots"][0]["status"], "empty")

    def test_guard_does_not_override_occupied(self) -> None:
        parked = [[10, 10], [90, 10], [90, 90], [10, 90]]
        result = self.evaluate(
            [
                footprint(parked, class_name="car"),
                footprint(self.TRUCK, class_name="truck"),
            ]
        )
        slot = result["slots"][0]
        self.assertEqual(slot["status"], "occupied")
        self.assertFalse(slot["occlusion_risk"])


if __name__ == "__main__":
    unittest.main()
