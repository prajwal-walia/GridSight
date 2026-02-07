"""
/api/laps  –  per-driver telemetry endpoints.
"""

from __future__ import annotations

import asyncio
import functools
import logging

import numpy as np
import pandas as pd
from fastapi import APIRouter

from fastapi.responses import JSONResponse

# Re-use the shared session cache from the sessions module
from api.sessions import _get_session

from models.schemas import DriverTelemetryResponse

DRIVER_NUMBER_FALLBACK = {
    2022: {
        'HAM':'44','RUS':'63','VER':'1','PER':'11','LEC':'16',
        'SAI':'55','NOR':'4','RIC':'3','ALO':'14','OCO':'31',
        'GAS':'10','TSU':'22','VET':'5','STR':'18','ALB':'23',
        'LAT':'6','BOT':'77','ZHO':'24','MAG':'20','MSC':'47',
    },
    2023: {
        'HAM':'44','RUS':'63','VER':'1','PER':'11','LEC':'16',
        'SAI':'55','NOR':'4','PIA':'81','ALO':'14','STR':'18',
        'GAS':'10','OCO':'31','DEV':'21','TSU':'22','RIC':'3',
        'LAW':'40','ALB':'23','SAR':'2','BOT':'77','ZHO':'24',
        'MAG':'20','HUL':'27',
    },
    2024: {
        'HAM':'44','RUS':'63','VER':'1','PER':'11','LEC':'16',
        'SAI':'55','NOR':'4','PIA':'81','ALO':'14','STR':'18',
        'GAS':'10','OCO':'31','TSU':'22','RIC':'3','LAW':'40',
        'ALB':'23','SAR':'2','COO':'43','BOT':'77','ZHO':'24',
        'MAG':'20','HUL':'27','BEA':'87','DOO':'7',
    },
    2025: {
        'VER':'1','LAW':'30','TSU':'22','HAD':'6','LEC':'16',
        'HAM':'44','RUS':'63','ANT':'12','NOR':'4','PIA':'81',
        'ALO':'14','STR':'18','GAS':'10','DOO':'7','COL':'43',
        'COO':'43','ALB':'23','SAI':'55','HUL':'27','BOR':'5',
        'OCO':'31','BEA':'87',
    },
    2026: {
        'VER':'3','HAD':'6','LEC':'16','HAM':'44','RUS':'63',
        'ANT':'12','NOR':'1','PIA':'81','ALO':'14','STR':'18',
        'GAS':'10','COL':'43','ALB':'23','SAI':'55','LAW':'30',
        'LIN':'41','HUL':'27','BOR':'5','OCO':'31','BEA':'87',
        'PER':'11','BOT':'77',
    },
}

def get_driver_num(session, driver_code: str, year: int) -> str | None:
    code = driver_code.strip().upper()[:3]
    try:
        for num in session.drivers:
            try:
                info = session.get_driver(num)
                for field in ['Abbreviation', 'abbreviation', 'DriverId']:
                    val = str(info.get(field, '')).strip().upper()[:3]
                    if val == code:
                        return str(num)
            except Exception:
                continue
    except Exception:
        pass
    if year in DRIVER_NUMBER_FALLBACK:
        result = DRIVER_NUMBER_FALLBACK[year].get(code)
        if result:
            return result
    for y in sorted(DRIVER_NUMBER_FALLBACK.keys(), key=lambda x: abs(x - year)):
        result = DRIVER_NUMBER_FALLBACK[y].get(code)
        if result:
            return result
    return None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/laps", tags=["laps"])


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )


# ── GET /{year}/{round}/{type}/{driver}/telemetry ─────────────────────────

@router.get(
    "/{year}/{round_num}/{session_type}/{driver}/telemetry",
    response_model=DriverTelemetryResponse,
)
async def get_driver_telemetry(
    year: int,
    round_num: int,
    session_type: str,
    driver: str,
):
    # Attempt to load session — if this fails, return empty gracefully
    try:
        session = await _get_session(year, round_num, session_type.upper())
    except Exception as e:
        logger.warning(f"Could not load session for telemetry: {e}")
        return DriverTelemetryResponse(
            driver_code=driver.upper(),
            telemetry_available=False,
            message=f"Session not available: {year} R{round_num} {session_type.upper()}",
        )

    print(f"\n=== TELEMETRY REQUEST: {year} R{round_num} {session_type} {driver} ===")

    def _extract():
        driver_code = driver.upper()
        driver_upper = driver_code

        driver_num = get_driver_num(session, driver_code, int(year))
        print(f"Driver num resolved: {driver_num}")
        if not driver_num:
            return JSONResponse({
                "telemetry_available": False,
                "error": f"Driver {driver_code} not found for {year}"
            })
        driver_laps = session.laps[
            session.laps['DriverNumber'].astype(str) == str(driver_num)
        ]
        print(f"Driver laps found: {len(driver_laps)} rows")
        if driver_laps.empty:
            return JSONResponse({
                "telemetry_available": False,
                "error": f"No laps for {driver_code} (#{driver_num})"
            })
        fastest = driver_laps.pick_fastest()
        print(f"Fastest lap: {fastest}")
        if fastest is None:
            return JSONResponse({
                "telemetry_available": False,
                "error": f"No valid fastest lap for {driver_code}"
            })

        full_name = driver_code
        team_color = "#999999"
        try:
            drv_info = session.get_driver(driver_num)
            full_name = str(drv_info.get("FullName", driver_code))
            tc = str(drv_info.get("TeamColor", "999999"))
            if tc and tc != "nan":
                team_color = f"#{tc}"
        except Exception:
            pass

        # ── attempt telemetry extraction ──────────────────────────────
        try:
            tel = fastest.get_telemetry()
            if tel is None or tel.empty:
                raise ValueError("Empty telemetry")
        except Exception as e:
            logger.warning(f"Telemetry unavailable for {driver_upper} in {year} R{round_num}: {e}")
            return DriverTelemetryResponse(
                driver_code=driver_upper,
                full_name=full_name,
                team_color=team_color,
                telemetry_available=False,
                message="Car telemetry not available for this session",
            )

        # ── extract arrays ────────────────────────────────────────────
        try:
            distance = tel["Distance"].to_numpy().astype(float)
            speed = tel["Speed"].to_numpy().astype(float)
            throttle = tel["Throttle"].to_numpy().astype(float) if "Throttle" in tel.columns else np.zeros(len(tel))
            brake = np.array([int(b) * 100 for b in tel["Brake"].tolist()], dtype=int) if "Brake" in tel.columns else np.zeros(len(tel), dtype=int)
            gear = tel["nGear"].to_numpy().astype(int) if "nGear" in tel.columns else np.zeros(len(tel), dtype=int)
            drs = tel["DRS"].to_numpy().astype(int) if "DRS" in tel.columns else np.zeros(len(tel), dtype=int)
        except Exception as e:
            logger.warning(f"Error extracting telemetry arrays for {driver_upper}: {e}")
            return DriverTelemetryResponse(
                driver_code=driver_upper,
                full_name=full_name,
                team_color=team_color,
                telemetry_available=False,
                message=f"Error reading telemetry data: {e}",
            )

        # ── lap time in ms ────────────────────────────────────────────
        lap_time_ms = None
        try:
            if pd.notna(fastest.get("LapTime")):
                lt = fastest["LapTime"]
                if hasattr(lt, 'total_seconds'):
                    lap_time_ms = round(lt.total_seconds() * 1000, 1)
                elif hasattr(lt, 'timestamp'):
                    lap_time_ms = round(lt.timestamp() * 1000, 1)
                else:
                    lap_time_ms = round(float(lt) * 1000, 1)
        except Exception:
            pass

        return DriverTelemetryResponse(
            driver_code=driver_upper,
            full_name=full_name,
            team_color=team_color,
            lap_time_ms=lap_time_ms,
            distance=[round(float(v), 1) for v in distance],
            speed=[round(float(v), 1) for v in speed],
            throttle=[round(float(v), 1) for v in throttle],
            brake=[int(v) for v in brake],
            gear=gear.tolist(),
            drs=drs.tolist(),
            telemetry_available=True,
        )

    try:
        result = await _run(_extract)
    except Exception as e:
        logger.error(f"Unexpected telemetry error for {driver} in {year} R{round_num}: {e}")
        result = DriverTelemetryResponse(
            driver_code=driver.upper(),
            telemetry_available=False,
            message=f"Unexpected error: {e}",
        )
    return result

