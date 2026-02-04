"""
Centralised two-layer cache manager for GridSight.

Layer 1 — FastF1 raw cache  (.fastf1-cache/)
Layer 2 — Precomputed JSON   (computed_data/*.json.gz)

All heavy serialisation uses **orjson** (10× faster than stdlib json,
native numpy support) and files are gzip-compressed on disk (~80% smaller).
"""

from __future__ import annotations

import gzip
import math
import threading
import asyncio
from pathlib import Path
from typing import Any, Optional

import numpy as np
import orjson

_preload_locks: dict[str, asyncio.Lock] = {}

def get_preload_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _preload_locks:
        _preload_locks[session_id] = asyncio.Lock()
    return _preload_locks[session_id]

# ── paths ────────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).resolve().parent.parent
COMPUTED_DIR = _BACKEND_DIR / "computed_data"
FASTF1_CACHE_DIR = _BACKEND_DIR / ".fastf1-cache"


def _ensure_dirs():
    COMPUTED_DIR.mkdir(parents=True, exist_ok=True)


# ── numpy → native Python sanitiser ─────────────────────────────────────

def sanitize(obj: Any) -> Any:
    """
    Recursively convert numpy scalars / arrays to native Python types.

    This guarantees that orjson never encounters a type it can't handle,
    and that the resulting JSON contains only standard JSON types.
    """
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


# ── status tracking ─────────────────────────────────────────────────────

_status_lock = threading.Lock()
_status_map: dict[str, dict[str, Any]] = {}
# key = "year_round_type", value = {"status": ..., "progress": ..., ...}


def _key(year: int, rnd: int, stype: str) -> str:
    return f"{year}_{rnd}_{stype.upper()}"


def set_status(
    year: int,
    rnd: int,
    stype: str,
    *,
    status: str,
    progress: int = 0,
    source: Optional[str] = None,
    detail: Optional[str] = None,
):
    with _status_lock:
        entry: dict[str, Any] = {"status": status, "progress": progress}
        if source:
            entry["source"] = source
        if detail:
            entry["detail"] = detail
        _status_map[_key(year, rnd, stype)] = entry


def get_status(year: int, rnd: int, stype: str) -> dict[str, Any]:
    """
    Return the current loading status for a session.

    Returns one of:
      {"status": "cached"}                          — .json.gz exists
      {"status": "loading", "progress": 0-100}      — currently loading
      {"status": "not_cached"}                       — nothing on disk
      {"status": "error", "detail": "..."}           — load failed
    """
    k = _key(year, rnd, stype)

    # 1. Is it currently loading or errored?
    with _status_lock:
        if k in _status_map:
            entry = _status_map[k]
            if entry["status"] == "loading":
                return {"status": "loading", "progress": entry.get("progress", 0)}
            if entry["status"] == "error":
                return {"status": "error", "detail": entry.get("detail", "")}
            if entry["status"] == "cached":
                return {"status": "cached", "source": entry.get("source", "computed"), "progress": entry.get("progress", 100)}

    # 2. Do we have a precomputed .json.gz?
    if has_computed_cache(year, rnd, stype):
        return {"status": "cached", "source": "computed", "progress": 100}

    # 3. Nothing at all
    return {"status": "not_cached"}


def clear_status(year: int, rnd: int, stype: str):
    with _status_lock:
        _status_map.pop(_key(year, rnd, stype), None)


# ── Layer 2: computed cache (orjson + gzip) ──────────────────────────────

def get_cache_path(year: int, rnd: int, stype: str) -> Path:
    _ensure_dirs()
    return COMPUTED_DIR / f"{year}_{rnd}_{stype.upper()}.json.gz"


def has_computed_cache(year: int, rnd: int, stype: str) -> bool:
    return get_cache_path(year, rnd, stype).exists()


def read_computed(year: int, rnd: int, stype: str) -> dict:
    """Read and decompress a precomputed cache file. Returns the dict."""
    path = get_cache_path(year, rnd, stype)
    with gzip.open(path, "rb") as f:
        raw = f.read()
    return orjson.loads(raw)


def sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(i) for i in obj]
    elif isinstance(obj, bool) or type(obj).__name__ == 'bool_':
        return int(obj)  # Convert bool to 0/1
    elif isinstance(obj, float):
        import math
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif hasattr(obj, 'item'):
        # numpy scalar
        return obj.item()
    else:
        return obj

def write_computed(year: int, rnd: int, stype: str, data: dict):
    """
    Sanitise numpy types, serialise with orjson, and gzip-compress to disk.
    """
    if "frames" not in data:
        data["frames"] = []

    _ensure_dirs()
    path = get_cache_path(year, rnd, stype)
    clean = sanitize(data)

    data_to_write = sanitize_for_json(clean)

    raw = orjson.dumps(data_to_write, option=orjson.OPT_SERIALIZE_NUMPY)
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(raw)
    print(f"[cache] Wrote computed cache → {path}  ({len(raw):,} bytes raw)")


# ── Layer 2b: track-feature cache (sector points + DRS XY) ───────────────

def _track_cache_path(year: int, rnd: int, stype: str) -> Path:
    _ensure_dirs()
    return COMPUTED_DIR / f"{year}_{rnd}_{stype.upper()}_TRACK.json.gz"


def has_track_cache(year: int, rnd: int, stype: str) -> bool:
    return _track_cache_path(year, rnd, stype).exists()


def read_track_cache(year: int, rnd: int, stype: str) -> dict:
    path = _track_cache_path(year, rnd, stype)
    with gzip.open(path, "rb") as f:
        raw = f.read()
    return orjson.loads(raw)


def write_track_cache(year: int, rnd: int, stype: str, data: dict):
    _ensure_dirs()
    path = _track_cache_path(year, rnd, stype)
    clean = sanitize(data)
    raw = orjson.dumps(clean, option=orjson.OPT_SERIALIZE_NUMPY)
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(raw)
    print(f"[cache] Wrote track cache → {path}  ({len(raw):,} bytes raw)")


# ── list all computed caches ─────────────────────────────────────────────

def list_cached() -> list[dict[str, Any]]:
    """Scan computed_data/ and return metadata for every cached session."""
    _ensure_dirs()
    results: list[dict[str, Any]] = []
    for p in sorted(COMPUTED_DIR.glob("*.json.gz")):
        stem = p.stem.replace(".json", "")  # "2024_1_R"
        parts = stem.split("_", 2)
        if len(parts) != 3:
            continue
        try:
            year, rnd, stype = int(parts[0]), int(parts[1]), parts[2]
        except ValueError:
            continue
        size_mb = round(p.stat().st_size / (1024 * 1024), 2)
        results.append({
            "year": year,
            "round": rnd,
            "type": stype,
            "file_size_mb": size_mb,
        })
    return results


# ── background preload ───────────────────────────────────────────────────

def preload_session_sync(year: int, rnd: int, stype: str):
    """
    Synchronous helper — loads via FastF1, computes telemetry, writes
    to the computed cache.  Intended to be called from an executor.

    Adopts graceful degradation: if car telemetry is unavailable (e.g.
    2026 sessions), we still cache whatever data we have rather than
    raising an error.  Each processing step is independent.
    """
    from core.f1_data import (
        enable_cache,
        load_session,
        get_race_telemetry,
        get_quali_telemetry,
    )

    try:
        print(f"[cache] Status transition -> loading (10%)")
        set_status(year, rnd, stype, status="loading", progress=10)
        enable_cache()

        print(f"[cache] Status transition -> loading (20%) - downloading FastF1 data")
        set_status(year, rnd, stype, status="loading", progress=20)
        session = load_session(year, rnd, stype)

        # ── Check car data availability ──────────────────────────────
        has_car_data = False
        try:
            has_car_data = session.car_data is not None and len(session.car_data) > 0
        except Exception:
            pass

        if not has_car_data:
            print(f"[cache] WARNING: No car telemetry for {year} R{rnd} {stype} — position-only mode")

        print(f"[cache] Status transition -> loading (50%) - extracting telemetry")
        set_status(year, rnd, stype, status="loading", progress=50)

        # Progress callback: updates loading status from 50→90% as drivers complete
        def _progress(pct: int):
            set_status(year, rnd, stype, status="loading", progress=pct)

        # ── Telemetry extraction (graceful) ──────────────────────────
        telemetry = None
        try:
            if stype.upper() in ("Q", "SQ", "SS"):
                telemetry = get_quali_telemetry(session, stype, progress_cb=_progress)
            else:
                telemetry = get_race_telemetry(session, stype, progress_cb=_progress)
        except Exception as e:
            print(f"[cache] WARNING: Telemetry extraction failed: {e}")
            if not has_car_data:
                print(f"[cache] Expected for sessions without car data — writing empty cache")
            else:
                import traceback
                traceback.print_exc()

        # ── Write whatever we have ───────────────────────────────────
        if telemetry is None:
            # Build a minimal stub so downstream code doesn't crash
            telemetry = {
                "timeline": [],
                "frames": [],
                "driver_data": {},
                "total_duration": 0,
                "total_laps": 0,
                "_partial": True,
                "_reason": "car telemetry unavailable",
            }
            print(f"[cache] Writing empty/partial cache for {year} R{rnd} {stype}")

        print(f"[cache] Status transition -> loading (90%) - writing to disk")
        set_status(year, rnd, stype, status="loading", progress=90)
        write_computed(year, rnd, stype, telemetry)

        print(f"[cache] Status transition -> cached (100%)")
        set_status(year, rnd, stype, status="cached", source="computed", progress=100)
        print("[cache] Status -> ready")
        print(f"[cache] Preload complete for {year} R{rnd} {stype}")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[cache] Preload FAILED for {year} R{rnd} {stype}: {exc}")
        set_status(year, rnd, stype, status="error", detail=str(exc))

