"""Pydantic response models for every /api/sessions endpoint."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


# ── /years ────────────────────────────────────────────────────────────────

class YearsResponse(BaseModel):
    years: list[int]


# ── /rounds ───────────────────────────────────────────────────────────────

class RoundInfo(BaseModel):
    round_number: int
    event_name: str
    date: str
    country: str
    event_format: str
    session_dates: dict[str, str] = {}


class RoundsResponse(BaseModel):
    year: int
    rounds: list[RoundInfo]


# ── /types ────────────────────────────────────────────────────────────────

class SessionTypeInfo(BaseModel):
    key: str   # e.g. "R", "Q", "FP1"
    name: str  # e.g. "Race", "Qualifying"


class SessionTypesResponse(BaseModel):
    year: int
    round_number: int
    event_name: str
    types: list[SessionTypeInfo]


# ── /metadata ─────────────────────────────────────────────────────────────

class DriverInfo(BaseModel):
    code: str
    full_name: str
    team: str
    color: str  # hex colour incl. "#"


class SessionMetadataResponse(BaseModel):
    year: int
    round_number: int
    session_type: str
    event_name: str
    circuit_short_name: str
    country: str
    date: str
    total_laps: Optional[int] = None
    drivers: list[DriverInfo]


# ── /track ────────────────────────────────────────────────────────────────

class TrackCoord(BaseModel):
    x: float
    y: float


class DRSZone(BaseModel):
    start: float  # relative distance 0-1
    end: float


class DRSZoneXY(BaseModel):
    start_x: float
    start_y: float
    end_x: float
    end_y: float


class SectorPoint(BaseModel):
    sector: int   # 1, 2, or 3
    x: float
    y: float


class TrackResponse(BaseModel):
    coords: list[TrackCoord]
    rotation: float
    drs_zones: list[DRSZone]
    drs_zones_xy: list[DRSZoneXY] = []
    sector_points: list[SectorPoint] = []
    pit_entry: Optional[TrackCoord] = None
    pit_exit: Optional[TrackCoord] = None
    x_min: float = 0.0
    x_max: float = 1.0
    y_min: float = 0.0
    y_max: float = 1.0
    active_aero: bool = False


# ── /weather ──────────────────────────────────────────────────────────────

class WeatherSample(BaseModel):
    time: float
    air_temp: Optional[float] = None
    track_temp: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    rainfall: bool = False


class WeatherResponse(BaseModel):
    samples: list[WeatherSample]


# ── /flags ────────────────────────────────────────────────────────────────

TRACK_STATUS_MAP: dict[str, str] = {
    "1": "Track Clear",
    "2": "Yellow Flag",
    "3": "SC Ending",
    "4": "Safety Car",
    "5": "Red Flag",
    "6": "Virtual Safety Car",
    "7": "VSC Ending",
}


class FlagEvent(BaseModel):
    status: str
    message: str
    start_time: float
    end_time: Optional[float] = None


class FlagsResponse(BaseModel):
    flags: list[FlagEvent]


# ── /laps ─────────────────────────────────────────────────────────────────

class LapInfo(BaseModel):
    driver_code: str
    lap_number: int
    position: Optional[int] = None
    lap_time: Optional[float] = None
    sector1_time: Optional[float] = None
    sector2_time: Optional[float] = None
    sector3_time: Optional[float] = None
    compound: Optional[str] = None
    tyre_life: Optional[int] = None
    is_personal_best: bool = False


class LapsResponse(BaseModel):
    laps: list[LapInfo]


# ── /laps/{driver}/telemetry ──────────────────────────────────────────────

class DriverTelemetryResponse(BaseModel):
    driver_code: str
    full_name: str = ""
    team_color: str = "#999999"  # hex incl. "#"
    lap_time_ms: Optional[float] = None
    distance: list[float] = []
    speed: list[float] = []
    throttle: list[float] = []
    brake: list[float] = []
    gear: list[int] = []
    drs: list[int] = []
    telemetry_available: bool = True
    message: Optional[str] = None


# ── /status ───────────────────────────────────────────────────────────────

class SessionStatusResponse(BaseModel):
    status: str                          # "cached" | "loading" | "not_cached" | "error"
    source: Optional[str] = None        # "computed" | "fastf1"
    progress: int = 0                   # 0-100
    detail: Optional[str] = None        # error message if status == "error"


# ── /cache ────────────────────────────────────────────────────────────────

class CacheEntry(BaseModel):
    year: int
    round: int
    type: str
    file_size_mb: float


class CacheListResponse(BaseModel):
    sessions: list[CacheEntry]


class PreloadRequest(BaseModel):
    year: int
    round: int
    type: str


class PreloadResponse(BaseModel):
    status: str

