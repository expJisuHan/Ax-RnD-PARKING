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
