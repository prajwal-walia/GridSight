"""
Live State Manager for F1 live timing.

Accumulates incremental SignalR updates and maintains a complete session state.
Output is normalized to the GridSight frame schema (camelCase driver fields,
flat sector fields, weather.flag merged).

Ported from F1ReplayTiming — all SignalR message processing kept identical,
only ``get_frame()`` output shape changed.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Track status code → normalised status string
_TRACK_STATUS_MAP: dict[str, str] = {
    "1": "GREEN",
    "2": "YELLOW",
    "4": "SAFETY_CAR",
    "5": "RED",
    "6": "VSC",
    "7": "VSC_ENDING",
}


def _parse_gap_seconds(gap: str | None) -> float | None:
    """Parse a gap string like '+1.234' into seconds.  Returns None for
    non-numeric gaps (leader, lapped, etc.)."""
    if not gap:
        return None
    if gap.startswith("LAP "):
        return None
    m = re.match(r"^\+?([\d.]+)$", gap)
    if m:
        return float(m.group(1))
    m = re.match(r"^(\d+)\s*L(?:ap)?", gap)
    if m:
        return None
    return None


def _parse_remaining(remaining: str) -> float:
    """Parse a time string like '00:15:32.000' into total seconds."""
    try:
        parts = remaining.split(":")
        if len(parts) == 3:
            h, m, rest = parts
            s = float(rest)
            return int(h) * 3600 + int(m) * 60 + s
        if len(parts) == 2:
            m, rest = parts
            s = float(rest)
            return int(m) * 60 + s
        return float(remaining)
    except (ValueError, IndexError):
        return 0.0


def _sanitize_value(val: Any) -> Any:
    """Replace NaN / Infinity floats with None."""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


class _DriverState:
    """Mutable per-driver state."""

    __slots__ = (
        "racing_number",
        "abbr",
        "team",
        "color",
        "position",
        "gap",
        "interval",
        "compound",
        "tyre_life",
        "tyre_history",
        "pit_stops",
        "in_pit",
        "has_fastest_lap",
        "flag",
        "retired",
        "no_timing",
        "grid_position",
        "sectors",
        "pit_prediction",
        "pit_prediction_margin",
        "pit_prediction_free_air",
        "best_lap_time",
        "pit_start",
        "x",
        "y",
        "relative_distance",
        "on_track",
        "_sector_best_personal",
        "_sector_best_overall",
        "_stint_count",
        "_last_stint_idx",
        "_s3_complete_time",
        "_sector_times",
    )

    def __init__(self, racing_number: str) -> None:
        self.racing_number: str = racing_number
        self.abbr: str = ""
        self.team: str = ""
        self.color: str = "#FFFFFF"
        self.position: int | None = None
        self.gap: str | None = None
        self.interval: str | None = None
        self.compound: str | None = None
        self.tyre_life: int | None = None
        self.tyre_history: list[str] = []
        self._last_stint_idx: int = -1
        self.pit_stops: int = 0
        self.in_pit: bool = False
        self.has_fastest_lap: bool = False
        self.flag: str | None = None  # "investigation" | "penalty" | None
        self.retired: bool = False
        self.no_timing: bool = False
        self.grid_position: int | None = None
        self.sectors: list[dict[str, Any]] | None = None
        self.pit_prediction: int | None = None
        self.pit_prediction_margin: float | None = None
        self.pit_prediction_free_air: float | None = None
        self.best_lap_time: str | None = None
        self.pit_start: bool = False
        self.x: float = 0.0
        self.y: float = 0.0
        self.relative_distance: float = 0.0
        self.on_track: bool = False
        # Internal tracking for sector colours
        self._sector_best_personal: dict[int, float] = {}
        self._sector_best_overall: dict[int, bool] = {}
        self._s3_complete_time: float | None = None
        self._sector_times: dict[int, float] = {}
        self._stint_count: int = 0

    def to_gridsight_dict(self) -> dict[str, Any]:
        """Normalize to GridSight driver schema (camelCase)."""
        # Flatten sectors
        s1 = s2 = s3 = None
        s1c = s2c = s3c = None
        if self.sectors:
            for s in self.sectors:
                num = s["num"]
                color = s.get("color")
                if num == 1:
                    s1 = True
                    s1c = color
                elif num == 2:
                    s2 = True
                    s2c = color
                elif num == 3:
                    s3 = True
                    s3c = color

        return {
            "code": self.abbr,
            "position": self.position,
            "x": self.x,
            "y": self.y,
            "speed": None,       # Not available in live SignalR
            "gear": None,
            "drs": None,
            "throttle": None,
            "brake": False,
            "tyre": self.compound,
            "tyreAge": self.tyre_life,
            "tyreHistory": list(self.tyre_history[-2:]) if self.tyre_history else [],
            "isOut": self.retired or self.no_timing,
            "teamColor": self.color,
            "team": self.team,
            "gapToLeader": self.gap,
            "interval": self.interval,
            "sector1": s1,
            "sector2": s2,
            "sector3": s3,
            "sector1Color": s1c,
            "sector2Color": s2c,
            "sector3Color": s3c,
            "fastestLap": self.has_fastest_lap,
            "pitCount": self.pit_stops,
            "gridPosition": self.grid_position,
            "underInvestigation": self.flag,
            "pitPrediction": self.pit_prediction,
        }


class LiveStateManager:
    """Accumulates incremental SignalR messages and produces complete
    GridSight-schema frame snapshots on demand.

    Parameters
    ----------
    session_type:
        One of "R", "Q", "S", "SQ", "FP1", "FP2", "FP3", etc.
    pit_loss_green:
        Estimated pit stop time loss under green flag conditions (seconds).
    pit_loss_sc:
        Estimated pit stop time loss under safety car (seconds).
    pit_loss_vsc:
        Estimated pit stop time loss under virtual safety car (seconds).
    """

    def __init__(
        self,
        session_type: str,
        pit_loss_green: float = 0.0,
        pit_loss_sc: float = 0.0,
        pit_loss_vsc: float = 0.0,
        track_norm: dict[str, float] | None = None,
        track_points: list[dict[str, float]] | None = None,
    ) -> None:
        self._session_type: str = session_type
        self._pit_loss_green: float = pit_loss_green
        self._pit_loss_sc: float = pit_loss_sc
        self._pit_loss_vsc: float = pit_loss_vsc

        # Track normalization: raw F1 coords -> 0-1 normalized
        self._track_norm: dict[str, float] | None = track_norm

        # Track outline as numpy arrays for nearest-point lookup
        self._track_xy: np.ndarray | None = None
        if track_points:
            self._track_xy = np.array(
                [[p["x"], p["y"]] for p in track_points], dtype=np.float64
            )

        # Auto-normalization from raw position data (fallback when no track_norm)
        self._raw_x_min: float = float("inf")
        self._raw_x_max: float = float("-inf")
        self._raw_y_min: float = float("inf")
        self._raw_y_max: float = float("-inf")
        self._position_samples: int = 0

        # Per-driver state keyed by racing number string
        self._drivers: dict[str, _DriverState] = {}

        # Session-level state
        self._status: str = "GREEN"
        self._weather: dict[str, Any] | None = None
        self._current_lap: int = 0
        self._total_laps: int = 0
        self._session_status: str = "Inactive"
        self._session_was_started: bool = False
        self._quali_phase: int = 0
        self._clock_remaining: float = 0.0
        self._clock_extrapolating: bool = False
        self._clock_utc: str = ""
        self._clock_update_time: float = 0.0
        self._last_timestamp: float = 0.0
        self._seen_topics: set[str] = set()

        # Race control messages (most recent first, capped at 50)
        self._rc_messages: list[dict[str, Any]] = []

        # Overall sector bests (sector index 0-2 -> best time)
        self._overall_sector_bests: dict[int, float] = {}

    # ------------------------------------------------------------------
    # Driver helpers
    # ------------------------------------------------------------------

    def _get_driver(self, number: str) -> _DriverState:
        """Get or create a driver state entry."""
        if number not in self._drivers:
            self._drivers[number] = _DriverState(number)
        return self._drivers[number]

    @property
    def _is_race(self) -> bool:
        return self._session_type in ("R", "S")

    @property
    def _is_quali(self) -> bool:
        return self._session_type in ("Q", "SQ")

    @property
    def session_status(self) -> str:
        """Current session status (Inactive, Started, Finished, Finalised, Ends)."""
        return self._session_status

    @property
    def session_was_started(self) -> bool:
        return self._session_was_started

    # ------------------------------------------------------------------
    # Message processing
    # ------------------------------------------------------------------

    def process_message(self, topic: str, data: dict, timestamp: float) -> None:
        """Process a single SignalR message."""
        self._last_timestamp = timestamp

        if topic not in self._seen_topics:
            self._seen_topics.add(topic)
            logger.info("First message for topic: %s", topic)

        handler = self._HANDLERS.get(topic)
        if handler is not None:
            try:
                handler(self, data, timestamp)
            except Exception:
                logger.exception("Error processing %s message", topic)

    # --- DriverList ---------------------------------------------------

    def _handle_driver_list(self, data: dict, _ts: float) -> None:
        for number, info in data.items():
            if not isinstance(info, dict):
                continue
            drv = self._get_driver(str(number))
            if "Tla" in info:
                drv.abbr = info["Tla"]
            if "TeamName" in info:
                drv.team = info["TeamName"]
            if "TeamColour" in info:
                colour = info["TeamColour"]
                if not colour.startswith("#"):
                    colour = "#" + colour
                drv.color = colour

    # --- TimingData ---------------------------------------------------

    def _handle_timing_data(self, data: dict, _ts: float) -> None:
        lines = data.get("Lines")
        if not lines:
            return
        for number, updates in lines.items():
            if not isinstance(updates, dict):
                continue
            drv = self._get_driver(str(number))

            if "Position" in updates:
                try:
                    drv.position = int(updates["Position"])
                except (ValueError, TypeError):
                    pass

            if "GapToLeader" in updates:
                val = updates["GapToLeader"]
                if isinstance(val, dict):
                    val = val.get("Value", "")
                drv.gap = val if val else drv.gap

            if "IntervalToPositionAhead" in updates:
                ival = updates["IntervalToPositionAhead"]
                if isinstance(ival, dict):
                    ival = ival.get("Value", "")
                drv.interval = ival if ival else drv.interval

            if "BestLapTime" in updates:
                blt = updates["BestLapTime"]
                if isinstance(blt, dict):
                    blt_val = blt.get("Value", "")
                else:
                    blt_val = str(blt) if blt else ""
                if blt_val:
                    drv.best_lap_time = blt_val

            if "InPit" in updates:
                drv.in_pit = bool(updates["InPit"])

            if "Retired" in updates:
                if updates["Retired"]:
                    drv.retired = True

            if "KnockedOut" in updates:
                if updates["KnockedOut"]:
                    drv.retired = True

            if "Sectors" in updates:
                sectors_raw = updates["Sectors"]
                if isinstance(sectors_raw, list):
                    sectors_raw = {str(i): v for i, v in enumerate(sectors_raw) if isinstance(v, dict)}
                if isinstance(sectors_raw, dict):
                    self._process_sectors(drv, sectors_raw)

            if "Status" in updates:
                status_val = updates["Status"]
                if not status_val or (isinstance(status_val, dict) and not status_val):
                    drv.no_timing = True
            if drv.position is None and not drv.gap:
                drv.no_timing = True
            else:
                drv.no_timing = False

    def _process_sectors(self, drv: _DriverState, sectors: dict) -> None:
        """Update sector colour indicators for a driver."""
        existing: dict[int, dict[str, Any]] = {}
        if drv.sectors:
            for s in drv.sectors:
                existing[s["num"]] = s

        for idx_str, sector_data in sorted(sectors.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            if not isinstance(sector_data, dict):
                continue
            try:
                sector_idx = int(idx_str)
            except ValueError:
                continue
            sector_num = sector_idx + 1

            val_str = sector_data.get("Value", "")
            if not val_str:
                continue

            try:
                sec_time = float(val_str)
            except ValueError:
                continue

            drv._sector_times[sector_idx] = sec_time

            current_pb = drv._sector_best_personal.get(sector_idx)
            is_personal_best = current_pb is None or sec_time <= current_pb + 0.0005
            if current_pb is None or sec_time < current_pb:
                drv._sector_best_personal[sector_idx] = sec_time

            current_ob = self._overall_sector_bests.get(sector_idx)
            is_overall_best = current_ob is None or sec_time <= current_ob + 0.0005
            if current_ob is None or sec_time < current_ob:
                self._overall_sector_bests[sector_idx] = sec_time
                self._recompute_sector_colours(sector_idx, drv.racing_number)

            if is_overall_best:
                color = "purple"
            elif is_personal_best:
                color = "green"
            else:
                color = "yellow"

            existing[sector_num] = {"num": sector_num, "color": color}

            for later in list(existing):
                if later > sector_num:
                    del existing[later]
                    drv._sector_times.pop(later - 1, None)

            if sector_num == 3:
                drv._s3_complete_time = time.monotonic()
            elif sector_num == 1:
                drv._s3_complete_time = None

        drv.sectors = [existing[k] for k in sorted(existing)] if existing else None

    def _recompute_sector_colours(self, sector_idx: int, exclude_rn: str) -> None:
        """When a new overall best is set, downgrade other drivers' purples."""
        sector_num = sector_idx + 1
        new_best = self._overall_sector_bests.get(sector_idx)
        if new_best is None:
            return

        for drv in self._drivers.values():
            if drv.racing_number == exclude_rn:
                continue
            if not drv.sectors:
                continue
            for s in drv.sectors:
                if s["num"] == sector_num and s["color"] == "purple":
                    drv_time = drv._sector_times.get(sector_idx)
                    drv_pb = drv._sector_best_personal.get(sector_idx)
                    if drv_time is not None and drv_pb is not None and drv_time <= drv_pb + 0.0005:
                        s["color"] = "green"
                    else:
                        s["color"] = "yellow"

    # --- Position -----------------------------------------------------

    def _handle_position(self, data: dict, _ts: float) -> None:
        """Handle Position data (decoded from Position.z)."""
        position_list = data.get("Position")
        if not position_list or not isinstance(position_list, list):
            return

        raw_positions: list[tuple[str, float, float, str]] = []
        for sample in position_list:
            entries = sample.get("Entries")
            if not entries or not isinstance(entries, dict):
                continue
            for number, pos_data in entries.items():
                if not isinstance(pos_data, dict):
                    continue
                raw_x = pos_data.get("X")
                raw_y = pos_data.get("Y")
                if raw_x is None or raw_y is None:
                    continue
                status = pos_data.get("Status", "")
                raw_positions.append((str(number), float(raw_x), float(raw_y), status))

        if not raw_positions:
            return

        if self._track_norm is None:
            for _, rx, ry, _ in raw_positions:
                self._raw_x_min = min(self._raw_x_min, rx)
                self._raw_x_max = max(self._raw_x_max, rx)
                self._raw_y_min = min(self._raw_y_min, ry)
                self._raw_y_max = max(self._raw_y_max, ry)
                self._position_samples += 1

            x_range = self._raw_x_max - self._raw_x_min
            y_range = self._raw_y_max - self._raw_y_min
            scale = max(x_range, y_range)

            if scale < 1.0 or self._position_samples < 5:
                return

            padding = scale * 0.05
            x_min = self._raw_x_min - padding
            y_min = self._raw_y_min - padding
            scale = scale + 2 * padding
        else:
            x_min = self._track_norm["x_min"]
            y_min = self._track_norm["y_min"]
            scale = self._track_norm["scale"]

        for number, raw_x, raw_y, status in raw_positions:
            drv = self._get_driver(number)
            drv.on_track = status == "OnTrack"

            norm_x = (raw_x - x_min) / scale
            norm_y = (raw_y - y_min) / scale

            if self._track_xy is not None:
                rel_dist, snap_x, snap_y = self._snap_to_track(norm_x, norm_y)
                drv.x = snap_x
                drv.y = snap_y
                drv.relative_distance = rel_dist
            else:
                drv.x = norm_x
                drv.y = norm_y

    def _snap_to_track(self, x: float, y: float) -> tuple[float, float, float]:
        """Snap a position to the nearest point on the track outline."""
        track = self._track_xy
        if track is None or len(track) == 0:
            return 0.0, x, y
        dx = track[:, 0] - x
        dy = track[:, 1] - y
        dist_sq = dx * dx + dy * dy
        nearest_idx = int(np.argmin(dist_sq))
        return (
            nearest_idx / len(track),
            float(track[nearest_idx, 0]),
            float(track[nearest_idx, 1]),
        )

    # --- TimingAppData ------------------------------------------------

    def _handle_timing_app_data(self, data: dict, _ts: float) -> None:
        lines = data.get("Lines")
        if not lines:
            return
        for number, updates in lines.items():
            if not isinstance(updates, dict):
                continue
            drv = self._get_driver(str(number))

            if "GridPos" in updates:
                try:
                    drv.grid_position = int(updates["GridPos"])
                except (ValueError, TypeError):
                    pass

            if "Stints" in updates:
                stints_raw = updates["Stints"]
                if isinstance(stints_raw, list):
                    stints_raw = {str(i): v for i, v in enumerate(stints_raw) if isinstance(v, dict)}
                if isinstance(stints_raw, dict):
                    self._process_stints(drv, stints_raw)

    def _process_stints(self, drv: _DriverState, stints: dict) -> None:
        """Process stint data — update compound, tyre_life, pit_stops, tyre_history."""
        max_idx = -1
        latest_stint: dict | None = None
        for idx_str, stint_data in stints.items():
            if not isinstance(stint_data, dict):
                continue
            try:
                idx = int(idx_str)
            except ValueError:
                continue
            if idx > max_idx:
                max_idx = idx
                latest_stint = stint_data

        if latest_stint is None:
            return

        if "Compound" in latest_stint:
            new_compound = latest_stint["Compound"].upper()
            if new_compound == "UNKNOWN":
                pass
            else:
                if max_idx > drv._last_stint_idx and drv._last_stint_idx >= 0 and drv.compound:
                    if not drv.tyre_history or drv.tyre_history[-1] != drv.compound:
                        drv.tyre_history.append(drv.compound)
                drv.compound = new_compound
                drv._last_stint_idx = max_idx

        if "TotalLaps" in latest_stint:
            try:
                drv.tyre_life = int(latest_stint["TotalLaps"])
            except (ValueError, TypeError):
                pass

        new_stint_count = max_idx + 1
        if new_stint_count > drv._stint_count:
            drv._stint_count = new_stint_count
            drv.pit_stops = max(0, new_stint_count - 1)

    # --- TimingStats --------------------------------------------------

    def _handle_timing_stats(self, data: dict, _ts: float) -> None:
        lines = data.get("Lines")
        if not lines:
            return

        new_fastest_number: str | None = None
        for number, stats in lines.items():
            if not isinstance(stats, dict):
                continue
            pb = stats.get("PersonalBestLapTime")
            if isinstance(pb, dict):
                pos = pb.get("Position")
                if pos == 1 or pos == "1":
                    new_fastest_number = str(number)

        if new_fastest_number is not None:
            for num, drv in self._drivers.items():
                drv.has_fastest_lap = (num == new_fastest_number)

    # --- RaceControlMessages ------------------------------------------

    def _handle_race_control(self, data: dict, ts: float) -> None:
        messages = data.get("Messages")
        if not messages:
            return
        if isinstance(messages, list):
            items = enumerate(messages)
        elif isinstance(messages, dict):
            items = messages.items()
        else:
            return
        for _, msg_data in items:
            if not isinstance(msg_data, dict):
                continue
            message = msg_data.get("Message", "")
            category = msg_data.get("Category", "")
            racing_number = msg_data.get("RacingNumber")
            lap = msg_data.get("Lap")
            upper_msg = message.upper()

            if message:
                rc_entry: dict[str, Any] = {
                    "message": message,
                    "category": category,
                    "timestamp": ts,
                    "lap": lap,
                }
                if racing_number:
                    rc_entry["racing_number"] = str(racing_number)
                self._rc_messages.append(rc_entry)
                if len(self._rc_messages) > 50:
                    self._rc_messages = self._rc_messages[-50:]

            if not racing_number:
                car_match = re.search(r"CAR\s+(\d+)", message)
                if car_match:
                    racing_number = car_match.group(1)

            if not racing_number:
                continue

            drv = self._get_driver(str(racing_number))

            if "NO FURTHER ACTION" in upper_msg or "NO INVESTIGATION" in upper_msg:
                drv.flag = None
            elif "PENALTY SERVED" in upper_msg:
                drv.flag = None
            elif "DECISION" in upper_msg and "PENALTY" not in upper_msg:
                drv.flag = None
            elif "UNDER INVESTIGATION" in upper_msg or "IS NOTED" in upper_msg:
                drv.flag = "investigation"
            elif ("TIME PENALTY" in upper_msg or "PENALTY" in upper_msg) and "NO FURTHER" not in upper_msg:
                drv.flag = "penalty"

    # --- TrackStatus --------------------------------------------------

    def _handle_track_status(self, data: dict, _ts: float) -> None:
        status_code = data.get("Status", "")
        mapped = _TRACK_STATUS_MAP.get(str(status_code))
        if mapped:
            self._status = mapped

    # --- WeatherData --------------------------------------------------

    def _handle_weather(self, data: dict, _ts: float) -> None:
        try:
            self._weather = {
                "air_temp": float(data["AirTemp"]) if "AirTemp" in data else (self._weather or {}).get("air_temp"),
                "track_temp": float(data["TrackTemp"]) if "TrackTemp" in data else (self._weather or {}).get("track_temp"),
                "humidity": float(data["Humidity"]) if "Humidity" in data else (self._weather or {}).get("humidity"),
                "rainfall": str(data.get("Rainfall", "0")) != "0" if "Rainfall" in data else (self._weather or {}).get("rainfall", False),
                "wind_speed": float(data["WindSpeed"]) if "WindSpeed" in data else (self._weather or {}).get("wind_speed"),
                "wind_direction": float(data["WindDirection"]) if "WindDirection" in data else (self._weather or {}).get("wind_direction"),
            }
        except (ValueError, TypeError):
            logger.warning("Failed to parse weather data: %s", data)

    # --- LapCount -----------------------------------------------------

    def _handle_lap_count(self, data: dict, _ts: float) -> None:
        if "CurrentLap" in data:
            try:
                self._current_lap = int(data["CurrentLap"])
            except (ValueError, TypeError):
                pass
        if "TotalLaps" in data:
            try:
                self._total_laps = int(data["TotalLaps"])
            except (ValueError, TypeError):
                pass

    # --- ExtrapolatedClock --------------------------------------------

    def _handle_extrapolated_clock(self, data: dict, ts: float) -> None:
        if "Remaining" in data:
            self._clock_remaining = _parse_remaining(data["Remaining"])
            self._clock_update_time = time.monotonic()
        if "Extrapolating" in data:
            self._clock_extrapolating = bool(data["Extrapolating"])
        if "Utc" in data:
            self._clock_utc = data["Utc"]

    # --- SessionStatus ------------------------------------------------

    def _handle_session_status(self, data: dict, _ts: float) -> None:
        if "Status" in data:
            new_status = data["Status"]
            if new_status == "Started":
                self._session_was_started = True
            self._session_status = new_status

    # --- SessionData --------------------------------------------------

    def _handle_session_data(self, data: dict, _ts: float) -> None:
        series = data.get("Series")
        if not series:
            return
        if isinstance(series, list):
            entries = [e for e in series if isinstance(e, dict)]
        elif isinstance(series, dict):
            entries = [e for e in series.values() if isinstance(e, dict)]
        else:
            return
        for entry in reversed(entries):
            if "QualifyingPart" in entry:
                try:
                    self._quali_phase = int(entry["QualifyingPart"])
                except (ValueError, TypeError):
                    pass
                break

    # ------------------------------------------------------------------
    # Handler dispatch table
    # ------------------------------------------------------------------

    _HANDLERS: dict[str, Any] = {
        "DriverList": _handle_driver_list,
        "TimingData": _handle_timing_data,
        "TimingAppData": _handle_timing_app_data,
        "TimingStats": _handle_timing_stats,
        "RaceControlMessages": _handle_race_control,
        "TrackStatus": _handle_track_status,
        "WeatherData": _handle_weather,
        "LapCount": _handle_lap_count,
        "ExtrapolatedClock": _handle_extrapolated_clock,
        "SessionStatus": _handle_session_status,
        "SessionData": _handle_session_data,
        "Position": _handle_position,
    }

    # ------------------------------------------------------------------
    # Frame construction — outputs GridSight schema
    # ------------------------------------------------------------------

    def get_frame(self) -> dict:
        """Build and return a GridSight-schema frame dict.

        Called at ~2 Hz by the broadcaster.

        Returns
        -------
        dict with keys: timestamp, lap, drivers, weather
        """
        SECTOR_LINGER = 5.0
        now = time.monotonic()

        drivers_list: list[dict[str, Any]] = []
        for drv in self._drivers.values():
            if not drv.abbr:
                continue
            # Clear sectors 5 seconds after S3 completes
            if drv._s3_complete_time and (now - drv._s3_complete_time) > SECTOR_LINGER:
                drv.sectors = None
                drv._s3_complete_time = None
                drv._sector_times.clear()
            d = drv.to_gridsight_dict()
            # Sanitize all values
            for key in list(d.keys()):
                d[key] = _sanitize_value(d[key])
            drivers_list.append(d)

        # Sort by position (None positions go to the end)
        drivers_list.sort(key=lambda d: d["position"] if d["position"] is not None else 9999)

        # Set leader gap for races
        if self._is_race and drivers_list:
            for d in drivers_list:
                if d["position"] == 1:
                    d["gapToLeader"] = f"LAP {self._current_lap}" if self._current_lap > 0 else d["gapToLeader"]
                    break

        # For non-race sessions: compute gap from best_lap_time values
        if not self._is_race and drivers_list:
            self._compute_practice_gaps(drivers_list)

        # Weather with flag merged in
        weather_out: dict[str, Any] = {
            "air_temp": None,
            "track_temp": None,
            "humidity": None,
            "wind_speed": None,
            "rainfall": False,
            "flag": self._status,
        }
        if self._weather:
            weather_out["air_temp"] = self._weather.get("air_temp")
            weather_out["track_temp"] = self._weather.get("track_temp")
            weather_out["humidity"] = self._weather.get("humidity")
            weather_out["wind_speed"] = self._weather.get("wind_speed")
            weather_out["rainfall"] = self._weather.get("rainfall", False)

        frame: dict[str, Any] = {
            "type": "frame",
            "timestamp": _sanitize_value(self._last_timestamp),
            "lap": _sanitize_value(self._current_lap),
            "drivers": drivers_list,
            "weather": weather_out,
        }

        # Add pit predictions for race sessions
        if self._is_race and self._pit_loss_green > 0:
            self._add_pit_predictions(frame)

        return frame

    # ------------------------------------------------------------------
    # Practice / qualifying gap computation
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_best_lap_seconds(time_str: str | None) -> float | None:
        """Parse a best lap time like '1:23.456' or '83.456' into seconds."""
        if not time_str:
            return None
        try:
            if ":" in time_str:
                parts = time_str.split(":")
                return int(parts[0]) * 60 + float(parts[1])
            return float(time_str)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _format_lap_time(seconds: float) -> str:
        """Format seconds as M:SS.sss lap time string."""
        mins = int(seconds // 60)
        secs = seconds - mins * 60
        return f"{mins}:{secs:06.3f}"

    def _compute_practice_gaps(self, drivers_list: list[dict[str, Any]]) -> None:
        """Compute best_lap_time display and gap-to-leader for non-race sessions."""
        timed: list[tuple[int, float]] = []
        for i, d in enumerate(drivers_list):
            # Look up best_lap_time from the driver state (not in the output dict)
            drv = None
            for ds in self._drivers.values():
                if ds.abbr == d.get("code"):
                    drv = ds
                    break
            if drv and drv.best_lap_time:
                secs = self._parse_best_lap_seconds(drv.best_lap_time)
                if secs is not None:
                    timed.append((i, secs))

        if not timed:
            return

        timed.sort(key=lambda x: x[1])
        leader_time = timed[0][1]

        for rank, (idx, secs) in enumerate(timed):
            d = drivers_list[idx]
            d["position"] = rank + 1
            if rank == 0:
                d["gapToLeader"] = self._format_lap_time(secs)
            else:
                d["gapToLeader"] = f"+{secs - leader_time:.3f}"

        drivers_list.sort(key=lambda d: d["position"] if d["position"] is not None else 9999)

    # ------------------------------------------------------------------
    # Pit prediction
    # ------------------------------------------------------------------

    def _add_pit_predictions(self, frame: dict) -> None:
        """Add pitPrediction to each driver in the frame."""
        drivers = frame.get("drivers", [])
        status = frame.get("weather", {}).get("flag", "GREEN")
        lap = frame.get("lap", 0)

        if lap < 5:
            return

        if "SC" in status.upper():
            pit_loss = self._pit_loss_sc
        elif "VSC" in status.upper():
            pit_loss = self._pit_loss_vsc
        else:
            pit_loss = self._pit_loss_green

        driver_gaps: list[tuple[str, float]] = []
        for d in drivers:
            if d.get("isOut"):
                continue
            if d.get("position") == 1:
                driver_gaps.append((d["code"], 0.0))
            else:
                gap_sec = _parse_gap_seconds(d.get("gapToLeader"))
                if gap_sec is not None:
                    driver_gaps.append((d["code"], gap_sec))

        if not driver_gaps:
            return

        driver_gaps.sort(key=lambda x: x[1])

        for d in drivers:
            if d.get("isOut"):
                d["pitPrediction"] = None
                continue

            current_gap: float | None = None
            if d.get("position") == 1:
                current_gap = 0.0
            else:
                current_gap = _parse_gap_seconds(d.get("gapToLeader"))

            if current_gap is None:
                d["pitPrediction"] = None
                continue

            projected_gap = current_gap + pit_loss
            other_gaps = [g for abbr, g in driver_gaps if abbr != d["code"]]

            predicted_pos = 1
            for g in other_gaps:
                if projected_gap > g:
                    predicted_pos += 1
                else:
                    break

            predicted_pos = min(predicted_pos, len(other_gaps) + 1)

            if predicted_pos > (d.get("position") or 0):
                d["pitPrediction"] = predicted_pos
            else:
                d["pitPrediction"] = None
