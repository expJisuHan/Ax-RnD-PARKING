from __future__ import annotations

import unittest

import numpy as np

from src.occupancy import VehicleFootprint, evaluate_slots, overlap_ratio


SLOT = {"id": "A1", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]}


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


if __name__ == "__main__":
    unittest.main()
