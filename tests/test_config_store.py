from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.config_store import ConfigStore, ConfigValidationError, DEFAULT_CONFIG


class ConfigStoreTests(unittest.TestCase):
    def test_save_and_load_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "parking_config.json")
            config = {
                **DEFAULT_CONFIG,
                "slots": [
                    {
                        "id": "A1",
                        "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    }
                ],
            }
            saved = store.save(config)
            loaded = store.load()

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["slots"][0]["id"], "A1")

    def test_duplicate_slot_ids_are_rejected(self) -> None:
        duplicate = {
            **DEFAULT_CONFIG,
            "slots": [
                {"id": "A1", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]},
                {"id": "A1", "points": [[2, 0], [3, 0], [3, 1], [2, 1]]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "parking_config.json")
            with self.assertRaises(ConfigValidationError):
                store.save(duplicate)

    def test_new_tuning_defaults_are_applied_to_legacy_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "parking_config.json")
            legacy = {
                "camera_id": "phone_camera_01",
                "analysis_interval_minutes": 5,
                "snapshot_retention_count": 10,
                "occupancy_threshold": 0.15,
                "unknown_threshold": 0.05,
                "confidence_threshold": 0.25,
                "image_size": 960,
                "model_path": "models/yolov8n-seg.pt",
                "slots": [],
            }
            saved = store.save(legacy)
            self.assertEqual(saved["slot_padding_ratio"], 0.1)
            self.assertTrue(saved["occlusion_guard"])
            self.assertEqual(saved["occlusion_neighbor_ratio"], 0.8)
            self.assertEqual(saved["large_vehicle_area_ratio"], 1.6)

    def test_invalid_tuning_values_are_rejected(self) -> None:
        cases = [
            {"slot_padding_ratio": 1.5},
            {"slot_padding_ratio": -0.1},
            {"occlusion_guard": "yes"},
            {"occlusion_neighbor_ratio": 5},
            {"large_vehicle_area_ratio": 0.5},
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "parking_config.json")
            for override in cases:
                with self.subTest(override=override):
                    with self.assertRaises(ConfigValidationError):
                        store.save({**DEFAULT_CONFIG, **override})

    def test_slot_requires_four_points(self) -> None:
        invalid = {
            **DEFAULT_CONFIG,
            "slots": [{"id": "A1", "points": [[0, 0], [1, 0], [1, 1]]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "parking_config.json")
            with self.assertRaises(ConfigValidationError):
                store.save(invalid)


if __name__ == "__main__":
    unittest.main()
