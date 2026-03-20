"""
/ws/live          –  WebSocket endpoint for real-time F1 25 game telemetry.
/api/sim/sessions –  REST endpoints for managing recorded sim sessions.
/ws/sim-replay    –  WebSocket endpoint for replaying saved sim sessions.

Clients connect to ``/ws/live`` to receive normalised ``frame`` messages
pushed by the :class:`LiveBridge` UDP listener.  Every frame is also
recorded to a JSONL file in ``backend/sim_sessions/``.
"""

from __future__ import annotations

import json
import os
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from core.live_bridge import LiveBridge, SIM_SESSIONS_DIR

router = APIRouter(tags=["live"])


# ═══════════════════════════════════════════════════════════════════════════
# /ws/live — F1 25 game telemetry WebSocket
# ═══════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/live")
async def live_ws(ws: WebSocket):
    await ws.accept()
    bridge = LiveBridge.get()

    if not bridge.is_running:
        try:
            await bridge.start()
        except OSError:
            await ws.send_json({
                "type": "error",
                "message": "UDP port 20777 is already in use. Close other F1 apps and reconnect."
            })
            await ws.close()
            return

    # Tell the frontend we're ready and what file we're recording to
    await ws.send_json({
        "type": "ready",
        "mode": "sim",
        "recording_filename": bridge.recording_filename,
    })

    await bridge.add_client(ws)
    try:
        # keep the connection open; ignore any incoming messages
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        bridge.remove_client(ws)


# ═══════════════════════════════════════════════════════════════════════════
# /api/live/network-info
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/live/network-info")
async def get_network_info():
    """Return local IP addresses for F1 25 UDP telemetry configuration."""
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.getaddrinfo(hostname, None):
            if ip[0].name == "AF_INET":
                ips.append(ip[4][0])
    except Exception:
        pass

    # ensure 127.0.0.1 is always present as fallback
    if not ips:
        ips.append("127.0.0.1")

    return {
        "hostname": socket.gethostname(),
        "ips": list(set(ips)),
        "port": 20777
    }


# ═══════════════════════════════════════════════════════════════════════════
# /api/sim/record — Start / Stop recording
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/api/sim/record/start")
async def start_recording():
    """Start recording the current sim session to a JSONL file."""
    bridge = LiveBridge.get()
    if not bridge.is_running:
        return {"error": "LiveBridge is not running"}, 400
    if bridge.is_recording:
        return {"recording": True, "filename": bridge.recording_filename}
    fname = bridge.start_recording()
    return {"recording": True, "filename": fname}


@router.post("/api/sim/record/stop")
async def stop_recording():
    """Stop recording and return the filename."""
    bridge = LiveBridge.get()
    if not bridge.is_recording:
        return {"recording": False, "filename": None}
    fname = bridge.stop_recording()
    return {"recording": False, "filename": fname}


@router.get("/api/sim/record/status")
async def recording_status():
    """Check current recording state."""
    bridge = LiveBridge.get()
    return {
        "recording": bridge.is_recording,
        "filename": bridge.recording_filename,
    }


# ═══════════════════════════════════════════════════════════════════════════
# /api/sim/sessions — List / Save / Delete recorded sim sessions
# ═══════════════════════════════════════════════════════════════════════════

def _parse_session_meta(filepath: Path) -> dict:
    """Extract metadata from a JSONL session file."""
    fname = filepath.name
    stat = filepath.stat()

    # Parse filename: {timestamp}_{trackname}.jsonl
    stem = filepath.stem
    parts = stem.split("_", 1)
    try:
        ts = int(parts[0])
        track = parts[1] if len(parts) > 1 else "unknown"
    except (ValueError, IndexError):
        ts = int(stat.st_mtime)
        track = stem

    # Count lines + get first/last timestamps for duration/lap count
    line_count = 0
    first_ts = 0.0
    last_ts = 0.0
    max_lap = 1
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                line_count += 1
                try:
                    frame = json.loads(line)
                    t = frame.get("timestamp", 0.0)
                    if line_count == 1:
                        first_ts = t
                    last_ts = t
                    lap = frame.get("lap", 1)
                    if lap > max_lap:
                        max_lap = lap
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass

    return {
        "filename": fname,
        "track": track,
        "date": datetime.fromtimestamp(ts).isoformat(),
        "timestamp": ts,
        "lap_count": max_lap,
        "duration": round(last_ts - first_ts, 1),
        "frame_count": line_count,
        "size_bytes": stat.st_size,
    }


@router.get("/api/sim/sessions")
async def list_sim_sessions():
    """List all recorded sim sessions with metadata."""
    SIM_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []
    for f in sorted(SIM_SESSIONS_DIR.glob("*.jsonl"), reverse=True):
        try:
            sessions.append(_parse_session_meta(f))
        except Exception:
            pass
    return {"sessions": sessions}


@router.post("/api/sim/sessions/{filename}/save")
async def save_sim_session(filename: str, name: str = Query(..., description="Display name for the session")):
    """Rename / finalize a recording with a user-chosen name."""
    src = SIM_SESSIONS_DIR / filename
    if not src.exists() or not src.suffix == ".jsonl":
        return {"error": "Session not found"}, 404

    # Build new filename: keep the timestamp prefix, replace track with name
    stem = src.stem
    parts = stem.split("_", 1)
    ts_part = parts[0] if parts else stem
    # Sanitise the name for filesystem use
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip().replace(" ", "_")
    if not safe_name:
        safe_name = "session"

    new_name = f"{ts_part}_{safe_name}.jsonl"
    dst = SIM_SESSIONS_DIR / new_name

    if dst.exists() and dst != src:
        return {"error": "A session with that name already exists"}, 409

    src.rename(dst)
    return {"filename": new_name, "name": name}


@router.delete("/api/sim/sessions/{filename}")
async def delete_sim_session(filename: str):
    """Delete a recorded sim session."""
    path = SIM_SESSIONS_DIR / filename
    if not path.exists() or not path.suffix == ".jsonl":
        return {"error": "Session not found"}, 404
    path.unlink()
    return {"deleted": filename}


# ═══════════════════════════════════════════════════════════════════════════
# /ws/sim-replay/{filename} — Replay a saved sim session
# ═══════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/sim-replay/{filename}")
async def sim_replay_ws(ws: WebSocket, filename: str):
    """Replay a saved JSONL sim session, supporting play/pause/seek/speed."""
    await ws.accept()

    path = SIM_SESSIONS_DIR / filename
    if not path.exists() or not path.suffix == ".jsonl":
        await ws.send_json({"type": "error", "detail": "Session file not found"})
        await ws.close()
        return

    # Load all frames
    frames: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        frames.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        await ws.send_json({"type": "error", "detail": str(exc)})
        await ws.close()
        return

    if not frames:
        await ws.send_json({"type": "error", "detail": "Session has no frames"})
        await ws.close()
        return

    print(f"[SimReplay] Opening {filename}, {len(frames)} frames")
    if frames:
        first = frames[0]
        print(f"[SimReplay] First frame: timestamp={first.get('timestamp')}, drivers={len(first.get('drivers', []))}")

    # Send ready
    total_duration = frames[-1].get("timestamp", 0) - frames[0].get("timestamp", 0)
    max_lap = max((f.get("lap", 1) for f in frames), default=1)

    await ws.send_json({
        "type": "ready",
        "mode": "sim",
        "total_frames": len(frames),
        "total_duration": round(total_duration, 1),
        "total_laps": max_lap,
    })

    # Playback engine state
    index = 0
    playing = False
    speed = 1.0
    STREAM_HZ = 10
    SEND_INTERVAL = 1.0 / STREAM_HZ

    # Approximate source FPS from the data
    if len(frames) > 1 and total_duration > 0:
        source_fps = len(frames) / total_duration
    else:
        source_fps = 10.0
    frames_per_tick = source_fps / STREAM_HZ

    async def reader():
        nonlocal index, playing, speed
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                action = msg.get("action", "")
                if action == "play":
                    playing = True
                    await ws.send_json({"type": "ack", "action": "play"})
                elif action == "pause":
                    playing = False
                    await ws.send_json({"type": "ack", "action": "pause"})
                elif action == "seek":
                    target = float(msg.get("timestamp", 0))
                    # find nearest frame
                    best = 0
                    for i, f in enumerate(frames):
                        if f.get("timestamp", 0) <= target:
                            best = i
                    index = best
                    await ws.send_json({"type": "ack", "action": "seek", "timestamp": frames[index].get("timestamp", 0)})
                elif action == "speed":
                    val = float(msg.get("value", 1))
                    if val in (0.5, 1, 2, 4, 8):
                        speed = val
                    await ws.send_json({"type": "ack", "action": "speed", "value": speed})
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def writer():
        nonlocal index, playing
        import time as _time
        try:
            while True:
                tick_start = _time.perf_counter()

                if playing and frames:
                    idx = max(0, min(int(index), len(frames) - 1))
                    await ws.send_json(frames[idx])

                    index += speed * frames_per_tick
                    if index >= len(frames):
                        index = len(frames) - 1
                        playing = False
                        await ws.send_json({"type": "finished"})

                elapsed = _time.perf_counter() - tick_start
                await asyncio.sleep(max(0, SEND_INTERVAL - elapsed))
        except (WebSocketDisconnect, RuntimeError):
            pass

    try:
        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        done, pending = await asyncio.wait(
            {reader_task, writer_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close()
        except Exception:
            pass
