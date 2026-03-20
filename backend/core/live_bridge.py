"""
Live telemetry bridge – listens for Codemasters / EA Sports F1 25 UDP
packets on port 20777, parses the player-car data, and broadcasts the
normalised GridSight frame schema to all connected WebSocket clients.

Key design decision: the broadcast payload uses the **same schema** as
``/ws/replay`` frames so that every existing frontend component (track
map, leaderboard, telemetry strip) works without changes.

Packet structures follow the F1 24 / F1 25 specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Codemasters packet constants ─────────────────────────────────────────

PACKET_MOTION    = 0
PACKET_SESSION   = 1
PACKET_LAP_DATA  = 2
PACKET_PARTICIPANTS = 4
PACKET_TELEMETRY = 6
PACKET_CAR_STATUS = 7

# Header (shared across all packet types)
#   uint16 packetFormat, uint8 gameYear, uint8 gameMajorVer, uint8 gameMinorVer,
#   uint8 packetVer, uint8 packetId, uint64 sessionUID, float sessionTime,
#   uint32 frameId, uint32 overallFrameId, uint8 playerCarIndex,
#   uint8 secondaryPlayerCarIndex
HEADER_FMT  = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FMT)          # 29

# Per-car struct sizes (F1 24 / F1 25)
MOTION_CAR_SIZE    = 60   # CarMotionData
TELEMETRY_CAR_SIZE = 60   # CarTelemetryData
LAP_DATA_CAR_SIZE  = 57   # LapData
CAR_STATUS_SIZE    = 55   # CarStatusData (verified via ctypes sizeof)

# Field offsets within each per-car struct
# ── CarMotionData ──
_MOT_X = 0    # float  worldPositionX
_MOT_Z = 8    # float  worldPositionZ  (Z in-game ≈ Y on 2-D map)

# ── CarTelemetryData ──
_TEL_SPEED    = 0   # uint16
_TEL_THROTTLE = 2   # float  (0.0 – 1.0)
_TEL_BRAKE    = 10  # float  (0.0 – 1.0)
_TEL_GEAR     = 15  # int8   (-1 R, 0 N, 1-8)
_TEL_RPM      = 16  # uint16
_TEL_DRS      = 18  # uint8  (0 off, 1 on)

# ── LapData ──
_LAP_LAST_TIME = 0   # uint32 lastLapTimeInMS
_LAP_CUR_TIME  = 4   # uint32 currentLapTimeInMS
_LAP_S1_TIME   = 8   # uint16 sector1TimeInMS
_LAP_S2_TIME   = 11  # uint16 sector2TimeInMS
_LAP_DISTANCE  = 20  # float  lapDistance
_LAP_TOTAL_DIST = 24  # float  totalDistance
_LAP_CAR_POS   = 32  # uint8  carPosition (1-22)
_LAP_CUR_LAP   = 33  # uint8  currentLapNum
_LAP_PIT_STATUS = 34  # uint8  pitStatus (0=none, 1=pitting, 2=pit lane)

# ── Session packet ──
# After the header, the first few fields are:
#   uint8 weather, int8 trackTemperature, int8 airTemperature,
#   uint8 totalLaps, uint16 trackLength, uint8 sessionType, int8 trackId, ...
_SES_WEATHER       = 0   # uint8
_SES_TRACK_TEMP    = 1   # int8
_SES_AIR_TEMP      = 2   # int8
_SES_TOTAL_LAPS    = 3   # uint8
_SES_TRACK_LENGTH  = 4   # uint16 (meters)
_SES_SESSION_TYPE  = 6   # uint8
_SES_TRACK_ID      = 7   # uint8 (index into track names table)

# Track name lookup (F1 24/25 trackId → short name)
TRACK_ID_MAP = { #(track name, highNumber=Small on canvas, x_offset, y_offset)
    0: ("melbourne", 3.5, 300, 300),
    1: ("paul_ricard", 2.5, 500, 300),
    2: ("shanghai", 2, 300, 300),
    3: ("sakhir", 2, 600, 350),
    4: ("catalunya", 2.5, 400, 300),
    5: ("monaco", 2, 300, 300),
    6: ("montreal", 3, 300, 100),
    7: ("silverstone", 3.5, 400, 250),
    8: ("hockenheim", 2, 300, 300),
    9: ("hungaroring", 2.5, 400, 300),
    10: ("spa", 3.5, 500, 350),
    11: ("monza", 4, 400, 300),
    12: ("singapore", 2, 400, 300),
    13: ("suzuka", 2.5, 500, 300),
    14: ("abu_dhabi", 2, 500, 250),
    15: ("texas", 2, 400, 50),
    16: ("brazil", 2, 600, 250),
    17: ("austria", 2, 300, 300),
    18: ("sochi", 2, 300, 300),
    19: ("mexico", 2.5, 500, 500),
    20: ("baku", 3, 400,400),
    21: ("sakhir_short", 2, 300, 300),
    22: ("silverstone_short", 2, 300, 300),
    23: ("texas_short", 2, 300, 300),
    24: ("suzuka_short", 2, 300, 300),
    25: ("hanoi", 2, 300, 300),
    26: ("zandvoort", 2, 500, 300),
    27: ("imola", 2, 500, 300),
    28: ("portimao", 2, 300, 300),
    29: ("jeddah", 4,500, 350),
    30:("Miami", 2,400,300),
    31:("Las Vegas", 4,400, 300),
    32:("Losail", 2.5,400,300),
    39: ("silverstone", 3.5, 400, 250),
    40: ("austria", 2, 300, 300),
    41: ("zandvoort", 2, 500, 300),
}

TEAM_ID_MAP = {
    0:   ('Mercedes', '#27F4D2'),
    1:   ('Ferrari', '#E8002D'),
    2:   ('Red Bull Racing', '#3671C6'),
    3:   ('Williams', '#64C4FF'),
    4:   ('Aston Martin', '#358C75'),
    5:   ('Alpine', '#FF87BC'),
    6:   ('Racing Bulls', '#6692FF'),
    7:   ('Haas F1 Team', '#B6BABD'),
    8:   ('McLaren', '#FF8000'),
    9:   ('Kick Sauber', '#52E252'),
    41:  ('F1 Generic', '#FFFFFF'),
    104: ('Custom Team', '#888888'),
    129: ('Konnersport', '#FF6B35'),
    154: ('APXGP', '#FF1801'),
    255: ('Unknown', '#888888'),
}

TYRE_MAP = {16: 'S', 17: 'M', 18: 'H', 7: 'I', 8: 'W', 19: 'S', 20: 'M', 21: 'H'}

SESSION_TYPE_MAP = {
    0: 'Unknown', 1: 'Practice 1', 2: 'Practice 2', 3: 'Practice 3',
    4: 'Short Practice', 5: 'Qualifying 1', 6: 'Qualifying 2',
    7: 'Qualifying 3', 8: 'Short Qualifying', 9: 'One Shot Qualifying',
    10: 'Race', 11: 'Race 2', 12: 'Race 3', 13: 'Time Trial',
}

# ── bridge settings ──────────────────────────────────────────────────────

UDP_PORT       = 20777
BROADCAST_HZ   = 10          # pushes per second to WS clients
SILENCE_TIMEOUT = 5.0        # seconds of UDP silence → "game disconnected"

SIM_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sim_sessions"
RACING_LINE_DIR  = Path(__file__).resolve().parent.parent / "tracks"


# ── asyncio UDP protocol ─────────────────────────────────────────────────

class _UDPProtocol(asyncio.DatagramProtocol):
    """Thin adapter that forwards datagrams to a callback."""

    def __init__(self, callback):
        self._cb = callback

    def datagram_received(self, data: bytes, addr):
        self._cb(data)

    def error_received(self, exc):          # noqa: D401
        pass                                # non-fatal on Windows


# ── LiveBridge (singleton) ───────────────────────────────────────────────

class LiveBridge:
    """
    Manages:
      • a UDP socket listening on 0.0.0.0:20777
      • a dict ``_state`` holding the latest parsed fields
      • a periodic broadcast loop that pushes the normalised frame to
        every registered WebSocket client at ``BROADCAST_HZ``
      • session recording to a .jsonl file in sim_sessions/
    """

    _instance: LiveBridge | None = None

    def __init__(self):
        self.clients: set = set()
        self._state: dict[str, Any] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task | None = None
        self._last_packet: float = 0.0
        self._game_connected: bool = False
        self.is_running: bool = False

        # ── timing ────────────────────────────────────────────────────
        self._start_time: float | None = None  # monotonic time of first packet
        self._last_broadcast: float = 0.0      # throttle broadcasts to BROADCAST_HZ

        # ── session info (from Session packet) ────────────────────────
        self._track_name: str = "unknown"
        self._air_temp: float = 25.0
        self._track_temp: float = 35.0
        self._weather_id: int = 0   # 0=clear, 1=light_cloud, etc.
        self._pending_track_change: str | None = None
        self._session_type_id: int = 0
        self._session_type_name: str = "Unknown"
        self._total_laps: int = 0
        self._track_length: float = 0.0
        self._num_active_cars: int = 20
        self._pending_session_info: bool = False

        # ── participants (keyed by carIndex) ──────────────────────────
        self._participants: dict[int, dict] = {}

        # ── new state dictionaries ────────────────────────────────────
        self._car_positions: dict[int, dict] = {}
        self._lap_data: dict[int, dict] = {}
        self._car_telemetry: dict[int, dict] = {}

        # ── coordinate mapping (Fredrik's approach) ────────────────────
        self._player_car_index: int = 0
        self._track_id: int = -1  # current trackId from session packet
        self._racing_line_coords: list[dict] | None = None  # loaded track outline
        self._pending_racing_line: bool = False  # broadcast outline to clients

        # ── per-car status (tyre, etc.) ───────────────────────────────
        self._car_status: dict[int, dict] = {}
        self._first_tyre_logged: bool = False

        # ── recording ─────────────────────────────────────────────────
        self._recording_enabled: bool = False  # opt-in, not auto
        self._recording_file: Any = None
        self._recording_filename: str | None = None
        self._frame_count: int = 0

    # ── singleton accessor ────────────────────────────────────────────

    @classmethod
    def get(cls) -> LiveBridge:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── lifecycle ─────────────────────────────────────────────────────

    async def start(self):
        loop = asyncio.get_event_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._on_packet),
            local_addr=("0.0.0.0", UDP_PORT),
        )
        self._task = asyncio.create_task(self._broadcast_loop())
        self.is_running = True
        # Recording is opt-in — don't auto-start
        print(f"[LiveBridge] UDP listener started on :{UDP_PORT}")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._transport:
            self._transport.close()
        self._stop_recording()
        # Reset timing so a new session can start fresh
        self._start_time = None
        self._last_broadcast = 0.0
        self._state = {}
        self._frame_count = 0
        self._pending_track_change = None
        self._pending_session_info = False
        self._session_type_id = 0
        self._session_type_name = "Unknown"
        self._total_laps = 0
        self._track_length = 0.0
        self._num_active_cars = 20
        self._participants = {}
        self._car_positions = {}
        self._lap_data = {}
        self._car_telemetry = {}
        self._track_id = -1
        self._racing_line_coords = None
        self._pending_racing_line = False
        self._car_status = {}
        print("[LiveBridge] stopped")

    # ── recording ─────────────────────────────────────────────────────

    def _start_recording(self):
        """Open a new JSONL recording file."""
        if not self._recording_enabled:
            return
        SIM_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        fname = f"{ts}_{self._track_name}.jsonl"
        self._recording_filename = fname
        path = SIM_SESSIONS_DIR / fname
        self._recording_file = open(path, "a", encoding="utf-8")
        self._frame_count = 0
        print(f"[LiveBridge] Recording to {path}")

    def _stop_recording(self):
        """Close the current recording file."""
        if self._recording_file:
            try:
                self._recording_file.close()
            except Exception:
                pass
            self._recording_file = None
            self._recording_enabled = False
            print(f"[LiveBridge] Recording stopped: {self._recording_filename}")

    # ── public recording API ──────────────────────────────────────────

    def start_recording(self) -> str | None:
        """Enable recording and open a new file. Returns filename."""
        if self._recording_file:
            return self._recording_filename  # already recording
        self._recording_enabled = True
        self._start_recording()
        return self._recording_filename

    def stop_recording(self) -> str | None:
        """Stop recording and return the filename."""
        fname = self._recording_filename
        self._stop_recording()
        return fname

    @property
    def is_recording(self) -> bool:
        return self._recording_file is not None

    def _record_frame(self, frame: dict):
        """Append a frame to the recording file."""
        if self._recording_file:
            try:
                self._recording_file.write(json.dumps(frame) + "\n")
                self._recording_file.flush()
                self._frame_count += 1
            except Exception:
                pass

    @property
    def recording_filename(self) -> str | None:
        return self._recording_filename

    # ── client management ────────────────────────────────────────────

    async def add_client(self, ws):
        self.clients.add(ws)
        # ── Send full state catch-up to newly connected clients ──────
        try:
            # 1. Track change (so frontend knows which circuit)
            if self._track_name and self._track_name != "unknown":
                await ws.send_json({
                    "type": "track_change",
                    "circuit": self._track_name,
                    "year": 2025,
                })

            # 2. Session info
            if self._session_type_name != "Unknown":
                await ws.send_json({
                    "type": "session_info",
                    "sessionType": self._session_type_name,
                    "sessionTypeId": self._session_type_id,
                    "trackName": self._track_name,
                    "totalLaps": self._total_laps,
                    "trackLength": self._track_length,
                    "numActiveCars": self._num_active_cars,
                })

            # 3. Racing line — load on-demand if not yet loaded
            if self._racing_line_coords is None and self._track_id >= 0:
                self._racing_line_coords = self._load_racing_line(self._track_name)

            if self._racing_line_coords:
                await ws.send_json({
                    "type": "live_track",
                    "coords": self._racing_line_coords,
                })
        except Exception:
            pass

    def remove_client(self, ws):
        self.clients.discard(ws)

    # ── packet handling ──────────────────────────────────────────────

    def _on_packet(self, data: bytes):
        """Called synchronously from the protocol; must not block."""
        try:
            if len(data) < HEADER_SIZE:
                return

            hdr = struct.unpack_from(HEADER_FMT, data, 0)
            packet_id  = hdr[5]   # m_packetId
            player_idx = hdr[10]  # m_playerCarIndex

            self._last_packet = time.monotonic()
            self._game_connected = True
            self._player_car_index = player_idx

            # Set start time on first packet
            if self._start_time is None:
                self._start_time = time.monotonic()

            if packet_id == PACKET_MOTION:
                self._parse_motion(data)
            elif packet_id == PACKET_SESSION:
                self._parse_session(data)
            elif packet_id == PACKET_TELEMETRY:
                self._parse_telemetry(data)
            elif packet_id == PACKET_LAP_DATA:
                self._parse_lap_data(data, player_idx)
            elif packet_id == PACKET_PARTICIPANTS:
                self._parse_participants(data)
            elif packet_id == PACKET_CAR_STATUS:
                self._parse_car_status(data)
        except (struct.error, IndexError, ValueError):
            pass  # malformed packet — ignore silently

    # ── parsers ──────────────────────────────────────────────────────

    def _parse_motion(self, data: bytes):
        """Parse CarMotionData — apply Fredrik's per-track transform."""
        track_data = TRACK_ID_MAP.get(self._track_id, ("unknown", 1, 0, 0))
        _, d, x_const, z_const = track_data
        for idx in range(22):
            if idx >= self._num_active_cars: continue
            base = HEADER_SIZE + idx * MOTION_CAR_SIZE
            if base + _MOT_Z + 4 > len(data):
                continue
            raw_x = struct.unpack_from("<f", data, base + _MOT_X)[0]
            raw_z = struct.unpack_from("<f", data, base + _MOT_Z)[0]
            # Fredrik's transform: same as applied to racing line files
            x = float(raw_x) / d + x_const
            y = float(raw_z) / d + z_const
            self._car_positions[idx] = {'x': round(x, 2), 'y': round(y, 2)}


    def _parse_session(self, data: bytes):
        """Parse Session packet for track info, weather, session type, laps."""
        base = HEADER_SIZE
        if base + _SES_TRACK_ID + 1 > len(data):
            return
        weather_id  = struct.unpack_from("<B", data, base + _SES_WEATHER)[0]
        track_temp  = struct.unpack_from("<b", data, base + _SES_TRACK_TEMP)[0]
        air_temp    = struct.unpack_from("<b", data, base + _SES_AIR_TEMP)[0]
        total_laps  = struct.unpack_from("<B", data, base + _SES_TOTAL_LAPS)[0]
        track_len   = struct.unpack_from("<H", data, base + _SES_TRACK_LENGTH)[0]
        session_type = struct.unpack_from("<B", data, base + _SES_SESSION_TYPE)[0]
        track_id    = struct.unpack_from("<B", data, base + _SES_TRACK_ID)[0]

        self._weather_id = int(weather_id)
        self._track_temp = float(track_temp)
        self._air_temp   = float(air_temp)
        self._total_laps = int(total_laps)
        self._track_length = float(track_len)

        # Session type change triggers session_info broadcast
        new_session_type_id = int(session_type)
        if new_session_type_id != self._session_type_id:
            self._session_type_id = new_session_type_id
            self._session_type_name = SESSION_TYPE_MAP.get(new_session_type_id, "Unknown")
            self._pending_session_info = True
            log.info("[LiveBridge] Session type: %s (id=%d)", self._session_type_name, new_session_type_id)

        # Time Trial: force 1 active car
        if self._session_type_id == 13:
            self._num_active_cars = 1

        # Reset racing line whenever trackId changes
        new_track_id = int(track_id)
        if new_track_id != self._track_id:
            self._track_id = new_track_id
            self._racing_line_coords = None
            self._pending_racing_line = False
            log.info("[LiveBridge] Track ID changed to %d", new_track_id)

        new_track_data = TRACK_ID_MAP.get(track_id, ("unknown", 1, 0, 0))
        new_track = new_track_data[0] if isinstance(new_track_data, tuple) else new_track_data
        if new_track != self._track_name:
            print(f"[F1 25] Raw trackId: {track_id} → mapped to: {new_track}")
            self._track_name = new_track
            self._pending_track_change = new_track
            self._pending_session_info = True
            # Update recording filename if track changed before first frame
            if self._frame_count == 0 and self._recording_file:
                self._stop_recording()
                self._start_recording()

    def _parse_telemetry(self, data: bytes):
        for idx in range(22):
            if idx >= self._num_active_cars: continue
            base = HEADER_SIZE + idx * TELEMETRY_CAR_SIZE
            if base + _TEL_DRS + 1 > len(data):
                continue
            speed    = struct.unpack_from("<H", data, base + _TEL_SPEED)[0]
            throttle = struct.unpack_from("<f", data, base + _TEL_THROTTLE)[0]
            brake    = struct.unpack_from("<f", data, base + _TEL_BRAKE)[0]
            gear     = struct.unpack_from("<b", data, base + _TEL_GEAR)[0]
            rpm      = struct.unpack_from("<H", data, base + _TEL_RPM)[0]
            drs      = struct.unpack_from("<B", data, base + _TEL_DRS)[0]
            
            self._car_telemetry[idx] = {
                'speed': int(speed),
                'throttle': int(round(float(throttle) * 100)),
                'brake': int(round(float(brake) * 100)),
                'gear': int(gear),
                'rpm': int(rpm),
                'drs': bool(drs),
            }

    def _parse_car_status(self, data: bytes):
        """Parse PacketCarStatusData using verified F1 25 offsets.

        Per-car struct layout (CarStatusData, 42 bytes):
          0: traction_control      uint8
          1: anti_lock_brakes      uint8
          2: fuel_mix              uint8
          3: front_brake_bias      uint8
          4: pit_limiter_status    uint8
          5: fuel_in_tank          float (4)
          9: fuel_capacity         float (4)
         13: fuel_remaining_laps   float (4)
         17: max_rpm               uint16 (2)
         19: idle_rpm              uint16 (2)
         21: max_gears             uint8
         22: drs_allowed           uint8
         23: drs_activation_dist   uint16 (2)
         25: actual_tyre_compound  uint8
         26: visual_tyre_compound  uint8  ← key field
         27: tyres_age_laps        uint8  ← key field
         28: vehicle_fia_flags     int8
         29: engine_power_ice      float (4)
         33: engine_power_mguk     float (4)
         37: ers_store_energy      float (4)
         41: ers_deploy_mode       uint8
        """
        for idx in range(22):
            if idx >= self._num_active_cars:
                continue
            base = HEADER_SIZE + idx * CAR_STATUS_SIZE
            if base + CAR_STATUS_SIZE > len(data):
                break
            try:
                visual_compound = struct.unpack_from("<B", data, base + 26)[0]
                tyre_age        = struct.unpack_from("<B", data, base + 27)[0]
                store_energy    = struct.unpack_from("<f", data, base + 37)[0]
                deploy_mode     = struct.unpack_from("<B", data, base + 41)[0]

                tyre_str = TYRE_MAP.get(visual_compound, 'U')
                self._car_status[idx] = {
                    'tyre': tyre_str,
                    'tyreAge': int(tyre_age),
                    'ersStore': float(store_energy),
                    'ersMode': int(deploy_mode),
                }

                # Debug logging for tyre data
                if idx == 0:
                    if not self._first_tyre_logged:
                        self._first_tyre_logged = True
                        self._last_logged_tyre_age = int(tyre_age)
                        print(f"[F1 25] First tyre packet: car0 compound={visual_compound} age={tyre_age} mapped={tyre_str}")
                    elif int(tyre_age) != getattr(self, '_last_logged_tyre_age', -1):
                        self._last_logged_tyre_age = int(tyre_age)
                        print(f"[F1 25] Tyre age changed: car0 compound={visual_compound} age={tyre_age} mapped={tyre_str}")
            except (struct.error, IndexError):
                pass

    def _parse_lap_data(self, data: bytes, p_idx: int):
        for idx in range(22):
            if idx >= self._num_active_cars: continue
            base = HEADER_SIZE + idx * LAP_DATA_CAR_SIZE
            if base + _LAP_PIT_STATUS + 1 > len(data):
                continue
            s1_ms      = struct.unpack_from("<H", data, base + _LAP_S1_TIME)[0]
            s2_ms      = struct.unpack_from("<H", data, base + _LAP_S2_TIME)[0]
            delta_ms   = struct.unpack_from("<H", data, base + 14)[0]
            total_dist = struct.unpack_from("<f", data, base + _LAP_TOTAL_DIST)[0]
            car_pos    = struct.unpack_from("<B", data, base + _LAP_CAR_POS)[0]
            cur_lap    = struct.unpack_from("<B", data, base + _LAP_CUR_LAP)[0]
            pit_status = struct.unpack_from("<B", data, base + _LAP_PIT_STATUS)[0]
            last_lap_ms = struct.unpack_from("<I", data, base + _LAP_LAST_TIME)[0]
            
            # The prompt requested 's3': lap.sector3TimeInMS... but since we use struct unpacking
            # we will set it to None and let the frontend calculate S3 = lapTime - s1 - s2 as requested.
            self._lap_data[idx] = {
                'position': int(car_pos),
                'currentLap': int(cur_lap),
                's1': s1_ms / 1000.0 if s1_ms > 0 else None,
                's2': s2_ms / 1000.0 if s2_ms > 0 else None,
                's3': None,
                'lastLapMs': last_lap_ms,
                'pitStatus': int(pit_status),
                'totalDistance': float(total_dist),
                'gap': delta_ms / 1000.0,
            }
            if idx == p_idx:
                self._state["lap"] = int(cur_lap)

    def _parse_participants(self, data: bytes):
        base = HEADER_SIZE
        if base + 1 > len(data):
            return
        num_active = struct.unpack_from("<B", data, base)[0]
        # Use participants packet's numActiveCars as the authoritative count
        if self._session_type_id != 13:  # Time Trial stays at 1
            self._num_active_cars = int(num_active)
        base += 1
        rem = len(data) - base
        size_per = rem // 22 if rem >= 22 * 50 else 58
        
        # Rebuild participants dict on every arrival
        new_participants: dict[int, dict] = {}
        first_time = len(self._participants) == 0
        for idx in range(22):
            if idx >= self._num_active_cars: continue
            if base + 50 > len(data):
                break
            team_id = struct.unpack_from("<B", data, base + 3)[0]
            name_bytes = data[base + 7: base + 55]
            name_str = name_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore')
            
            new_participants[idx] = {
                "name": name_str,
                "teamId": int(team_id),
                "active": True,
            }
            if first_time:
                print(f"Car {idx}: name={name_str} teamId={team_id}")
            base += size_per
        self._participants = new_participants

    # ── racing line loader (Fredrik's approach) ────────────────────────

    def _load_racing_line(self, track_name: str) -> list[dict] | None:
        """Load track outline from Fredrik's racing line files.

        Applies the same per-track transform (/ d + offset) used for car
        positions so that outline and dots share the same coordinate space.
        """
        track_data = TRACK_ID_MAP.get(self._track_id, ("unknown", 1, 0, 0))
        _, d, x_const, z_const = track_data

        # Try several filename patterns
        candidates = [
            RACING_LINE_DIR / f"{track_name}_2020_racingline.txt",
            RACING_LINE_DIR / f"{track_name.lower()}_2020_racingline.txt",
            RACING_LINE_DIR / f"{track_name}_racingline.txt",
        ]
        path = None
        for c in candidates:
            if c.exists():
                path = c
                break
        if path is None:
            log.warning("[LiveBridge] No racing line file for '%s'", track_name)
            return None

        coords: list[dict] = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < 2:  # skip header lines
                    continue
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue
                # File columns: dist, z, x, y, drs, sector
                # z → worldPositionX direction, x → worldPositionZ direction
                file_z = float(parts[1])
                file_x = float(parts[2])
                # Same transform as _parse_motion
                tx = file_z / d + x_const
                ty = file_x / d + z_const
                coords.append({'x': round(tx, 4), 'y': round(ty, 4)})

        # Downsample to ~300 points for efficient rendering
        step = max(1, len(coords) // 300)
        downsampled = coords[::step]
        print(f"[F1 25] Racing line loaded: {track_name} ({len(coords)} raw → {len(downsampled)} pts)")
        return downsampled

    # ── frame builder ────────────────────────────────────────────────

    def _build_live_frame(self):
        drivers = []

        best_lap_ms = min(
            (self._lap_data[i].get('lastLapMs', 999999) for i in range(self._num_active_cars) if self._lap_data[i].get('lastLapMs', 0) > 0),
            default=999999
        )

        for i in range(self._num_active_cars):
            participant = self._participants.get(i, {})
            position = self._car_positions.get(i, {})
            status = self._car_status.get(i, {})
            lap = self._lap_data.get(i, {})
            telemetry = self._car_telemetry.get(i, {})
            
            team, color = TEAM_ID_MAP.get(participant.get('teamId', 255), ('Unknown', '#888888'))
            
            gap = lap.get('gap', 0.0)

            drivers.append({
                'code': participant.get('name', f'CAR{i}')[:3].upper(),
                'fullName': participant.get('name', ''),
                'team': team,
                'teamColor': color,
                'position': lap.get('position', i+1),
                'x': position.get('x', 0),
                'y': position.get('y', 0),
                'speed': telemetry.get('speed', 0),
                'gear': telemetry.get('gear', 0),
                'throttle': telemetry.get('throttle', 0),
                'brake': telemetry.get('brake', 0),
                'rpm': telemetry.get('rpm', 0),
                'drs': telemetry.get('drs', False),
                'tyre': status.get('tyre', 'U'),
                'tyreAge': status.get('tyreAge', 0),
                's1': lap.get('s1'),
                's2': lap.get('s2'),
                's3': lap.get('s3'),
                'currentLap': lap.get('currentLap', 0),
                'pitStatus': lap.get('pitStatus', 0),
                'isPlayer': i == self._player_car_index,
                'gapToLeader': gap,
                'isOut': False,
                'fastestLap': lap.get('lastLapMs', 0) == best_lap_ms and best_lap_ms < 999999,
                'lastLapMs': lap.get('lastLapMs', 0),
            })
        
        # Sort by position
        drivers.sort(key=lambda d: d['position'] if d['position'] > 0 else 99)

        return drivers

    def _build_frame(self) -> dict:
        """Build a normalised frame dict matching the replay schema."""
        elapsed = 0.0
        if self._start_time is not None:
            elapsed = round(time.monotonic() - self._start_time, 3)

        active_drivers = self._build_live_frame()

        return {
            "type": "frame",
            "timestamp": elapsed,
            "lap": self._state.get("lap", 1),
            "drivers": active_drivers,
            "weather": {
                "air_temp":  self._air_temp,
                "track_temp": self._track_temp,
                "rainfall":  self._weather_id >= 4,  # 4=heavy rain, 5=storm
                "flag":      "GREEN",
            },
        }

    # ── broadcast loop ───────────────────────────────────────────────

    async def _broadcast_loop(self):
        interval = 1.0 / BROADCAST_HZ
        try:
            while True:
                await asyncio.sleep(interval)

                # ── handle UDP silence (game closed / in menu) ────────
                if self._game_connected:
                    if time.monotonic() - self._last_packet > SILENCE_TIMEOUT:
                        self._game_connected = False
                        self._state.clear()
                        await self._broadcast({"type": "live_disconnected"})
                        continue

                if self._pending_track_change:
                    circuit_name = self._pending_track_change
                    self._pending_track_change = None
                    await self._broadcast({
                        "type": "track_change",
                        "circuit": circuit_name,
                        "year": 2025
                    })
                    # Load racing line from file (same coord system as car positions)
                    self._racing_line_coords = self._load_racing_line(circuit_name)
                    if self._racing_line_coords:
                        self._pending_racing_line = True

                if self._pending_racing_line and self._racing_line_coords:
                    self._pending_racing_line = False
                    await self._broadcast({
                        "type": "live_track",
                        "coords": self._racing_line_coords,
                    })

                if self._pending_session_info:
                    self._pending_session_info = False
                    await self._broadcast({
                        "type": "session_info",
                        "sessionType": self._session_type_name,
                        "sessionTypeId": self._session_type_id,
                        "trackName": self._track_name,
                        "totalLaps": self._total_laps,
                        "trackLength": self._track_length,
                        "numActiveCars": self._num_active_cars,
                    })

                if not self._participants or not self.clients:
                    continue

                # Throttle broadcasts to max BROADCAST_HZ per second
                now = time.time()
                if now - self._last_broadcast < (1.0 / BROADCAST_HZ):
                    continue
                self._last_broadcast = now

                frame = self._build_frame()
                self._record_frame(frame)
                await self._broadcast(frame)

        except asyncio.CancelledError:
            pass

    def set_track_coords(self, x_arr: list[float], y_arr: list[float]):
        """Legacy stub — no longer used for live mode."""
        pass

    async def _broadcast(self, data: dict):
        dead: set = set()
        for ws in list(self.clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.clients -= dead
