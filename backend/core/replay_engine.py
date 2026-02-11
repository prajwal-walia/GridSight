"""
Replay engine that streams pre-computed race frames over a WebSocket.

The engine is fed the dict returned by ``get_race_telemetry()`` and
supports play / pause / seek / speed / rewind client commands.
"""

from __future__ import annotations

import asyncio
import json
import math
import numpy as np
from bisect import bisect_right
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

# ── constants ────────────────────────────────────────────────────────────

SOURCE_FPS = 25          # frames per second in the precomputed data
STREAM_HZ  = 4           # how often we push over the wire (per second)
FRAMES_PER_TICK = SOURCE_FPS / STREAM_HZ  # ≈ 6.25
SEND_INTERVAL  = 1.0 / STREAM_HZ          # 0.25 s

VALID_SPEEDS = {0.5, 1, 2, 4, 8}

FLAG_MAP: dict[str, str] = {
    "1": "GREEN",
    "2": "YELLOW",
    "3": "SC_ENDING",
    "4": "SAFETY_CAR",
    "5": "RED",
    "6": "VSC",
    "7": "VSC_ENDING",
}




# ── engine ───────────────────────────────────────────────────────────────

class ReplayEngine:
    """Manage playback state and transform / stream frames."""

    def __init__(
        self,
        telemetry: dict[str, Any],
        retirements: dict[str, float] | None = None,
    ):
        if "frames" not in telemetry or not telemetry["frames"]:
            raise ValueError(f"Cache missing frames key. Keys present: {list(telemetry.keys())}")
        self.frames: list[dict]       = telemetry["frames"]
        self.track_statuses: list[dict] = telemetry.get("track_statuses", [])
        self.total_laps: int          = telemetry.get("total_laps", 0)
        self.race_control_messages: list[dict] = telemetry.get("race_control_messages", [])
        self.event_name: str          = telemetry.get("event_name", "")

        # driver_code → timestamp (s) after which the driver is OUT
        self.retirements = retirements or {}

        # Pit prediction data (loaded lazily)
        self._pit_loss: dict[str, float] | None = None
        self._pit_loss_loaded = False

        # ── playback state ────────────────────────────────────────────
        self.index: float   = 0.0
        self.playing: bool  = False
        self.speed: float   = 1.0
        self.direction: int = 1   # +1 forward, −1 rewind

    # ── pit loss lookup ──────────────────────────────────────────────

    def _get_pit_loss(self) -> dict[str, float] | None:
        """Lazy-load pit loss data for this session's circuit."""
        if not self._pit_loss_loaded:
            self._pit_loss_loaded = True
            try:
                from core.pit_prediction import get_pit_loss_for_event
                self._pit_loss = get_pit_loss_for_event(self.event_name)
            except Exception:
                self._pit_loss = None
        return self._pit_loss

    # ── flag lookup ───────────────────────────────────────────────────

    def _flag_at(self, t: float) -> str:
        """Return the human-readable flag string for timestamp *t*."""
        flag = "GREEN"
        for s in self.track_statuses:
            if s["start_time"] <= t:
                end = s.get("end_time")
                if end is None or t < end:
                    flag = FLAG_MAP.get(str(s["status"]), "GREEN")
            elif s["start_time"] > t:
                break
        return flag

    # ── frame transform ──────────────────────────────────────────────

    def _build_output(self, idx: int) -> dict:
        """Convert an internal frame to the public schema."""
        raw = self.frames[idx]
        t   = raw["t"]
        current_flag = self._flag_at(t)

        drivers_out: list[dict] = []
        for code, d in raw["drivers"].items():
            driver_dict = {
                "code":     code,
                "position": d["position"],
                "x":        d["x"],
                "y":        d["y"],
                "speed":    d["speed"],
                "gear":     d["gear"],
                "drs":      bool(d["drs"]),
                "overtake_mode_active": int(d["drs"]) > 10 if "drs" in d else False,
                "straight_mode_active": int(d["drs"]) >= 10 if "drs" in d else False,
                "throttle": d["throttle"],
                "brake":    d["brake"],
                "tyre":     int(d["tyre"]),
                "tyre_age": int(d["tyre_life"]),
                "is_out":   code in self.retirements and t > self.retirements[code],
                "sector1":  d.get("sector1"),
                "sector2":  d.get("sector2"),
                "sector3":  d.get("sector3"),
                "last_lap_time": d.get("last_lap_time"),
                "gap_to_leader": d.get("gap_to_leader", 0.0),
                "interval":      d.get("interval", 0.0),
                "tyre_history":  d.get("tyre_history", []),
                "pit_count":     d.get("pit_count", 0),
                "grid_position": d.get("grid_position"),
                "under_investigation": d.get("under_investigation", False),
                "pit_prediction": None,  # filled below
            }
            drivers_out.append(driver_dict)
            print(f"DEBUG DRIVER DICT (replay_engine): code={driver_dict.get('code')!r} is_out={driver_dict.get('is_out')!r}")

        # ── Pit predictions ──────────────────────────────────────────
        try:
            pit_loss = self._get_pit_loss()
            if pit_loss:
                from core.pit_prediction import compute_pit_predictions
                predictions = compute_pit_predictions(
                    drivers=drivers_out,
                    pit_loss_green=pit_loss["pit_loss_green"],
                    pit_loss_sc=pit_loss["pit_loss_sc"],
                    pit_loss_vsc=pit_loss["pit_loss_vsc"],
                    flag=current_flag,
                    lap=raw.get("lap", 0),
                )
                for d in drivers_out:
                    d["pit_prediction"] = predictions.get(d["code"])
        except Exception:
            pass  # Never crash the frame

        # ── Weather ──────────────────────────────────────────────────
        w = raw.get("weather", {})
        rain_state = w.get("rain_state", "DRY") if w else "DRY"
        weather_out = {
            "air_temp":       w.get("air_temp"),
            "track_temp":     w.get("track_temp"),
            "humidity":       w.get("humidity"),
            "wind_speed":     w.get("wind_speed"),
            "wind_direction": w.get("wind_direction"),
            "rainfall":       rain_state == "RAINING",
            "flag":           current_flag,
        }

        # ── Race control ─────────────────────────────────────────────
        race_control = raw.get("race_control")
        if race_control is None:
            # Fallback: build minimal race_control from track status
            race_control = {
                "messages": [],
                "current_flag": current_flag,
                "sc_deployed": current_flag in ("SAFETY_CAR", "SC", "SC_ENDING"),
                "vsc_deployed": current_flag in ("VSC", "VSC_ENDING"),
                "yellow_sectors": [],
            }

        return {
            "type":          "frame",
            "timestamp":     t,
            "lap":           raw["lap"],
            "drivers":       drivers_out,
            "weather":       weather_out,
            "race_control":  race_control,
        }

    # ── control handling ─────────────────────────────────────────────

    def handle(self, msg: dict) -> dict | None:
        """Process a client control message.  Returns an optional ack."""
        action = msg.get("action", "")

        if action == "play":
            self.playing   = True
            self.direction = 1
            return {"type": "ack", "action": "play"}

        if action == "pause":
            self.playing = False
            return {"type": "ack", "action": "pause"}

        if action == "seek":
            target = float(msg.get("timestamp", 0))
            # binary search for nearest frame
            times = [f["t"] for f in self.frames]
            i = bisect_right(times, target)
            self.index = max(0, min(i, len(self.frames) - 1))
            return {"type": "ack", "action": "seek", "timestamp": self.frames[int(self.index)]["t"]}

        if action == "speed":
            val = float(msg.get("value", 1))
            if val in VALID_SPEEDS:
                self.speed = val
            return {"type": "ack", "action": "speed", "value": self.speed}

        if action == "rewind":
            self.playing   = True
            self.direction = -1
            return {"type": "ack", "action": "rewind"}

        return {"type": "error", "detail": f"unknown action '{action}'"}

    # ── main loop ────────────────────────────────────────────────────

    async def run(self, ws: WebSocket):
        """
        Start two concurrent tasks:
          1. *_reader* — listens for client control messages.
          2. *_writer* — streams frames at the configured speed.
        Exits cleanly on disconnect.
        """
        try:
            reader_task = asyncio.create_task(self._reader(ws))
            writer_task = asyncio.create_task(self._writer(ws))

            done, pending = await asyncio.wait(
                {reader_task, writer_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass  # clean exit on client disconnect

    # ── internal tasks ───────────────────────────────────────────────

    async def _reader(self, ws: WebSocket):
        """Read and dispatch client control messages until disconnect."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "detail": "invalid JSON"})
                    continue
                ack = self.handle(msg)
                if ack:
                    await ws.send_json(ack)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _writer(self, ws: WebSocket):
        """Push frames at STREAM_HZ, honouring speed and direction."""
        import time as _time
        try:
            while True:
                tick_start = _time.perf_counter()

                if self.playing and self.frames:
                    idx = int(self.index)
                    idx = max(0, min(idx, len(self.frames) - 1))
                    
                    frame = self._build_output(idx)
                    
                    # Only fix numpy scalars, leave everything else untouched
                    def fix_numpy(obj):
                        if isinstance(obj, dict):
                            return {k: fix_numpy(v) for k, v in obj.items()}
                        elif isinstance(obj, list):
                            return [fix_numpy(i) for i in obj]
                        elif isinstance(obj, np.bool_):
                            return bool(obj)
                        elif isinstance(obj, np.integer):
                            return int(obj)
                        elif isinstance(obj, np.floating):
                            return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)
                        return obj
                    
                    await ws.send_json(fix_numpy(frame))

                    # advance
                    self.index += self.direction * self.speed * FRAMES_PER_TICK
                    # clamp
                    if self.index >= len(self.frames):
                        self.index = len(self.frames) - 1
                        self.playing = False
                        await ws.send_json({"type": "finished"})
                    elif self.index < 0:
                        self.index = 0
                        self.playing = False
                        await ws.send_json({"type": "finished"})

                elapsed = _time.perf_counter() - tick_start
                await asyncio.sleep(max(0, SEND_INTERVAL - elapsed))
        except (WebSocketDisconnect, RuntimeError):
            pass
