"""
/api/sessions  –  REST endpoints for FastF1 session data.

All heavy FastF1 work is dispatched to a thread-pool executor so the
async event-loop stays responsive.
"""

from __future__ import annotations

import asyncio
import functools
from collections import OrderedDict

import fastf1
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from core.f1_data import enable_cache, get_track_features
from core.async_wrappers import load_session as async_load_session
from models.schemas import (
    YearsResponse,
    RoundsResponse, RoundInfo,
    SessionTypesResponse, SessionTypeInfo,
    SessionMetadataResponse, DriverInfo,
    TrackResponse, TrackCoord, DRSZone, DRSZoneXY, SectorPoint,
    WeatherResponse, WeatherSample,
    FlagsResponse, FlagEvent, TRACK_STATUS_MAP,
    LapsResponse, LapInfo,
    SessionStatusResponse,
)
from core.cache_manager import (
    get_status as cache_get_status,
    has_track_cache, read_track_cache, write_track_cache,
)
from core.regulations import get_regulation_era

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# ── helpers ───────────────────────────────────────────────────────────────

SESSION_NAME_TO_KEY: dict[str, str] = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Q",
    "Race": "R",
    "Sprint": "S",
    "Sprint Qualifying": "SQ",
    "Sprint Shootout": "SS",
}

_session_cache: OrderedDict = OrderedDict()
_MAX_SESSIONS = 5


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )


async def _get_session(year: int, round_num: int, session_type: str):
    key = (year, round_num, session_type)
    
    def _force_load(s):
        s.load(
            laps=True,
            telemetry=True,
            weather=True,
            messages=True
        )
        return s

    if key in _session_cache:
        _session_cache.move_to_end(key)
        session = _session_cache[key]
        if getattr(session, "laps", None) is None or session.laps.empty:
            await _run(_force_load, session)
        return session

    try:
        session = await async_load_session(year, round_num, session_type)
        # Ensure the session was loaded with laps=True before storing
        if getattr(session, "laps", None) is None or session.laps.empty:
            await _run(_force_load, session)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Could not load session {year} R{round_num} {session_type}: {exc}",
        )

    _session_cache[key] = session
    while len(_session_cache) > _MAX_SESSIONS:
        _session_cache.popitem(last=False)
    return session


def safe_to_seconds(t):
    if t is None or (hasattr(t, '__class__') and 'NaT' in str(t.__class__)):
        return None
    if hasattr(t, 'total_seconds'):
        return t.total_seconds()  # Timedelta
    if hasattr(t, 'timestamp'):
        try:
            return t.timestamp()  # datetime
        except Exception:
            pass
    try:
        return float(t)
    except Exception:
        return None


def _td_to_seconds(td) -> float | None:
    if pd.isna(td):
        return None
    val = safe_to_seconds(td)
    return round(val, 3) if val is not None else None


# ── 0. GET /{year}/{round}/{type}/status ──────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/status",
            response_model=SessionStatusResponse)
async def get_session_status(year: int, round_num: int, session_type: str):
    """Return loading / cache status for a session."""
    try:
        session = await _get_session(year, round_num, session_type.upper())
        if len(getattr(session, "drivers", [])) == 0:
            return {
                "status": "unavailable",
                "message": "Session data not yet available — check back after the session",
                "drivers": 0
            }
    except Exception:
        pass

    info = cache_get_status(year, round_num, session_type.upper())
    return SessionStatusResponse(**info)


# ── 1. GET /years ─────────────────────────────────────────────────────────

@router.get("/years", response_model=YearsResponse)
async def get_years():
    return YearsResponse(years=list(range(2022, 2027)))


# ── 2. GET /{year}/rounds ─────────────────────────────────────────────────

@router.get("/{year}/rounds", response_model=RoundsResponse)
async def get_rounds(year: int):
    def _load():
        enable_cache()
        return fastf1.get_event_schedule(int(year))

    try:
        schedule = await _run(_load)
    except Exception as exc:
        if year >= 2026:
            return RoundsResponse(year=year, rounds=[])
        raise HTTPException(404, f"No schedule for {year}: {exc}")

    rounds: list[RoundInfo] = []
    for _, ev in schedule.iterrows():
        if ev.is_testing():
            continue
        session_dates: dict[str, str] = {}
        for i in range(1, 6):
            sn = ev.get(f"Session{i}")
            sd = ev.get(f"Session{i}Date")
            if sn and pd.notna(sd):
                session_dates[str(sn)] = sd.isoformat()
        rounds.append(RoundInfo(
            round_number=int(ev["RoundNumber"]),
            event_name=str(ev["EventName"]),
            date=str(ev["EventDate"].date()),
            country=str(ev["Country"]),
            event_format=str(ev["EventFormat"]),
            session_dates=session_dates,
        ))
    return RoundsResponse(year=year, rounds=rounds)


# ── 3. GET /{year}/{round}/types ──────────────────────────────────────────

@router.get("/{year}/{round_num}/types", response_model=SessionTypesResponse)
async def get_types(year: int, round_num: int):
    def _load():
        enable_cache()
        schedule = fastf1.get_event_schedule(int(year))
        rows = schedule[schedule["RoundNumber"] == round_num]
        if rows.empty:
            return None
        return rows.iloc[0]

    event = await _run(_load)
    if event is None:
        raise HTTPException(404, f"Round {round_num} not found for {year}")

    types: list[SessionTypeInfo] = []
    for i in range(1, 6):
        name = event.get(f"Session{i}")
        if name and pd.notna(name) and str(name).strip():
            key = SESSION_NAME_TO_KEY.get(str(name), str(name))
            types.append(SessionTypeInfo(key=key, name=str(name)))

    return SessionTypesResponse(
        year=year,
        round_number=round_num,
        event_name=str(event["EventName"]),
        types=types,
    )


# ── 4. GET /{year}/{round}/{type}/metadata ────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/metadata",
            response_model=SessionMetadataResponse)
async def get_metadata(year: int, round_num: int, session_type: str):
    session = await _get_session(year, round_num, session_type.upper())

    drivers: list[DriverInfo] = []
    if session.results is not None and not session.results.empty:
        for _, row in session.results.iterrows():
            code = str(row.get("Abbreviation", "")).strip()[:3].upper()
            if not code:
                continue
            team_color = str(row.get("TeamColor", "999999"))
            if team_color == "nan":
                team_color = "999999"
            drivers.append(DriverInfo(
                code=code,
                full_name=str(row.get("FullName", code)),
                team=str(row.get("TeamName", "Unknown")),
                color=f"#{team_color}",
            ))

    total_laps = None
    if session_type.upper() in ("R", "S"):
        try:
            total_laps = int(session.total_laps)
        except Exception:
            if session.laps is not None and not session.laps.empty:
                total_laps = int(session.laps["LapNumber"].max())

    ev = session.event
    return SessionMetadataResponse(
        year=year,
        round_number=round_num,
        session_type=session_type.upper(),
        event_name=str(ev["EventName"]),
        circuit_short_name=str(ev.get("Location", "")),
        country=str(ev["Country"]),
        date=str(ev["EventDate"].date()) if pd.notna(ev.get("EventDate")) else "",
        total_laps=total_laps,
        drivers=drivers,
    )


# ── 5. GET /{year}/{round}/{type}/track ──────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/track",
            response_model=TrackResponse)
async def get_track(year: int, round_num: int, session_type: str):
    stype = session_type.upper()
    error_msg = ""
    try:
        session = await _get_session(year, round_num, stype)
        if len(getattr(session, "drivers", [])) == 0:
            raise Exception("0 drivers in session")
    except Exception as e:
        session = None
        error_msg = str(e)

    def _extract():
        x = None
        y = None
        tel = None
        rotation = 0.0

        # ── rotation & circuit info ───────────────────────────────────
        try:
            circuit_info = session.get_circuit_info()
            rotation = float(circuit_info.rotation)
        except Exception:
            circuit_info = None

        # ── Method 1: get_telemetry (2022-2025 with full car data) ────
        try:
            fastest = session.laps.pick_fastest()
            if fastest is not None:
                tel = fastest.get_telemetry()
                if tel is not None and not tel.empty and "X" in tel.columns:
                    x = tel["X"].to_numpy().astype(float)
                    y = tel["Y"].to_numpy().astype(float)
        except Exception:
            pass

        # ── Method 2: position data (works for 2026 without car data) ─
        if x is None:
            try:
                pos_data = getattr(session, "pos_data", None)
                if pos_data is not None and len(pos_data) > 0:
                    drivers_to_try = list(session.drivers[:3]) if hasattr(session, "drivers") else []
                    for driver_num in drivers_to_try:
                        try:
                            pos = pos_data.get(driver_num)
                            if pos is not None and not pos.empty and "X" in pos.columns:
                                x = pos["X"].to_numpy().astype(float)
                                y = pos["Y"].to_numpy().astype(float)
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        # ── Method 3: circuit_info track map coordinates ──────────────
        if x is None and circuit_info is not None:
            try:
                corners = getattr(circuit_info, "corners", None)
                if corners is not None and not corners.empty:
                    x = corners["X"].to_numpy().astype(float)
                    y = corners["Y"].to_numpy().astype(float)
            except Exception:
                pass

        # ── All methods failed — return empty track ───────────────────
        if x is None or y is None or len(x) < 2:
            return TrackResponse(
                coords=[], rotation=rotation,
                drs_zones=[], drs_zones_xy=[],
                sector_points=[],
                pit_entry=None, pit_exit=None,
                x_min=0, x_max=0, y_min=0, y_max=0,
                active_aero=get_regulation_era(int(year)).get("has_active_aero", False),
            )

        # ── Normalise to 0-1 ──────────────────────────────────────────
        x_min, x_max = float(x.min()), float(x.max())
        y_min, y_max = float(y.min()), float(y.max())
        x_range = (x_max - x_min) or 1.0
        y_range = (y_max - y_min) or 1.0
        x_norm = (x - x_min) / x_range
        y_norm = (y - y_min) / y_range

        # downsample to ~300 points
        step = max(1, len(x_norm) // 300)
        coords = [
            TrackCoord(x=round(float(x_norm[i]), 5),
                       y=round(float(y_norm[i]), 5))
            for i in range(0, len(x_norm), step)
        ]

        # ── DRS zones (only if telemetry available) ───────────────────
        zones: list[DRSZone] = []
        if tel is not None and "DRS" in tel.columns and "RelativeDistance" in tel.columns:
            drs = tel["DRS"].to_numpy()
            rel = tel["RelativeDistance"].to_numpy()
            in_zone = False
            z_start = 0.0
            for i in range(len(drs)):
                if drs[i] >= 10 and not in_zone:
                    in_zone = True
                    z_start = float(rel[i])
                elif drs[i] < 10 and in_zone:
                    in_zone = False
                    zones.append(DRSZone(start=round(z_start, 4),
                                         end=round(float(rel[i]), 4)))
            if in_zone:
                zones.append(DRSZone(start=round(z_start, 4),
                                     end=round(float(rel[-1]), 4)))

        # ── Sector points + DRS zones XY (cached) ────────────────────
        stype_upper = session_type.upper()
        if has_track_cache(int(year), int(round_num), stype_upper):
            features = read_track_cache(int(year), int(round_num), stype_upper)
            print(f"[track] Loaded features from cache for {year} R{round_num} {stype_upper}")
        else:
            try:
                features = get_track_features(session)
                write_track_cache(int(year), int(round_num), stype_upper, features)
            except Exception:
                features = {"sector_points": [], "drs_zones_xy": []}

        sector_points = [
            SectorPoint(**sp) for sp in features.get("sector_points", [])
        ]
        drs_zones_xy = [
            DRSZoneXY(**dz) for dz in features.get("drs_zones_xy", [])
        ]

        # Pit lane markers
        pit_entry_raw = features.get("pit_entry")
        pit_exit_raw = features.get("pit_exit")
        pit_entry = TrackCoord(**pit_entry_raw) if pit_entry_raw else None
        pit_exit = TrackCoord(**pit_exit_raw) if pit_exit_raw else None

        # 2026: active aero replaces DRS
        era = get_regulation_era(int(year))
        is_active_aero = era.get("has_active_aero", False)
        if is_active_aero:
            zones = []
            drs_zones_xy = []

        return TrackResponse(
            coords=coords, rotation=rotation,
            drs_zones=zones,
            drs_zones_xy=drs_zones_xy,
            sector_points=sector_points,
            pit_entry=pit_entry,
            pit_exit=pit_exit,
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            active_aero=is_active_aero,
        )

    if session is not None:
        try:
            result = await _run(_extract)
        except Exception as e:
            error_msg = str(e)
            result = None
    else:
        result = None

    if result is None:
        print(f"[track] Failed to load track for {year} R{round_num} {stype}: {error_msg}")
        # Try to find the circuit name from FastF1 schedule
        try:
            schedule = fastf1.get_event_schedule(int(year))
            event = schedule[schedule['RoundNumber'] == int(round_num)]
            if not event.empty:
                circuit = event.iloc[0]['Location']
                # Try loading same circuit from previous year
                return await get_circuit_track(circuit)
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Track data not available yet")

    return result


# ── 5a. GET /circuit/{circuit_name}/track ─────────────────────────────────

CIRCUIT_TO_ROUND = {
    'miami': (2024, 6, 'R'),
    'miami gardens': (2024, 6, 'R'),
    'sakhir': (2024, 1, 'R'),
    'bahrain': (2024, 1, 'R'),
    'melbourne': (2024, 3, 'R'),
    'shanghai': (2024, 5, 'R'),
    'suzuka': (2024, 4, 'R'),
    'jeddah': (2024, 2, 'R'),
    'monaco': (2024, 8, 'R'),
    'montreal': (2024, 9, 'R'),
    'silverstone': (2024, 12, 'R'),
    'red bull ring': (2024, 11, 'R'),
    'spielberg': (2024, 11, 'R'),
    'hungaroring': (2024, 13, 'R'),
    'spa': (2024, 14, 'R'),
    'spa-francorchamps': (2024, 14, 'R'),
    'zandvoort': (2024, 15, 'R'),
    'monza': (2024, 16, 'R'),
    'baku': (2024, 17, 'R'),
    'singapore': (2024, 18, 'R'),
    'austin': (2024, 19, 'R'),
    'mexico city': (2024, 20, 'R'),
    'mexico': (2024, 20, 'R'),
    'interlagos': (2024, 21, 'R'),
    'sao paulo': (2024, 21, 'R'),
    'las vegas': (2024, 22, 'R'),
    'losail': (2024, 23, 'R'),
    'abu dhabi': (2024, 24, 'R'),
    'imola': (2024, 7, 'R'),
    'barcelona': (2024, 10, 'R'),
    'madrid': (2025, 11, 'R'),
    'portimao': (2023, 3, 'R'),
}

@router.get("/circuit/{circuit_name}/track", response_model=TrackResponse)
async def get_circuit_track(circuit_name: str):
    # Normalize circuit name
    name_lower = circuit_name.lower().strip()
    
    # Find matching entry in CIRCUIT_TO_ROUND
    fallback = None
    for key, value in CIRCUIT_TO_ROUND.items():
        if key.lower() == name_lower or key.lower() in name_lower or name_lower in key.lower():
            fallback = value
            break
    
    if fallback:
        year, rnd, stype = fallback
        # Call the existing track logic directly, not via redirect
        return await get_track(year, rnd, stype)
    
    raise HTTPException(status_code=404, detail=f"No track data available for {circuit_name}")


# ── 5b. GET /{year}/{round}/pit-loss ─────────────────────────────────────

@router.get("/{year}/{round_num}/pit-loss")
async def get_pit_loss(year: int, round_num: int):
    """Return pit loss data for a given circuit/round."""
    try:
        from core.pit_prediction import get_pit_loss_for_event

        # Try to get event name from schedule
        def _load():
            enable_cache()
            schedule = fastf1.get_event_schedule(int(year))
            rows = schedule[schedule["RoundNumber"] == round_num]
            if rows.empty:
                return None
            return str(rows.iloc[0]["EventName"])

        event_name = await _run(_load)
        if not event_name:
            return {"pit_loss": None, "reason": "Event not found"}

        pit_loss = get_pit_loss_for_event(event_name)
        if pit_loss is None:
            return {"pit_loss": None, "reason": "No pit loss data for this circuit"}

        return {
            "event_name": event_name,
            "pit_loss": pit_loss,
            "regulation_era": get_regulation_era(year),
        }
    except Exception as e:
        return {"pit_loss": None, "reason": str(e)}


# ── 6. GET /{year}/{round}/{type}/weather ─────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/weather",
            response_model=WeatherResponse)
async def get_weather(year: int, round_num: int, session_type: str):
    session = await _get_session(year, round_num, session_type.upper())

    wdf = getattr(session, "weather_data", None)
    if wdf is None or wdf.empty:
        return WeatherResponse(samples=[])

    samples: list[WeatherSample] = []
    for _, row in wdf.iterrows():
        samples.append(WeatherSample(
            time=round(safe_to_seconds(row["Time"]), 1)
                 if pd.notna(row.get("Time")) else 0.0,
            air_temp=float(row["AirTemp"])
                     if pd.notna(row.get("AirTemp")) else None,
            track_temp=float(row["TrackTemp"])
                       if pd.notna(row.get("TrackTemp")) else None,
            humidity=float(row["Humidity"])
                     if pd.notna(row.get("Humidity")) else None,
            wind_speed=float(row["WindSpeed"])
                       if pd.notna(row.get("WindSpeed")) else None,
            wind_direction=float(row["WindDirection"])
                           if pd.notna(row.get("WindDirection")) else None,
            rainfall=bool(row["Rainfall"])
                     if pd.notna(row.get("Rainfall")) else False,
        ))
    return WeatherResponse(samples=samples)


# ── 7. GET /{year}/{round}/{type}/flags ──────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/flags",
            response_model=FlagsResponse)
async def get_flags(year: int, round_num: int, session_type: str):
    session = await _get_session(year, round_num, session_type.upper())

    ts = session.track_status
    flags: list[FlagEvent] = []
    for _, row in ts.iterrows():
        code = str(row.get("Status", ""))
        flags.append(FlagEvent(
            status=code,
            message=str(row.get("Message", ""))
                    or TRACK_STATUS_MAP.get(code, "Unknown"),
            start_time=round(safe_to_seconds(row["Time"]), 3)
                       if pd.notna(row.get("Time")) else 0.0,
        ))

    # chain end-times
    for i in range(len(flags) - 1):
        flags[i].end_time = flags[i + 1].start_time

    return FlagsResponse(flags=flags)


# ── 8. GET /{year}/{round}/{type}/laps ───────────────────────────────────

@router.get("/{year}/{round_num}/{session_type}/laps",
            response_model=LapsResponse)
async def get_laps(year: int, round_num: int, session_type: str):
    session = await _get_session(year, round_num, session_type.upper())

    if session.laps is None or session.laps.empty:
        return LapsResponse(laps=[])

    laps: list[LapInfo] = []
    for _, lap in session.laps.iterrows():
        if pd.isna(lap.get("LapNumber")):
            continue
        laps.append(LapInfo(
            driver_code=str(lap.get("Driver", "")),
            lap_number=int(lap["LapNumber"]),
            position=int(lap["Position"])
                     if pd.notna(lap.get("Position")) else None,
            lap_time=_td_to_seconds(lap.get("LapTime")),
            sector1_time=_td_to_seconds(lap.get("Sector1Time")),
            sector2_time=_td_to_seconds(lap.get("Sector2Time")),
            sector3_time=_td_to_seconds(lap.get("Sector3Time")),
            compound=str(lap["Compound"])
                     if pd.notna(lap.get("Compound")) else None,
            tyre_life=int(lap["TyreLife"])
                      if pd.notna(lap.get("TyreLife")) else None,
            is_personal_best=bool(lap["IsPersonalBest"])
                             if pd.notna(lap.get("IsPersonalBest"))
                             else False,
        ))

    return LapsResponse(laps=laps)
