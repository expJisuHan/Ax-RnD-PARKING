from __future__ import annotations

import argparse
import json

import cv2
import numpy as np
import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live parking API smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    health = requests.get(f"{base_url}/health", timeout=10)
    health.raise_for_status()
    original_config = requests.get(f"{base_url}/api/config", timeout=10).json()
    test_config = {
        **original_config,
        "frame_width": 640,
        "frame_height": 480,
        "slots": [
            {
                "id": "TEST-01",
                "points": [[180, 180], [460, 180], [460, 420], [180, 420]],
            }
        ],
    }

    try:
        saved = requests.post(
            f"{base_url}/api/config",
            json=test_config,
            timeout=10,
        )
        saved.raise_for_status()

        image = np.full((480, 640, 3), 235, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        if not ok:
            raise RuntimeError("Unable to encode the smoke-test image.")

        analyzed = requests.post(
            f"{base_url}/api/analyze",
            files={"image": ("smoke-test.jpg", encoded.tobytes(), "image/jpeg")},
            timeout=120,
        )
        analyzed.raise_for_status()
        result = analyzed.json()
        assert result["model_ready"] is True
        assert result["total_slots"] == 1
        assert result["slots"][0]["id"] == "TEST-01"
        assert result["slots"][0]["status"] == "empty"
        print(
            json.dumps(
                {
                    "health": health.json(),
                    "model_ready": result["model_ready"],
                    "detected_vehicles": result["detected_vehicles"],
                    "slot_status": result["slots"][0]["status"],
                    "snapshot": result["snapshot"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        restored = requests.post(
            f"{base_url}/api/config",
            json=original_config,
            timeout=10,
        )
        restored.raise_for_status()


if __name__ == "__main__":
    main()
