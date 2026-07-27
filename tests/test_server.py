from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server


class SnapshotRetentionTests(unittest.TestCase):
    def test_only_latest_snapshots_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_dir = Path(directory)
            for index in range(12):
                path = snapshot_dir / f"snapshot_{index:02d}.jpg"
                path.write_bytes(b"test")
                os.utime(path, (index + 1, index + 1))

            with patch.object(server, "SNAPSHOT_DIR", snapshot_dir):
                removed = server.prune_snapshots(10)

            remaining = sorted(snapshot_dir.iterdir())
            self.assertEqual(len(removed), 2)
            self.assertEqual(len(remaining), 10)
            self.assertNotIn(snapshot_dir / "snapshot_00.jpg", remaining)
            self.assertNotIn(snapshot_dir / "snapshot_01.jpg", remaining)


if __name__ == "__main__":
    unittest.main()
