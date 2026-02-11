"""
/ws/replay/{session_id}  –  WebSocket replay route.

session_id format:  ``{year}_{round}_{type}``  e.g. ``2024_1_R``

Connection lifecycle:
  1. accept → send {"type":"status","status":"preparing"}
  2. while data loads → send {"type":"ping"} every 3 s to keep alive
  3. data ready      → send {"type":"ready", total_frames, total_duration, total_laps}
  4. engine.run()    → stream frames
  5. disconnect      → clean exit, no crash
"""

from __future__ import annotations

import asyncio
import functools

import pandas as pd
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.sessions import _get_session          # shared LRU session cache
from core.f1_data import get_race_telemetry, get_driver_num_from_session, _pick_driver_laps
from core.cache_manager import (
    has_computed_cache,
    read_computed,
    write_computed,
    set_status,
)
from core.replay_engine import ReplayEngine

router = APIRouter(tags=["replay"])


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )


def _parse_session_id(session_id: str):
    """Return (year, round, type) from ``'2024_1_R'``."""
    parts = session_id.split("_", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return int(parts[0]), int(parts[1]), parts[2].upper()


def _compute_retirements(session) -> dict[str, float]:
    """Build { driver_code: last_timestamp_seconds } for retired drivers."""
    retirements: dict[str, float] = {}
    if session.results is None or session.results.empty:
        return retirements

    for _, row in session.results.iterrows():
        status = str(row.get("Status", ""))
        if "Finished" in status or "Lap" in status:
            continue  # completed the race
        code = str(row.get("Abbreviation", "")).strip()[:3].upper()
        if not code:
            continue
        try:
            try:
                year = int(session.event['EventDate'].year)
            except Exception:
                year = 2025
            _ret_num = get_driver_num_from_session(session, code, year)
            dlaps = _pick_driver_laps(session.laps, code, _ret_num)
            if dlaps is not None and not dlaps.empty:
                last = dlaps.iloc[-1]
                if pd.notna(last.get("Time")):
                    t = last["Time"]
                    if hasattr(t, 'total_seconds'):
                        retirements[code] = float(t.total_seconds())
                    elif hasattr(t, 'timestamp'):
                        retirements[code] = float(t.timestamp())
                    else:
                        retirements[code] = float(t)
        except Exception:
            pass
    return retirements


async def _send_safe(ws: WebSocket, data: dict) -> bool:
    """Send JSON over WS; return False if the peer already disconnected."""
    try:
        await ws.send_json(data)
        return True
    except (WebSocketDisconnect, RuntimeError, Exception):
        return False


@router.websocket("/ws/replay/{session_id}")
async def replay_ws(ws: WebSocket, session_id: str):
    await ws.accept()

    # ── 1. Immediately tell the client we're preparing ────────────────
    if not await _send_safe(ws, {"type": "status", "status": "preparing"}):
        return

    # ── parse ─────────────────────────────────────────────────────────
    try:
        year, rnd, stype = _parse_session_id(session_id)
    except ValueError as exc:
        await _send_safe(ws, {"type": "error", "detail": str(exc)})
        try:
            await ws.close()
        except Exception:
            pass
        return

    # ── 2. Start a keepalive ping task ────────────────────────────────
    ping_active = True

    async def _keepalive():
        """Send {"type":"ping"} every 3 s while data is being prepared."""
        while ping_active:
            await asyncio.sleep(3)
            if not ping_active:
                break
            try:
                await ws.send_json({"type": "ping"})
            except (WebSocketDisconnect, RuntimeError, Exception):
                break

    ping_task = asyncio.create_task(_keepalive())

    # ── load telemetry ────────────────────────────────────────────────
    try:
        from core.cache_manager import get_preload_lock
        lock = get_preload_lock(session_id)

        if lock.locked() and not has_computed_cache(year, rnd, stype):
            await _send_safe(ws, {"type": "status", "status": "waiting", "message": "Session loading in progress, please wait..."})

        async with lock:
            if has_computed_cache(year, rnd, stype):
                await _send_safe(ws, {"type": "status", "status": "preparing", "message": "Loading from cache…"})
                telemetry = await _run(read_computed, year, rnd, stype)
                print(f"[replay] Loaded from computed cache: {year}_R{rnd}_{stype}")

                retirements: dict[str, float] = {}
                try:
                    session = await _get_session(year, rnd, stype)
                    retirements = _compute_retirements(session)
                except Exception:
                    pass
            else:
                print(f"[replay] Status -> loading (10%) for {year}_R{rnd}_{stype}")
                set_status(year, rnd, stype, status="loading", progress=10)
                await _send_safe(ws, {"type": "status", "status": "preparing", "message": "Loading session…"})
                session = await _get_session(year, rnd, stype)

                print(f"[replay] Status -> loading (40%) - computing telemetry")
                set_status(year, rnd, stype, status="loading", progress=40)
                await _send_safe(ws, {"type": "status", "status": "preparing", "message": "Computing telemetry…"})
                telemetry = await _run(get_race_telemetry, session, stype)

                print(f"[replay] Status -> loading (70%) - telemetry complete")
                set_status(year, rnd, stype, status="loading", progress=70)

                retirements = _compute_retirements(session)

                # Mark as cached immediately so the frontend knows
                print(f"[replay] Status -> cached (100%) for {year}_R{rnd}_{stype}")
                set_status(year, rnd, stype, status="cached", source="computed", progress=100)

                # Write cache to disk in background — don't block the WebSocket
                async def _bg_cache_write():
                    try:
                        await _run(write_computed, year, rnd, stype, telemetry)
                        print(f"[replay] Background cache write complete: {year}_R{rnd}_{stype}")
                    except Exception as e:
                        print(f"[replay] Background cache write failed: {e}")

                asyncio.create_task(_bg_cache_write())

    except (WebSocketDisconnect, RuntimeError):
        # Client hung up during preparation — clean exit
        print(f"[replay] Client disconnected during load for {year}_R{rnd}_{stype}")
        ping_active = False
        ping_task.cancel()
        return
    except asyncio.CancelledError:
        print(f"[replay] Connection cancelled during load for {session_id}")
        ping_active = False
        ping_task.cancel()
        return
    except Exception as exc:
        ping_active = False
        ping_task.cancel()
        print(f"[replay] Status -> error for {year}_R{rnd}_{stype}: {exc}")
        set_status(year, rnd, stype, status="error", detail=str(exc))
        await _send_safe(ws, {"type": "error", "detail": str(exc)})
        telemetry = {
            "frames": [],
            "total_laps": 0,
            "driver_info": {},
            "_partial": True,
            "_reason": str(exc),
        }
        retirements = {}

    # ── 3. Stop pings, send "ready" ───────────────────────────────────
    ping_active = False
    ping_task.cancel()

    frames = telemetry.get("frames", [])
    ready_msg = {
        "type":           "ready",
        "total_frames":   len(frames),
        "total_duration": frames[-1]["t"] if frames else 0,
        "total_laps":     telemetry.get("total_laps", 0),
        "driver_info":    telemetry.get("driver_info", {}),
    }
    if not await _send_safe(ws, ready_msg):
        return

    # ── 4. Run the replay engine (fully wrapped) ──────────────────────
    try:
        engine = ReplayEngine(telemetry, retirements=retirements)
    except (KeyError, ValueError) as e:
        print(f"[replay] Bad cache for {session_id}: {e} — deleting and recomputing")
        import os
        from core.cache_manager import COMPUTED_DIR
        cache_file = os.path.join(COMPUTED_DIR, f"{session_id}.json.gz")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        await ws.send_json({"type": "error", "message": "Session cache corrupted — please reload to recompute"})
        await ws.close()
        return
    try:
        await engine.run(ws)
    except (WebSocketDisconnect, RuntimeError):
        pass  # clean exit
    except Exception as exc:
        print(f"[replay] Engine error: {exc}")
    finally:
        try:
            if ws.client_state == ws.client_state.CONNECTED:
                await ws.close()
        except Exception:
            pass
