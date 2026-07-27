from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import ParkingAnalyzer, decode_image
from .config_store import ConfigStore, ConfigValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "app" / "static"
CONFIG_PATH = PROJECT_ROOT / "config" / "parking_config.json"
SNAPSHOT_DIR = PROJECT_ROOT / "outputs" / "snapshots"
LOG_DIR = PROJECT_ROOT / "outputs" / "logs"
JSONL_LOG = LOG_DIR / "analysis_results.jsonl"
CSV_LOG = LOG_DIR / "analysis_results.csv"
SEOUL = timezone(timedelta(hours=9), name="KST")

app = FastAPI(title="Ax-RnD Parking Occupancy", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

config_store = ConfigStore(CONFIG_PATH)
analyzer = ParkingAnalyzer(PROJECT_ROOT)
latest_result: dict[str, Any] | None = None


def ensure_runtime_directories() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    config_store.load()


def prune_snapshots(retention_count: int) -> list[str]:
    files = sorted(
        (
            path
            for path in SNAPSHOT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for old_file in files[retention_count:]:
        old_file.unlink()
        removed.append(old_file.name)
    return removed


def save_snapshot(image: Any, timestamp: datetime) -> Path:
    filename = timestamp.strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
    path = SNAPSHOT_DIR / filename
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 88]):
        raise RuntimeError("Failed to save analysis snapshot.")
    return path


def append_logs(result: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_LOG.open("a", encoding="utf-8") as jsonl_file:
        jsonl_file.write(json.dumps(result, ensure_ascii=False) + "\n")

    csv_exists = CSV_LOG.exists()
    with CSV_LOG.open("a", encoding="utf-8-sig", newline="") as csv_file:
        fieldnames = [
            "timestamp",
            "total_slots",
            "occupied_slots",
            "empty_slots",
            "unknown_slots",
            "occupancy_rate",
            "detected_vehicles",
            "model_ready",
            "snapshot",
            "slots_json",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if not csv_exists:
            writer.writeheader()
        writer.writerow(
            {
                **{field: result.get(field) for field in fieldnames if field != "slots_json"},
                "slots_json": json.dumps(result.get("slots", []), ensure_ascii=False),
            }
        )


def read_latest_log() -> dict[str, Any] | None:
    if not JSONL_LOG.exists():
        return None
    lines = JSONL_LOG.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1]) if lines else None


ensure_runtime_directories()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    config = config_store.load()
    model_path = Path(config["model_path"])
    if not model_path.is_absolute():
        model_path = PROJECT_ROOT / model_path
    return {
        "status": "ok",
        "configured_slots": len(config["slots"]),
        "model_file_exists": model_path.exists(),
        "snapshot_retention_count": config["snapshot_retention_count"],
    }


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return config_store.load()


@app.post("/api/config")
def save_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        config = config_store.save(payload)
    except (ConfigValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    prune_snapshots(config["snapshot_retention_count"])
    return {"saved": True, "config": config}


@app.post("/api/analyze")
async def analyze_frame(image: UploadFile = File(...)) -> dict[str, Any]:
    global latest_result

    content_type = image.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are supported.")

    image_bytes = await image.read()
    if len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image size must be 15 MB or less.")
    try:
        frame = decode_image(image_bytes)
        config = config_store.load()
        timestamp = datetime.now(SEOUL)
        snapshot_path = save_snapshot(frame, timestamp)
        analysis = analyzer.analyze(frame, config)
        prune_snapshots(config["snapshot_retention_count"])
    except (ValueError, ConfigValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    latest_result = {
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "snapshot": snapshot_path.name,
        "snapshot_url": f"/api/snapshots/{snapshot_path.name}",
        **analysis,
    }
    append_logs(latest_result)
    return latest_result


@app.get("/api/results/latest")
def get_latest_result() -> dict[str, Any]:
    result = latest_result or read_latest_log()
    return {"result": result}


@app.get("/api/snapshots")
def list_snapshots() -> dict[str, Any]:
    config = config_store.load()
    files = sorted(
        (
            path
            for path in SNAPSHOT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return {
        "retention_count": config["snapshot_retention_count"],
        "count": len(files),
        "items": [
            {
                "name": path.name,
                "url": f"/api/snapshots/{path.name}",
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, SEOUL).isoformat(
                    timespec="seconds"
                ),
            }
            for path in files
        ],
    }


@app.get("/api/snapshots/{filename}")
def get_snapshot(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid snapshot filename.")
    path = SNAPSHOT_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return FileResponse(path)
