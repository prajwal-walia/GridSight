"""
/ws/live-f1/{year}/{round}/{session}  –  Live F1 SignalR timing WebSocket.
/api/live/status                     –  Check if a session is currently live.

Streams real-time F1 timing data from the official SignalR feed,
normalized to the GridSight frame schema, at 2 Hz.

Features:
  - Broadcast delay slider (0-60 seconds) — buffers frames and releases
    them with the specified delay.  Clients send
    ``{"command": "delay", "seconds": N}`` to change the delay live.
  - Post-session replay — when the session ends, the buffered frames are
    replayed at 2 Hz so late-joiners (or delayed viewers) see the full
    session.

Does NOT touch /ws/live (F1 25 UDP) or /ws/replay — those stay unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live-f1"])

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_live_sessions: dict[str, "LiveF1Session"] = {}

# Map session type path params to short codes
_SESSION_TYPE_MAP: dict[str, str] = {
    "race": "R",
    "qualifying": "Q",
    "sprint": "S",
    "sprint_qualifying": "SQ",
    "fp1": "FP1",
    "fp2": "FP2",
    "fp3": "FP3",
    # Also accept the short codes directly
    "R": "R",
    "Q": "Q",
    "S": "S",
    "SQ": "SQ",
    "FP1": "FP1",
    "FP2": "FP2",
    "FP3": "FP3",
}

# Maximum number of frames to keep in the replay buffer (~2 Hz × 3 hours)
_MAX_BUFFER_FRAMES = 25_000


class LiveF1Session:
    """Manages a single live SignalR session with fan-out to multiple WS clients."""

    def __init__(self, key: str, session_type: str):
        self.key = key
        self.session_type = session_type
        self.clients: list[WebSocket] = []
        self._state_manager = None
        self._signalr_client = None
        self._task: asyncio.Task | None = None
        self._started = False
        self._msg_logged = False

        # Frame buffer for delay slider and post-session replay
        # Each entry is (wall_clock_ts, frame_dict)
        self._frame_buffer: deque[tuple[float, dict]] = deque(maxlen=_MAX_BUFFER_FRAMES)
        self._buffer_lock = asyncio.Lock()

    async def start(self) -> None:
        """Connect to the F1 SignalR stream and start accumulating state."""
        if self._started:
            return

        from core.live_state import LiveStateManager
        from core.live_signalr import LiveSignalRClient

        self._state_manager = LiveStateManager(session_type=self.session_type)
        self._signalr_client = LiveSignalRClient()
        self._task = asyncio.create_task(self._run_signalr())
        self._started = True
        logger.info("LiveF1 session started: %s", self.key)

    async def _run_signalr(self) -> None:
        """Run the SignalR client, feeding messages into the state manager."""
        try:
            await self._signalr_client.connect(self._on_message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("SignalR error in session %s: %s", self.key, e)

    async def _on_message(self, topic: str, data: dict, timestamp: float) -> None:
        """Handle a message from SignalR."""
        if not self._msg_logged:
            logger.info("First SignalR message for %s: topic=%s", self.key, topic)
            self._msg_logged = True
        self._state_manager.process_message(topic, data, timestamp)

    def get_frame(self) -> dict | None:
        """Get the current GridSight-schema frame."""
        if self._state_manager is None:
            return None
        return self._state_manager.get_frame()

    async def snapshot_and_buffer(self) -> dict | None:
        """Take a frame snapshot and add it to the replay buffer.

        Called by the broadcast loop at 2 Hz.
        """
        frame = self.get_frame()
        if frame is not None:
            wall_ts = time.time()
            async with self._buffer_lock:
                self._frame_buffer.append((wall_ts, frame))
        return frame

    def add_client(self, ws: WebSocket) -> None:
        self.clients.append(ws)

    def remove_client(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    @property
    def client_count(self) -> int:
        return len(self.clients)

    @property
    def is_session_finished(self) -> bool:
        """True if the session was started and has since finished/finalised."""
        if self._state_manager is None:
            return False
        return (
            self._state_manager.session_was_started
            and self._state_manager.session_status in ("Finalised", "Finished", "Ends")
        )

    @property
    def session_status(self) -> str:
        if self._state_manager is None:
            return "Inactive"
        return self._state_manager.session_status

    async def get_buffer_copy(self) -> list[tuple[float, dict]]:
        """Return a copy of the frame buffer for replay."""
        async with self._buffer_lock:
            return list(self._frame_buffer)

    async def stop(self) -> None:
        if self._signalr_client:
            await self._signalr_client.disconnect()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._started = False
        logger.info("LiveF1 session stopped: %s", self.key)


async def _get_or_create_session(
    year: int, round_num: int, session_type: str
) -> LiveF1Session:
    """Get existing live session or create a new one."""
    key = f"{year}_{round_num}_{session_type}"

    if key not in _live_sessions:
        session = LiveF1Session(key, session_type)
        _live_sessions[key] = session
        await session.start()

    return _live_sessions[key]


# ---------------------------------------------------------------------------
# WebSocket endpoint — fans out at 2 Hz with per-client delay
# ---------------------------------------------------------------------------

@router.websocket("/ws/live-f1/{year}/{round_num}/{session}")
async def live_f1_websocket(
    websocket: WebSocket,
    year: int,
    round_num: int,
    session: str,
):
    """Stream live F1 timing data at 2 Hz in the GridSight frame schema.

    Supports per-client broadcast delay via WebSocket commands:
      {"command": "delay", "seconds": 15}

    When the session ends, automatically replays the buffered frames.
    """
    await websocket.accept()

    # Resolve session type
    session_type = _SESSION_TYPE_MAP.get(session, session.upper())

    # Per-client delay (seconds)
    client_delay: float = 0.0

    live_session: LiveF1Session | None = None
    try:
        live_session = await _get_or_create_session(year, round_num, session_type)
        live_session.add_client(websocket)

        # Send ready handshake
        await websocket.send_json({
            "type": "ready",
            "mode": "live-f1",
            "session": f"{year}/{round_num}/{session_type}",
        })

        # Broadcast loop: push frames at 2 Hz
        frame_interval = 0.5

        # Per-client pending frame queue (for delay)
        pending_frames: deque[tuple[float, dict]] = deque()

        async def handle_commands():
            """Listen for client commands (delay changes, keep-alive)."""
            nonlocal client_delay
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        cmd = json.loads(raw)
                        if cmd.get("command") == "delay":
                            new_delay = float(cmd.get("seconds", 0))
                            client_delay = max(0.0, min(60.0, new_delay))
                            logger.info(
                                "Client delay updated to %.1fs for %s",
                                client_delay, live_session.key
                            )
                            await websocket.send_json({
                                "type": "delay_ack",
                                "seconds": client_delay,
                            })
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
            except WebSocketDisconnect:
                pass

        command_task = asyncio.create_task(handle_commands())

        try:
            while True:
                # Snapshot current state and buffer it
                frame = await live_session.snapshot_and_buffer()

                if frame:
                    now = time.time()

                    if client_delay <= 0:
                        # No delay — send immediately
                        await websocket.send_json({"type": "frame", **frame})
                    else:
                        # Buffer the frame with its wall-clock timestamp
                        pending_frames.append((now, frame))

                        # Release all frames older than the delay
                        while pending_frames:
                            oldest_ts, oldest_frame = pending_frames[0]
                            if now - oldest_ts >= client_delay:
                                pending_frames.popleft()
                                await websocket.send_json({"type": "frame", **oldest_frame})
                            else:
                                break

                # Check if session has finished
                if live_session.is_session_finished:
                    # Notify client that session has ended
                    await websocket.send_json({
                        "type": "session_ended",
                        "message": "Session has ended — replaying buffered data",
                        "replay": True,
                    })

                    # Drain any remaining delayed frames
                    while pending_frames:
                        _, delayed_frame = pending_frames.popleft()
                        await websocket.send_json({"type": "frame", **delayed_frame})
                        await asyncio.sleep(0.05)

                    # Replay the full buffer
                    await _replay_buffer(websocket, live_session)
                    break

                await asyncio.sleep(frame_interval)
        finally:
            command_task.cancel()

    except WebSocketDisconnect:
        logger.info("LiveF1 WS disconnected: %s/%s/%s", year, round_num, session)
    except Exception as e:
        logger.error("LiveF1 WS error: %s", e)
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        if live_session:
            live_session.remove_client(websocket)
            # Clean up session if no more clients (2s grace for React Strict Mode)
            if live_session.client_count == 0:
                await asyncio.sleep(2)
                if live_session.client_count == 0:
                    key = f"{year}_{round_num}_{session_type}"
                    if key in _live_sessions:
                        await live_session.stop()
                        del _live_sessions[key]


async def _replay_buffer(websocket: WebSocket, live_session: LiveF1Session) -> None:
    """Replay the session's buffered frames at 2 Hz."""
    buffer = await live_session.get_buffer_copy()
    if not buffer:
        await websocket.send_json({
            "type": "finished",
            "message": "Session ended — no buffered data to replay.",
        })
        return

    logger.info(
        "Starting post-session replay of %d frames for %s",
        len(buffer), live_session.key
    )

    for i, (_, frame) in enumerate(buffer):
        try:
            await websocket.send_json({"type": "frame", **frame})
        except Exception:
            return  # Client disconnected during replay
        # Pace at 2 Hz
        if i < len(buffer) - 1:
            await asyncio.sleep(0.5)

    await websocket.send_json({
        "type": "finished",
        "message": "Session ended — replay complete.",
    })
    logger.info("Post-session replay complete for %s", live_session.key)


# ---------------------------------------------------------------------------
# GET /api/live/status — check if a session is currently live
# ---------------------------------------------------------------------------

@router.get("/api/live/status")
async def live_status(
    year: int = Query(0, description="Year (0 = current)"),
    round: int = Query(0, description="Round number (0 = next)"),
):
    """Check if an F1 session is currently live using the FastF1 schedule.

    Returns session info and whether it's currently active.
    """
    import functools

    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None, functools.partial(_check_live_status, year, round)
        )
        return result
    except Exception as e:
        logger.exception("Error checking live status")
        return {
            "live": False,
            "error": str(e),
        }


def _check_live_status(year: int, round_num: int) -> dict:
    """Synchronous helper — queries FastF1 schedule to determine if a session
    is currently live.

    Returns a dict with:
      - live: bool
      - year, round, session_type, event_name (if applicable)
      - starts_at, ends_at (ISO strings)
    """
    try:
        import fastf1
    except ImportError:
        return {"live": False, "error": "FastF1 not installed"}

    now = datetime.now(timezone.utc)

    if year == 0:
        year = now.year

    try:
        schedule = fastf1.get_event_schedule(year)
    except Exception as e:
        return {"live": False, "error": f"Could not load schedule: {e}"}

    # Session column names in the schedule
    session_cols = [
        ("Session1", "Session1DateUtc", "FP1"),
        ("Session2", "Session2DateUtc", "FP2"),
        ("Session3", "Session3DateUtc", "FP3"),
        ("Session4", "Session4DateUtc", "Q"),
        ("Session5", "Session5DateUtc", "R"),
    ]

    # If round specified, only check that round
    if round_num > 0:
        events = schedule[schedule["RoundNumber"] == round_num]
    else:
        events = schedule[schedule["RoundNumber"] > 0]

    for _, event in events.iterrows():
        event_name = event.get("EventName", "Unknown")
        event_round = int(event.get("RoundNumber", 0))

        for session_name_col, date_col, session_code in session_cols:
            if date_col not in event.index:
                continue

            session_date = event.get(date_col)
            if session_date is None or str(session_date) == "NaT":
                continue

            import pandas as pd
            if isinstance(session_date, pd.Timestamp):
                if session_date.tzinfo is None:
                    session_date = session_date.tz_localize("UTC")
                session_start = session_date.to_pydatetime()
            else:
                continue

            # Session durations (approximate)
            duration_map = {"FP1": 60, "FP2": 60, "FP3": 60, "Q": 75, "R": 150, "S": 60, "SQ": 45}
            duration_mins = duration_map.get(session_code, 120)

            from datetime import timedelta
            session_end = session_start + timedelta(minutes=duration_mins)

            if session_start <= now <= session_end:
                return {
                    "live": True,
                    "year": year,
                    "round": event_round,
                    "session_type": session_code,
                    "event_name": event_name,
                    "starts_at": session_start.isoformat(),
                    "ends_at": session_end.isoformat(),
                }

    # Check for upcoming session (next one that hasn't ended yet)
    upcoming = None
    for _, event in events.iterrows():
        event_name = event.get("EventName", "Unknown")
        event_round = int(event.get("RoundNumber", 0))

        for session_name_col, date_col, session_code in session_cols:
            if date_col not in event.index:
                continue
            session_date = event.get(date_col)
            if session_date is None or str(session_date) == "NaT":
                continue

            import pandas as pd
            if isinstance(session_date, pd.Timestamp):
                if session_date.tzinfo is None:
                    session_date = session_date.tz_localize("UTC")
                session_start = session_date.to_pydatetime()
            else:
                continue

            if session_start > now:
                if upcoming is None or session_start < upcoming["starts_at_dt"]:
                    upcoming = {
                        "year": year,
                        "round": event_round,
                        "session_type": session_code,
                        "event_name": event_name,
                        "starts_at": session_start.isoformat(),
                        "starts_at_dt": session_start,
                    }

    if upcoming:
        upcoming.pop("starts_at_dt", None)
        return {"live": False, "next_session": upcoming}

    return {"live": False}
