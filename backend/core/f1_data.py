import logging
logging.getLogger("fastf1.core").setLevel(logging.ERROR)

import os
import re
import sys
from datetime import timedelta, date
from typing import Callable, Optional

# Type alias for the progress callback used during caching
ProgressCallback = Optional[Callable[[int], None]]

import fastf1
import fastf1.plotting
import numpy as np
import pandas as pd

from core.tyres import get_tyre_compound_int
from core.cache_manager import has_computed_cache, read_computed, write_computed


# ---------------------------------------------------------------------------
# Helpers inlined from the original repo's src.lib.time / src.lib.settings
# ---------------------------------------------------------------------------

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".fastf1-cache")


def enable_cache():
    if not os.path.exists(CACHE_PATH):
        os.makedirs(CACHE_PATH)
    fastf1.Cache.enable_cache(CACHE_PATH)


def parse_time_string(time_str: str) -> Optional[float]:
    """
    Parse strings like:
      - "00:01:26:123000"
      - "00:01:26.123000"
      - "01:26.123"
      - "01:26"
    and return total seconds as float. Returns None if parsing fails.
    """
    # Handle timedelta format like "0 days 00:01:27.060000"
    if "days" in str(time_str):
        time_str = str(time_str).split(" ", 2)[-1]
    else:
        time_str = str(time_str).split(" ")[0]

    if time_str is None:
        return None

    s = str(time_str).strip()
    if s == "":
        return None

    parts = re.split(r'[:.]', s)
    hh = 0
    micro = 0

    try:
        if len(parts) == 4:
            hh, mm, ss, micro = parts
        elif len(parts) == 3:
            if len(parts[2]) > 2:
                mm, ss, micro = parts
            else:
                hh, mm, ss = parts
        elif len(parts) == 2:
            mm, ss = parts
        else:
            return None

        hh = int(hh)
        mm = int(mm)
        ss = int(ss)
        micro = int(str(micro)[:6].ljust(6, '0')) if micro is not None and str(micro) != "" else 0

        total_seconds = hh * 3600 + mm * 60 + ss + micro / 1_000_000.0

        return round(total_seconds, 3)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Original f1_data.py logic — preserved exactly
# ---------------------------------------------------------------------------

FPS = 25
DT = 1 / FPS


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

def get_driver_num_from_session(session, driver_code: str, year: int) -> str | None:
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

def _pick_driver_laps(laps_df, driver_code: str, driver_num: str | None = None):
    """Robustly pick laps for a driver.
    
    Primary method: direct DataFrame filter by DriverNumber (most reliable).
    Fallbacks: abbreviation, Driver column, pick_drivers().
    Returns a (possibly empty) DataFrame — never raises.
    """
    if laps_df is None or laps_df.empty:
        return laps_df

    # 1. Primary: Direct DataFrame filter by DriverNumber
    if driver_num:
        try:
            result = laps_df[laps_df['DriverNumber'].astype(str) == str(driver_num)]
            if not result.empty:
                return result
        except Exception:
            pass

    # 2. Direct filter by abbreviation (Driver column)
    try:
        result = laps_df[laps_df['Driver'].astype(str).str.upper() == driver_code]
        if not result.empty:
            return result
    except Exception:
        pass

    # 3. Fallback: pick_drivers with abbreviation
    try:
        result = laps_df.pick_drivers(driver_code)
        if result is not None and not result.empty:
            return result
    except Exception:
        pass

    # 4. Fallback: pick_drivers with number
    if driver_num:
        for num_val in [str(driver_num), int(driver_num) if driver_num.isdigit() else driver_num]:
            try:
                result = laps_df.pick_drivers(num_val)
                if result is not None and not result.empty:
                    return result
            except Exception:
                pass

    return laps_df.iloc[0:0]  # empty DataFrame


def _series_to_seconds(series: pd.Series) -> np.ndarray:
    """Convert a pandas Series of time-like values to a numpy array of seconds.

    Handles both Timedelta Series (.dt.total_seconds()) and Timestamp
    Series (converted via epoch) gracefully.
    """
    try:
        return series.dt.total_seconds().to_numpy()
    except AttributeError:
        # Fallback: Timestamp Series or mixed types
        return series.apply(lambda t: safe_to_seconds(t)).to_numpy()


def _process_single_driver(driver_no, session, driver_code, year: int, stype="R"):
    """Process telemetry data for a single driver.
    
    Returns None on failure — caller must handle gracefully.
    Wrapped in a top-level try/except so one driver failing
    never crashes the entire session processing.
    """
    # NOTE: runs sequentially — FastF1 session objects cannot be pickled.

    driver_num = get_driver_num_from_session(session, driver_code, year)
    if not driver_num:
        print(f"Driver {driver_code} not found for {year}, skipping")
        return None

    print(f"Getting telemetry for driver: {driver_code} (number={driver_num})")

    driver_laps = session.laps[
        session.laps['DriverNumber'].astype(str) == str(driver_num)
    ]
    if driver_laps.empty:
        print(f"No laps found for {driver_code} (#{driver_num}), skipping")
        return None
        
    laps_driver = driver_laps
    driver_no = driver_num

    # For qualifying: filter to quick laps but fall back to all laps
    if stype in ['Q', 'SQ', 'FP1', 'FP2', 'FP3']:
        try:
            quick = laps_driver.pick_quicklaps()
            if quick is not None and not quick.empty:
                laps_driver = quick
        except Exception:
            pass  # keep all laps if quicklaps fails
    try:
        year = int(session.event['EventDate'].year)
    except Exception:
        year = "unknown"

    if laps_driver is None or laps_driver.empty:
        print(f"No laps found for {driver_code} (#{driver_no})")
        return None

    try:
        driver_max_lap = laps_driver.LapNumber.max() if not laps_driver.empty else 0
    except Exception:
        driver_max_lap = 0

    t_all = []
    x_all = []
    y_all = []
    race_dist_all = []
    rel_dist_all = []
    lap_numbers = []
    tyre_compounds = []
    tyre_life_all = []
    speed_all = []
    gear_all = []
    drs_all = []
    throttle_all = []
    brake_all = []
    s1_all = []
    s2_all = []
    s3_all = []
    last_lap_all = []
    battery_pct_all = []
    ers_mode_all = []

    total_dist_so_far = 0.0
    logged_cols = False

    # iterate laps in order
    for _, lap in laps_driver.iterlaps():
        # get telemetry for THIS lap only
        try:
            lap_tel = lap.get_telemetry()
        except Exception as e:
            print(f"Skipping telemetry for driver {driver_code} lap {lap['LapNumber']}: {e}")
            continue
            
        try:
            lap_number = lap.get('LapNumber', 0)
        except Exception:
            lap_number = 0

        try:
            compound_val = lap.get('Compound', 'UNKNOWN')
            tyre_compund_as_int = get_tyre_compound_int(compound_val)
        except Exception:
            tyre_compund_as_int = 0

        try:
            lap_tl = lap.get('TyreLife')
            tyre_life = lap_tl if pd.notna(lap_tl) else 0
        except Exception:
            tyre_life = 0

        if lap_tel.empty:
            continue

        t_lap = lap_tel["SessionTime"].dt.total_seconds().to_numpy()
        x_lap = lap_tel["X"].to_numpy()
        y_lap = lap_tel["Y"].to_numpy()
        d_lap = lap_tel["Distance"].to_numpy()
        rd_lap = lap_tel["RelativeDistance"].to_numpy()
        speed_kph_lap = lap_tel["Speed"].to_numpy()
        gear_lap = lap_tel["nGear"].to_numpy()
        drs_lap = lap_tel["DRS"].to_numpy()
        throttle_lap = lap_tel["Throttle"].to_numpy()
        brake_lap = np.array([int(b) * 100 for b in lap_tel["Brake"].tolist()], dtype=int)

        # Sector times
        s1_time = safe_to_seconds(lap['Sector1Time']) if pd.notna(lap['Sector1Time']) else None
        s2_time = safe_to_seconds(lap['Sector2Time']) if pd.notna(lap['Sector2Time']) else None
        s3_time = safe_to_seconds(lap['Sector3Time']) if pd.notna(lap['Sector3Time']) else None

        s1_sess = lap['Sector1SessionTime']
        s2_sess = lap['Sector2SessionTime']
        s3_sess = lap['Sector3SessionTime']

        session_times = lap_tel["SessionTime"]

        # Fill with np.nan if not completed yet
        s1_arr = np.full(len(lap_tel), np.nan, dtype=float)
        s2_arr = np.full(len(lap_tel), np.nan, dtype=float)
        s3_arr = np.full(len(lap_tel), np.nan, dtype=float)
        last_lap_arr = np.full(len(lap_tel), np.nan, dtype=float)

        if s1_time is not None and pd.notna(s1_sess):
            s1_arr[session_times >= s1_sess] = s1_time
        if s2_time is not None and pd.notna(s2_sess):
            s2_arr[session_times >= s2_sess] = s2_time
        if s3_time is not None and pd.notna(s3_sess):
            s3_arr[session_times >= s3_sess] = s3_time
            lap_time_sec = lap.get('LapTime')
            if pd.notna(lap_time_sec):
                last_lap_arr[session_times >= s3_sess] = safe_to_seconds(lap_time_sec)

        # race distance = distance before this lap + distance within this lap
        race_d_lap = total_dist_so_far + d_lap

        t_all.append(t_lap)
        x_all.append(x_lap)
        y_all.append(y_lap)
        race_dist_all.append(race_d_lap)
        rel_dist_all.append(rd_lap)
        lap_numbers.append(np.full_like(t_lap, lap_number))
        tyre_compounds.append(np.full_like(t_lap, tyre_compund_as_int))
        tyre_life_all.append(np.full_like(t_lap, tyre_life))
        speed_all.append(speed_kph_lap)
        gear_all.append(gear_lap)
        drs_all.append(drs_lap)
        throttle_all.append(throttle_lap)
        brake_all.append(brake_lap)
        s1_all.append(s1_arr)
        s2_all.append(s2_arr)
        s3_all.append(s3_arr)
        last_lap_all.append(last_lap_arr)

        if not logged_cols:
            logging.info(f"Available car_data columns for {year}: {list(lap_tel.columns)}")
            logged_cols = True

        if "ErsStoreEnergy" in lap_tel.columns:
            battery_pct_all.append(lap_tel["ErsStoreEnergy"].to_numpy().astype(float) / 8500000.0 * 100.0)
        else:
            battery_pct_all.append(np.full(len(lap_tel), np.nan))

        if "ErsDeployMode" in lap_tel.columns:
            ers_mode_all.append(lap_tel["ErsDeployMode"].to_numpy())
        else:
            ers_mode_all.append(np.full(len(lap_tel), np.nan))

    if not t_all:
        return None

    # Concatenate all arrays at once for better performance
    all_arrays = [t_all, x_all, y_all, race_dist_all, rel_dist_all, 
                  lap_numbers, tyre_compounds, tyre_life_all, speed_all, gear_all, drs_all, s1_all, s2_all, s3_all, last_lap_all]
    
    t_all, x_all, y_all, race_dist_all, rel_dist_all, lap_numbers, \
    tyre_compounds, tyre_life_all, speed_all, gear_all, drs_all, s1_all, s2_all, s3_all, last_lap_all = [np.concatenate(arr) for arr in all_arrays]

    # Sort all arrays by time in one operation
    order = np.argsort(t_all)
    all_data = [t_all, x_all, y_all, race_dist_all, rel_dist_all, 
                lap_numbers, tyre_compounds, tyre_life_all, speed_all, gear_all, drs_all, s1_all, s2_all, s3_all, last_lap_all]
    
    t_all, x_all, y_all, race_dist_all, rel_dist_all, lap_numbers, \
    tyre_compounds, tyre_life_all, speed_all, gear_all, drs_all, s1_all, s2_all, s3_all, last_lap_all = [arr[order] for arr in all_data]

    throttle_all = np.concatenate(throttle_all)[order]
    brake_all = np.concatenate(brake_all)[order]
    battery_pct_all = np.concatenate(battery_pct_all)[order]
    ers_mode_all = np.concatenate(ers_mode_all)[order]

    print(f"Completed telemetry for driver: {driver_code}")

    return {
        "code": driver_code,
        "data": {
            "t": t_all,
            "x": x_all,
            "y": y_all,
            "dist": race_dist_all,
            "rel_dist": rel_dist_all,
            "lap": lap_numbers,
            "tyre": tyre_compounds,
            "tyre_life": tyre_life_all,
            "speed": speed_all,
            "gear": gear_all,
            "drs": drs_all,
            "throttle": throttle_all,
            "brake": brake_all,
            "sector1": s1_all,
            "sector2": s2_all,
            "sector3": s3_all,
            "last_lap_time": last_lap_all,
            "battery_pct": battery_pct_all,
            "ers_mode": ers_mode_all,
            "overtake_active": np.where(ers_mode_all == 2, True, False),
            "boost_active": np.where(ers_mode_all == 1, True, False),
        },
        "t_min": t_all.min(),
        "t_max": t_all.max(),
        "max_lap": driver_max_lap,
    }


def load_session(year, round_number, session_type="R"):
    # session_type: 'R' (Race), 'S' (Sprint) etc.
    session = fastf1.get_session(int(year), int(round_number), session_type)
    session.load(
        weather=True,
        messages=True,
        laps=True,
        telemetry=True
    )
    
    # Check car data availability AFTER load, safely
    try:
        has_car_data = session.car_data is not None and len(session.car_data) > 0
        if not has_car_data:
            print(f"WARNING: No car telemetry available for {year} R{round_number} {session_type}")
    except Exception:
        print(f"WARNING: Could not check car data for {year} R{round_number} {session_type}")
        
    return session


# The following functions require a loaded session object


TEAM_COLORS_BY_YEAR = {
    2022: {
        'Mercedes': '#00D2BE', 'Ferrari': '#DC0000',
        'Red Bull Racing': '#3671C6', 'Alpine': '#0090FF',
        'Haas F1 Team': '#FFFFFF', 'McLaren': '#FF8000',
        'Aston Martin': '#358C75', 'Williams': '#37BEDD',
        'AlphaTauri': '#2B4562', 'Alfa Romeo': '#C92D4B',
    },
    2023: {
        'Mercedes': '#00D2BE', 'Ferrari': '#E8002D',
        'Red Bull Racing': '#3671C6', 'Alpine': '#FF87BC',
        'Haas F1 Team': '#B6BABD', 'McLaren': '#FF8000',
        'Aston Martin': '#358C75', 'Williams': '#64C4FF',
        'AlphaTauri': '#3D5FA0', 'Alfa Romeo': '#C92D4B',
    },
    2024: {
        'Mercedes': '#27F4D2', 'Ferrari': '#E8002D',
        'Red Bull Racing': '#3671C6', 'Alpine': '#FF87BC',
        'Haas F1 Team': '#B6BABD', 'McLaren': '#FF8000',
        'Aston Martin': '#358C75', 'Williams': '#64C4FF',
        'RB': '#6692FF', 'Kick Sauber': '#52E252',
    },
    2025: {
        'Mercedes': '#27F4D2', 'Ferrari': '#E8002D',
        'Red Bull Racing': '#3671C6', 'Alpine': '#FF87BC',
        'Haas F1 Team': '#B6BABD', 'McLaren': '#FF8000',
        'Aston Martin': '#358C75', 'Williams': '#64C4FF',
        'Racing Bulls': '#6692FF', 'Kick Sauber': '#52E252',
    },
    2026: {
        'Mercedes': '#27F4D2', 'Ferrari': '#E8002D',
        'Red Bull Racing': '#3671C6', 'Alpine': '#FF87BC',
        'Haas F1 Team': '#B6BABD', 'McLaren': '#FF8000',
        'Aston Martin': '#358C75', 'Williams': '#64C4FF',
        'Racing Bulls': '#6692FF', 'Audi': '#B7191C',
        'Cadillac': '#CC0000',
    },
}

# (driver, team, start_round, end_round) per year
# Ground-effect era only (2022+)
DRIVER_STINTS = {
    2022: [
        # Mercedes
        ('HAM', 'Mercedes', 1, 22),
        ('RUS', 'Mercedes', 1, 22),
        # Red Bull
        ('VER', 'Red Bull Racing', 1, 22),
        ('PER', 'Red Bull Racing', 1, 22),
        # Ferrari
        ('LEC', 'Ferrari', 1, 22),
        ('SAI', 'Ferrari', 1, 22),
        # McLaren
        ('NOR', 'McLaren', 1, 22),
        ('RIC', 'McLaren', 1, 22),
        # Alpine
        ('ALO', 'Alpine', 1, 22),
        ('OCO', 'Alpine', 1, 22),
        # AlphaTauri
        ('GAS', 'AlphaTauri', 1, 22),
        ('TSU', 'AlphaTauri', 1, 22),
        # Aston Martin — VET missed R1-R2 (COVID), HUL substituted
        ('VET', 'Aston Martin', 3, 22),
        ('HUL', 'Aston Martin', 1, 2),
        ('STR', 'Aston Martin', 1, 22),
        # Williams — ALB missed R16 Italian GP (appendicitis), de Vries subbed
        ('ALB', 'Williams', 1, 15),
        ('DEV', 'Williams', 16, 16),
        ('ALB', 'Williams', 17, 22),
        ('LAT', 'Williams', 1, 22),
        # Alfa Romeo
        ('BOT', 'Alfa Romeo', 1, 22),
        ('ZHO', 'Alfa Romeo', 1, 22),
        # Haas
        ('MAG', 'Haas F1 Team', 1, 22),
        ('MSC', 'Haas F1 Team', 1, 22),
    ],

    2023: [
        # Mercedes
        ('HAM', 'Mercedes', 1, 22),
        ('RUS', 'Mercedes', 1, 22),
        # Red Bull
        ('VER', 'Red Bull Racing', 1, 22),
        ('PER', 'Red Bull Racing', 1, 22),
        # Ferrari
        ('LEC', 'Ferrari', 1, 22),
        ('SAI', 'Ferrari', 1, 22),
        # McLaren
        ('NOR', 'McLaren', 1, 22),
        ('PIA', 'McLaren', 1, 22),
        # Alpine
        ('GAS', 'Alpine', 1, 22),
        ('OCO', 'Alpine', 1, 22),
        # AlphaTauri — DEV replaced by RIC mid-season, LAW covered RIC injury
        ('DEV', 'AlphaTauri', 1, 10),
        ('RIC', 'AlphaTauri', 11, 12),
        ('LAW', 'AlphaTauri', 13, 17),  # covered RIC broken hand (Dutch-Qatar)
        ('RIC', 'AlphaTauri', 18, 22),
        ('TSU', 'AlphaTauri', 1, 22),
        # Aston Martin
        ('ALO', 'Aston Martin', 1, 22),
        ('STR', 'Aston Martin', 1, 22),
        # Williams
        ('ALB', 'Williams', 1, 22),
        ('SAR', 'Williams', 1, 22),
        # Alfa Romeo
        ('BOT', 'Alfa Romeo', 1, 22),
        ('ZHO', 'Alfa Romeo', 1, 22),
        # Haas
        ('MAG', 'Haas F1 Team', 1, 22),
        ('HUL', 'Haas F1 Team', 1, 22),
    ],

    2024: [
        # Mercedes
        ('HAM', 'Mercedes', 1, 24),
        ('RUS', 'Mercedes', 1, 24),
        # Red Bull
        ('VER', 'Red Bull Racing', 1, 24),
        ('PER', 'Red Bull Racing', 1, 24),
        # Ferrari
        ('LEC', 'Ferrari', 1, 24),
        ('SAI', 'Ferrari', 1, 24),
        # McLaren
        ('NOR', 'McLaren', 1, 24),
        ('PIA', 'McLaren', 1, 24),
        # Aston Martin
        ('ALO', 'Aston Martin', 1, 24),
        ('STR', 'Aston Martin', 1, 24),
        # Alpine
        ('GAS', 'Alpine', 1, 24),
        ('OCO', 'Alpine', 1, 20),
        ('DOO', 'Alpine', 21, 24),
        # RB (formerly AlphaTauri)
        ('TSU', 'RB', 1, 24),
        ('RIC', 'RB', 1, 18),
        ('LAW', 'RB', 19, 24),
        # Williams
        ('ALB', 'Williams', 1, 24),
        ('SAR', 'Williams', 1, 16),
        ('COO', 'Williams', 17, 24),  # Franco Colapinto
        # Kick Sauber
        ('BOT', 'Kick Sauber', 1, 24),
        ('ZHO', 'Kick Sauber', 1, 24),
        # Haas
        ('MAG', 'Haas F1 Team', 1, 19),
        ('HUL', 'Haas F1 Team', 1, 24),
        ('BEA', 'Haas F1 Team', 20, 24),
    ],

    2025: [
        # Red Bull — LAW replaced by TSU after R5
        ('VER', 'Red Bull Racing', 1, 24),
        ('LAW', 'Red Bull Racing', 1, 5),
        ('TSU', 'Red Bull Racing', 6, 24),
        # Racing Bulls — TSU moved up, LAW moved down, HAD full season
        ('TSU', 'Racing Bulls', 1, 5),
        ('LAW', 'Racing Bulls', 6, 24),
        ('HAD', 'Racing Bulls', 1, 24),
        # Ferrari
        ('LEC', 'Ferrari', 1, 24),
        ('HAM', 'Ferrari', 1, 24),
        # Mercedes
        ('RUS', 'Mercedes', 1, 24),
        ('ANT', 'Mercedes', 1, 24),
        # McLaren
        ('NOR', 'McLaren', 1, 24),
        ('PIA', 'McLaren', 1, 24),
        # Aston Martin
        ('ALO', 'Aston Martin', 1, 24),
        ('STR', 'Aston Martin', 1, 24),
        # Alpine — DOO replaced by COO after R4
        ('GAS', 'Alpine', 1, 24),
        ('DOO', 'Alpine', 1, 4),
        ('COO', 'Alpine', 5, 24),
        ('COL', 'Alpine', 1, 24),  # Colapinto full season at Alpine
        # Williams
        ('ALB', 'Williams', 1, 24),
        ('SAI', 'Williams', 1, 24),
        # Kick Sauber
        ('HUL', 'Kick Sauber', 1, 24),
        ('BOR', 'Kick Sauber', 1, 24),
        # Haas
        ('OCO', 'Haas F1 Team', 1, 24),
        ('BEA', 'Haas F1 Team', 1, 24),
    ],

    2026: [
        # Red Bull (22 rounds — Bahrain and Saudi cancelled)
        ('VER', 'Red Bull Racing', 1, 22),
        ('HAD', 'Red Bull Racing', 1, 22),
        # Ferrari
        ('LEC', 'Ferrari', 1, 22),
        ('HAM', 'Ferrari', 1, 22),
        # Mercedes
        ('RUS', 'Mercedes', 1, 22),
        ('ANT', 'Mercedes', 1, 22),
        # McLaren
        ('NOR', 'McLaren', 1, 22),
        ('PIA', 'McLaren', 1, 22),
        # Aston Martin
        ('ALO', 'Aston Martin', 1, 22),
        ('STR', 'Aston Martin', 1, 22),
        # Alpine (Mercedes customer engines from 2026)
        ('GAS', 'Alpine', 1, 22),
        ('COL', 'Alpine', 1, 22),
        # Williams
        ('ALB', 'Williams', 1, 22),
        ('SAI', 'Williams', 1, 22),
        # Racing Bulls — Tsunoda out, Lindblad in
        ('LAW', 'Racing Bulls', 1, 22),
        ('LIN', 'Racing Bulls', 1, 22),  # Arvid Lindblad, rookie
        # Audi (formerly Kick Sauber, works Audi power unit)
        ('HUL', 'Audi', 1, 22),
        ('BOR', 'Audi', 1, 22),
        # Haas
        ('OCO', 'Haas F1 Team', 1, 22),
        ('BEA', 'Haas F1 Team', 1, 22),
        # Cadillac (new 11th team, Ferrari customer engines until 2029)
        ('PER', 'Cadillac', 1, 22),
        ('BOT', 'Cadillac', 1, 22),
    ],
}

def get_driver_info(session) -> dict:
    try:
        year = int(session.event['EventDate'].year)
    except Exception:
        year = 2025

    try:
        round_number = int(session.event['RoundNumber'])
    except Exception:
        round_number = 1

    team_colors = TEAM_COLORS_BY_YEAR.get(year, TEAM_COLORS_BY_YEAR[2025])
    stints = DRIVER_STINTS.get(year, DRIVER_STINTS[2025])

    result = {}
    for driver in session.drivers:
        try:
            abbr = str(session.get_driver(driver)['Abbreviation']).strip()[:3].upper()
        except Exception:
            abbr = str(driver).strip()[:3].upper()

        try:
            team = ''
            for stint_abbr, stint_team, start_r, end_r in stints:
                if stint_abbr == abbr and start_r <= round_number <= end_r:
                    team = stint_team
                    break

            # Fallback 1: try nearest year's stints
            if not team:
                nearest_year = min(DRIVER_STINTS.keys(), key=lambda y: abs(y - year))
                fallback_stints = DRIVER_STINTS[nearest_year]
                for stint_abbr, stint_team, start_r, end_r in fallback_stints:
                    if stint_abbr == abbr:
                        team = stint_team
                        break

            # Fallback 2: search all years most recent first
            if not team:
                for search_year in sorted(DRIVER_STINTS.keys(), reverse=True):
                    for stint_abbr, stint_team, _, _ in DRIVER_STINTS[search_year]:
                        if stint_abbr == abbr:
                            team = stint_team
                            break
                    if team:
                        break

            # Fallback 3: white
            col = team_colors.get(team, '#FFFFFF') if team else '#FFFFFF'
            result[abbr] = {
                "color": col,
                "team": team if team else abbr
            }

        except Exception:
            result[abbr] = {
                "color": '#FFFFFF',
                "team": abbr
            }

    return result


def get_circuit_rotation(session):
    try:
        circuit = session.get_circuit_info()
        return circuit.rotation
    except Exception:
        return 0.0


def get_track_features(session) -> dict:
    """
    Extract sector boundary points and DRS zones with X/Y coordinates
    from session.get_circuit_info(), mapped via the fastest lap's
    position array (distance → closest X/Y point).

    Returns dict with keys: sector_points, drs_zones_xy
    Coordinates are normalised to 0-1 range.
    """
    try:
        fastest = session.laps.pick_fastest()
        if fastest is None or fastest.empty:
            raise ValueError("No fastest lap")
        tel = fastest.get_telemetry()
        x = tel["X"].to_numpy().astype(float)
        y = tel["Y"].to_numpy().astype(float)
        dist_arr = tel["Distance"].to_numpy().astype(float)
    except Exception:
        # Fall back to position data
        try:
            first_driver = list(session.pos_data.keys())[0]
            pos = session.pos_data[first_driver]
            x = np.array(pos['X'].dropna().values.tolist()).astype(float)
            y = np.array(pos['Y'].dropna().values.tolist()).astype(float)
            dist_arr = np.zeros(len(x))
            tel = None  # To skip sector times that need session time
        except Exception:
            return {"sector_points": [], "drs_zones_xy": [], "pit_entry": None, "pit_exit": None}

    # Normalise coordinates to 0-1
    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()
    x_range = (x_max - x_min) or 1.0
    y_range = (y_max - y_min) or 1.0

    def _dist_to_xy(distance: float) -> tuple:
        """Map a track distance to normalised (x, y)."""
        idx = int(np.argmin(np.abs(dist_arr - distance)))
        nx = round((float(x[idx]) - x_min) / x_range, 5)
        ny = round((float(y[idx]) - y_min) / y_range, 5)
        return nx, ny

    try:
        circuit_info = session.get_circuit_info()
    except Exception as e:
        print(f"[track] Could not get circuit info: {e}")
        circuit_info = None

    # ── Sector boundaries ─────────────────────────────────────────────
    sector_points = []
    if tel is not None:
        try:
            tel_session_times = tel["SessionTime"].dt.total_seconds().to_numpy()
            s1_sess = fastest.get("Sector1SessionTime")
            s2_sess = fastest.get("Sector2SessionTime")

            if pd.notna(s1_sess):
                s1_seconds = safe_to_seconds(s1_sess)
                s1_idx = int(np.argmin(np.abs(tel_session_times - s1_seconds)))
                sx = round((float(x[s1_idx]) - x_min) / x_range, 5)
                sy = round((float(y[s1_idx]) - y_min) / y_range, 5)
                sector_points.append({"sector": 1, "x": sx, "y": sy})

            if pd.notna(s2_sess):
                s2_seconds = safe_to_seconds(s2_sess)
                s2_idx = int(np.argmin(np.abs(tel_session_times - s2_seconds)))
                sx = round((float(x[s2_idx]) - x_min) / x_range, 5)
                sy = round((float(y[s2_idx]) - y_min) / y_range, 5)
                sector_points.append({"sector": 2, "x": sx, "y": sy})

            # Sector 3 = start/finish line (index 0)
            s3x = round((float(x[0]) - x_min) / x_range, 5)
            s3y = round((float(y[0]) - y_min) / y_range, 5)
            sector_points.append({"sector": 3, "x": s3x, "y": s3y})

        except Exception as e:
            print(f"[track] Could not extract sector points from lap data: {e}")

    # Fallback to 3 equal segments if sectors extraction failed or was incomplete
    if len(sector_points) < 3:
        total = len(x)
        sector_points = [
            {"sector": 1, "x": round((float(x[total//3]) - x_min) / x_range, 5), "y": round((float(y[total//3]) - y_min) / y_range, 5)},
            {"sector": 2, "x": round((float(x[2*total//3]) - x_min) / x_range, 5), "y": round((float(y[2*total//3]) - y_min) / y_range, 5)},
            {"sector": 3, "x": round((float(x[0]) - x_min) / x_range, 5), "y": round((float(y[0]) - y_min) / y_range, 5)}
        ]

    # ── DRS zones from circuit_info ───────────────────────────────────
    drs_zones_xy = []
    if circuit_info is not None:
        try:
            drs_df = getattr(circuit_info, "drs_zones", None)
            if drs_df is not None and not drs_df.empty:
                entry_col = None
                exit_col = None
                for col in drs_df.columns:
                    cl = col.lower()
                    if "entry" in cl and "distance" in cl:
                        entry_col = col
                    elif "exit" in cl and "distance" in cl:
                        exit_col = col

                if entry_col and exit_col:
                    for _, row in drs_df.iterrows():
                        e_dist = float(row[entry_col])
                        x_dist = float(row[exit_col])
                        sx, sy = _dist_to_xy(e_dist)
                        ex, ey = _dist_to_xy(x_dist)
                        drs_zones_xy.append({
                            "start_x": sx, "start_y": sy,
                            "end_x": ex, "end_y": ey,
                        })
        except Exception as e:
            print(f"[track] Could not extract DRS zone XY: {e}")

    # ── Pit Lane Approximation ────────────────────────────────────────
    try:
        pit_entry_idx = int(len(x) * 0.95)
        pit_exit_idx = int(len(x) * 0.02)
        pit_entry = { 'x': round((float(x[pit_entry_idx]) - x_min) / x_range, 5), 'y': round((float(y[pit_entry_idx]) - y_min) / y_range, 5) }
        pit_exit = { 'x': round((float(x[pit_exit_idx]) - x_min) / x_range, 5), 'y': round((float(y[pit_exit_idx]) - y_min) / y_range, 5) }
    except Exception as e:
        print(f"[track] Could not extract pit lane: {e}")
        pit_entry = None
        pit_exit = None

    print(f"Track data: {len(sector_points)} sectors, {len(drs_zones_xy)} zones")
    
    # Check for 2026 regulations
    try:
        year = int(session.event['EventDate'].year)
        if year >= 2026:
            return {
                "sector_points": sector_points,
                "straight_mode_zones": drs_zones_xy,
                "pit_entry": pit_entry,
                "pit_exit": pit_exit,
            }
    except:
        pass

    return {
        "sector_points": sector_points,
        "drs_zones_xy": drs_zones_xy,
        "pit_entry": pit_entry,
        "pit_exit": pit_exit,
    }


# ── Race control per-frame builder ─────────────────────────────────────

_TRACK_STATUS_TO_FLAG = {
    "1": "GREEN", "2": "YELLOW", "3": "SC_ENDING",
    "4": "SC", "5": "RED", "6": "VSC", "7": "SC_ENDING",
}


def _build_race_control_at(
    t: float,
    race_control_messages: list[dict],
    track_statuses: list[dict],
    flag_map: dict[str, str],
) -> dict:
    """Build the race_control block for a frame at time *t*.

    Returns dict with:
      - messages: list of recent RC messages (last 5 within 30s window)
      - current_flag: GREEN|YELLOW|SC|VSC|RED|SC_ENDING
      - sc_deployed: bool
      - vsc_deployed: bool
      - yellow_sectors: list[int] — sectors with active yellow flags
    """
    # Current flag from track_statuses
    current_flag = "GREEN"
    for s in track_statuses:
        if s["start_time"] <= t:
            end = s.get("end_time")
            if end is None or t < end:
                current_flag = _TRACK_STATUS_TO_FLAG.get(str(s["status"]), "GREEN")
        elif s["start_time"] > t:
            break

    sc_deployed = current_flag in ("SC", "SC_ENDING")
    vsc_deployed = current_flag in ("VSC",)

    # Recent race control messages (within last 30s, max 5)
    recent: list[dict] = []
    for msg in race_control_messages:
        msg_t = msg.get("time", 0)
        if msg_t <= t and (t - msg_t) < 30.0:
            recent.append({
                "time": msg["time"],
                "message": msg["message"],
                "flag": msg.get("flag", ""),
                "category": msg.get("category", ""),
            })
    recent = recent[-5:]  # Keep only the 5 most recent

    # Yellow sectors — find all sectors with active yellow flags at time t
    yellow_sectors: list[int] = []
    for msg in race_control_messages:
        msg_t = msg.get("time", 0)
        if msg_t > t:
            break
        flag = msg.get("flag", "")
        sector = msg.get("sector")
        scope = msg.get("scope", "")
        if sector and flag == "YELLOW" and scope == "Sector":
            sector_num = int(sector)
            if sector_num not in yellow_sectors:
                yellow_sectors.append(sector_num)
        elif flag == "CLEAR" and sector:
            sector_num = int(sector)
            if sector_num in yellow_sectors:
                yellow_sectors.remove(sector_num)
        elif flag in ("GREEN", "") and not sector:
            # Global green clears all sector yellows
            if current_flag == "GREEN":
                yellow_sectors.clear()

    return {
        "messages": recent,
        "current_flag": current_flag,
        "sc_deployed": sc_deployed,
        "vsc_deployed": vsc_deployed,
        "yellow_sectors": sorted(yellow_sectors),
    }


def get_race_telemetry(session, session_type="R", progress_cb: ProgressCallback = None):
    event_name = str(session).replace(" ", "_")
    cache_suffix = "sprint" if session_type == "S" else "race"
    
    try:
        year = int(session.event['EventDate'].year)
    except Exception:
        year = 2025

    drivers = session.drivers

    # Build driver number → code map dynamically from session data.
    # Each lookup is guarded so one unknown driver doesn't crash everything.
    driver_codes = {}
    for num in drivers:
        try:
            drv = session.get_driver(num)
            driver_codes[num] = str(drv["Abbreviation"]).strip()[:3].upper()
        except Exception as e:
            print(f"WARNING: Could not resolve driver number {num}: {e}")
            driver_codes[num] = str(num).strip()[:3].upper()  # fallback: use number as code

    driver_data = {}

    global_t_min = None
    global_t_max = None

    max_lap_number = 0

    # 1. Process each driver's telemetry sequentially
    #    (FastF1 session objects cannot be pickled, so multiprocessing is not viable)
    total_drivers = len(drivers)
    print(f"Processing {total_drivers} drivers sequentially...")

    results = []
    for idx, driver_no in enumerate(drivers, start=1):
        code = driver_codes[driver_no]
        try:
            result = _process_single_driver(driver_no, session, code, year, session_type)
        except Exception as e:
            print(f"ERROR: _process_single_driver failed for {code} (#{driver_no}): {e}")
            result = None
        results.append(result)
        print(f"[cache] Completed {code} ({idx}/{total_drivers})")
        if progress_cb:
            progress_cb(int(50 + (idx / total_drivers) * 40))

    # Process results
    for result in results:
        if result is None:
            continue

        code = result["code"]
        driver_data[code] = result["data"]

        t_min = result["t_min"]
        t_max = result["t_max"]
        max_lap_number = max(max_lap_number, result["max_lap"])

        global_t_min = t_min if global_t_min is None else min(global_t_min, t_min)
        global_t_max = t_max if global_t_max is None else max(global_t_max, t_max)

    # Ensure we have valid time bounds
    if global_t_min is None or global_t_max is None:
        raise ValueError("No valid telemetry data found for any driver")

    # 2. Create a timeline (start from zero)
    timeline = np.arange(global_t_min, global_t_max, DT) - global_t_min

    # 3. Resample each driver's telemetry (x, y, gap) onto the common timeline
    resampled_data = {}
    max_tyre_life_map = {}

    for code, data in driver_data.items():
        t = data["t"] - global_t_min  # Shift

        # ensure sorted by time
        order = np.argsort(t)
        t_sorted = t[order]

        # Vectorize all resampling in one operation for speed
        arrays_to_resample = [
            data["x"][order],
            data["y"][order],
            data["dist"][order],
            data["rel_dist"][order],
            data["lap"][order],
            data["tyre"][order],
            data["tyre_life"][order],
            data["speed"][order],
            data["gear"][order],
            data["drs"][order],
            data["throttle"][order],
            data["brake"][order],
        ]

        resampled = [np.interp(timeline, t_sorted, arr) for arr in arrays_to_resample]
        x_resampled, y_resampled, dist_resampled, rel_dist_resampled, lap_resampled, \
        tyre_resampled, tyre_life_resampled, speed_resampled, gear_resampled, drs_resampled, throttle_resampled, brake_resampled = resampled

        # Discrete fields with NaN forward-fill logic wrapper
        idxs = np.searchsorted(t_sorted, timeline, side="right") - 1
        idxs = np.clip(idxs, 0, len(t_sorted) - 1)
        
        s1_resampled = data["sector1"][idxs]
        s2_resampled = data["sector2"][idxs]
        s3_resampled = data["sector3"][idxs]

        resampled_data[code] = {
            "t": timeline,
            "x": x_resampled,
            "y": y_resampled,
            "dist": dist_resampled,  # race distance (metres since Lap 1 start)
            "rel_dist": rel_dist_resampled,
            "lap": lap_resampled,
            "tyre": tyre_resampled,
            "tyre_life": tyre_life_resampled,
            "speed": speed_resampled,
            "gear": gear_resampled,
            "drs": drs_resampled,
            "throttle": throttle_resampled,
            "brake": brake_resampled,
            "sector1": s1_resampled,
            "sector2": s2_resampled,
            "sector3": s3_resampled,
        }

        for t_int in np.unique(tyre_resampled):
            mask = tyre_resampled == t_int
            c_max = np.nanmax(tyre_life_resampled[mask])
            if not np.isnan(c_max):
                max_tyre_life_map[int(t_int)] = max(max_tyre_life_map.get(int(t_int), 1), int(c_max))

    # 4. Incorporate track status data into the timeline (for safety car, VSC, etc.)

    try:
        track_status = session.track_status
    except Exception:
        track_status = pd.DataFrame()

    formatted_track_statuses = []

    if not track_status.empty:
        for status in track_status.to_dict("records"):
            seconds = safe_to_seconds(status["Time"])

            start_time = seconds - global_t_min  # Shift to match timeline
            end_time = None

            # Set the end time of the previous status

            if formatted_track_statuses:
                formatted_track_statuses[-1]["end_time"] = start_time

            formatted_track_statuses.append(
                {
                    "status": status["Status"],
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
    # 4.1. Extract race control messages (Race Director)
    #       FastF1 columns: Time, Category, Message, Flag, Scope, Sector, RacingNumber
    _RC_FLAG_MAP = {
        "1": "GREEN", "2": "YELLOW", "4": "SC", "5": "RED",
        "6": "VSC", "7": "SC_ENDING", "3": "SC_ENDING",
    }
    race_control_messages: list[dict] = []
    try:
        try:
            rcm_df = session.race_control_messages
        except Exception:
            rcm_df = getattr(session, "race_control_messages", None)
            
        if rcm_df is not None and not rcm_df.empty:
            for _, rc_row in rcm_df.iterrows():
                rc_msg = str(rc_row.get("Message", ""))
                if not rc_msg or rc_msg == "nan":
                    continue

                rc_time = rc_row.get("Time")
                if pd.isna(rc_time):
                    continue

                if hasattr(rc_time, 'total_seconds'):
                    rc_seconds = rc_time.total_seconds()
                else:
                    try:
                        rc_seconds = safe_to_seconds(rc_time) - global_t_min
                    except Exception:
                        continue
                        
                rc_category = str(rc_row.get("Category", ""))
                rc_driver = str(rc_row.get("RacingNumber", ""))
                if rc_driver in ("nan", "None", "0"):
                    rc_driver = ""

                entry = {
                    "time": round(rc_seconds, 3),
                    "message": rc_msg,
                    "category": rc_category,
                }
                
                if rc_driver:
                    entry["racing_number"] = rc_driver
                    
                rc_scope = str(rc_row.get("Scope", ""))
                if rc_scope and rc_scope != "nan":
                    entry["scope"] = rc_scope
                    
                rc_flag = str(rc_row.get("Flag", ""))
                if rc_flag and rc_flag != "nan":
                    entry["flag"] = rc_flag

                rc_sector = rc_row.get("Sector")
                if not pd.isna(rc_sector):
                    try:
                        entry["sector"] = int(rc_sector)
                    except (ValueError, TypeError):
                        pass

                rc_lap = rc_row.get("Lap")
                if not pd.isna(rc_lap):
                    try:
                        entry["lap"] = int(rc_lap)
                    except (ValueError, TypeError):
                        pass

                race_control_messages.append(entry)
            
            race_control_messages.sort(key=lambda e: e["time"])
            print(f"[race_control] Extracted {len(race_control_messages)} race control messages")
    except Exception as e:
        print(f"[race_control] Could not extract race control messages: {e}")

    # 4.2. Pre-compute nearest weather data per frame for playback
    weather_resampled = None
    try:
        weather_df = session.weather_data
    except Exception:
        weather_df = getattr(session, "weather_data", None)

    if weather_df is not None and not weather_df.empty:
        try:
            weather_times = weather_df["Time"].dt.total_seconds().to_numpy() - global_t_min
            weather_idx = np.abs(weather_times.reshape(-1, 1) - timeline).argmin(axis=0)

            track_temps = weather_df["TrackTemp"].to_numpy()
            air_temps = weather_df["AirTemp"].to_numpy()
            humidities = weather_df["Humidity"].to_numpy()
            wind_speeds = weather_df["WindSpeed"].to_numpy()
            wind_dirs = weather_df["WindDirection"].to_numpy()
            rainfalls = weather_df.get("Rainfall", pd.Series(np.zeros(len(weather_df)))).to_numpy()

            weather_resampled = {
                "track_temp": track_temps[weather_idx],
                "air_temp": air_temps[weather_idx],
                "humidity": humidities[weather_idx],
                "wind_speed": wind_speeds[weather_idx],
                "wind_direction": wind_dirs[weather_idx],
                "rainfall": rainfalls[weather_idx],
            }
        except Exception as e:
            print(f"Weather data could not be processed: {e}")
            weather_resampled = None

    # 5. Pre-compute pit stop / tyre history / grid position data
    #    These are per-driver static or lap-indexed lookups.

    # Grid positions from session results
    grid_positions: dict[str, int] = {}
    try:
        if session.results is not None and not session.results.empty:
            for _, row in session.results.iterrows():
                code = str(row.get("Abbreviation", "")).strip()[:3].upper()
                gp = row.get("GridPosition")
                if code and pd.notna(gp):
                    grid_positions[code] = int(gp)
    except Exception:
        pass

    # Per-driver: build a list of (start_lap, compound_str) stints
    # from the laps DataFrame.  This lets us compute pit_count and
    # tyre_history at any frame by comparing current lap.
    driver_stints_map: dict[str, list[dict]] = {}  # code -> [{"start_lap": int, "compound": str}]
    for code in resampled_data:
        try:
            # Try abbreviation first, fallback to resolved number
            _stint_num = get_driver_num_from_session(session, code, year)
            dlaps = _pick_driver_laps(session.laps, code, _stint_num)
            if dlaps is None or dlaps.empty:
                driver_stints_map[code] = []
                continue
            stints: list[dict] = []
            prev_compound = None
            for _, lap_row in dlaps.iterrows():
                compound = str(lap_row.get("Compound", "UNKNOWN"))
                if compound != prev_compound:
                    stints.append({"start_lap": int(lap_row["LapNumber"]), "compound": compound})
                    prev_compound = compound
            driver_stints_map[code] = stints
        except Exception:
            driver_stints_map[code] = []

    # 5b. Build the frames + LIVE LEADERBOARD
    frames = []
    num_frames = len(timeline)

    # Pre-extract data references for faster access
    driver_codes = list(resampled_data.keys())
    driver_arrays = {code: resampled_data[code] for code in driver_codes}

    for i in range(num_frames):
        t = timeline[i]
        snapshot = []
        for code in driver_codes:
            d = driver_arrays[code]
            snapshot.append({
                "code": code,
                "dist": float(d["dist"][i]),
                "x": float(d["x"][i]),
                "y": float(d["y"][i]),
                "lap": int(round(d["lap"][i])),
                "rel_dist": float(d["rel_dist"][i]),
                "tyre": float(d["tyre"][i]),
                "tyre_life": float(d["tyre_life"][i]),
                "speed": float(d['speed'][i]),
                "gear": int(d['gear'][i]),
                "drs": int(d['drs'][i]),
                "throttle": float(d['throttle'][i]),
                "brake": int(d['brake'][i]),
                "sector1": None if np.isnan(d['sector1'][i]) else float(d['sector1'][i]),
                "sector2": None if np.isnan(d['sector2'][i]) else float(d['sector2'][i]),
                "sector3": None if np.isnan(d['sector3'][i]) else float(d['sector3'][i]),
            })

        # If for some reason we have no drivers at this instant
        if not snapshot:
            continue

        # Sort by race distance to get POSITIONS (1–20)
        # Leader = largest race distance covered
        snapshot.sort(key=lambda r: (r.get("lap", 0), r["dist"]), reverse=True)

        leader = snapshot[0]
        leader_lap = leader["lap"]
        leader_dist = leader["dist"]
        leader_speed = max(leader["speed"], 1.0)  # avoid div-by-zero (km/h → m/s)
        leader_speed_ms = leader_speed / 3.6

        # Compute gap/interval + new fields
        frame_data = {}

        for idx, car in enumerate(snapshot):
            code = car["code"]
            position = idx + 1
            cur_lap = car["lap"]

            # gap_to_leader: distance deficit / leader speed
            if position == 1:
                gap_to_leader = 0.0
            else:
                dist_delta = leader_dist - car["dist"]
                gap_to_leader = round(max(0.0, dist_delta / leader_speed_ms), 3)

            # interval: gap to car directly ahead
            if position == 1:
                interval = 0.0
            else:
                ahead = snapshot[idx - 1]
                ahead_speed_ms = max(ahead["speed"], 1.0) / 3.6
                dist_to_ahead = ahead["dist"] - car["dist"]
                interval = round(max(0.0, dist_to_ahead / ahead_speed_ms), 3)

            # tyre_history + pit_count from precomputed stints
            stints = driver_stints_map.get(code, [])
            past_compounds: list[str] = []
            pit_count = 0
            if stints:
                for si, stint in enumerate(stints):
                    if stint["start_lap"] <= cur_lap:
                        if si > 0:
                            pit_count += 1
                            # Record the compound of the PREVIOUS stint
                            past_compounds.append(stints[si - 1]["compound"][0])  # first char: S, M, H, I, W
                    else:
                        break

            frame_data[code] = {
                "x": car["x"],
                "y": car["y"],
                "dist": car["dist"],
                "lap": car["lap"],
                "rel_dist": round(car["rel_dist"], 4),
                "tyre": car["tyre"],
                "tyre_life": car["tyre_life"],
                "position": position,
                "speed": car["speed"],
                "gear": car["gear"],
                "drs": car["drs"],
                "throttle": car["throttle"],
                "brake": car["brake"],
                "sector1": car["sector1"],
                "sector2": car["sector2"],
                "sector3": car["sector3"],
                "gap_to_leader": gap_to_leader,
                "interval": interval,
                "tyre_history": past_compounds,
                "pit_count": pit_count,
                "grid_position": grid_positions.get(code),
                "under_investigation": False,
            }

        weather_snapshot = {}
        if weather_resampled:
            try:
                wt = weather_resampled
                rain_val = wt["rainfall"][i]
                weather_snapshot = {
                    "track_temp": float(wt["track_temp"][i]) if pd.notna(wt["track_temp"][i]) else None,
                    "air_temp": float(wt["air_temp"][i]) if pd.notna(wt["air_temp"][i]) else None,
                    "humidity": float(wt["humidity"][i]) if pd.notna(wt["humidity"][i]) else None,
                    "wind_speed": float(wt["wind_speed"][i]) if pd.notna(wt["wind_speed"][i]) else None,
                    "wind_direction": float(wt["wind_direction"][i]) if pd.notna(wt["wind_direction"][i]) else None,
                    "rain_state": "RAINING" if rain_val and float(rain_val) >= 0.5 else "DRY",
                }
            except Exception as e:
                print(f"Failed to attach weather data to frame {i}: {e}")

        # Race control block for this frame timestamp
        rc_block = _build_race_control_at(t, race_control_messages, formatted_track_statuses, _RC_FLAG_MAP)

        frame_payload = {
            "t": round(t, 3),
            "lap": leader_lap,  # leader's lap at this time
            "drivers": frame_data,
            "race_control": rc_block,
        }
        if weather_snapshot:
            frame_payload["weather"] = weather_snapshot

        frames.append(frame_payload)
    print("completed telemetry extraction...")

    result = {
        "frames": frames,
        "driver_info": get_driver_info(session),
        "track_statuses": formatted_track_statuses,
        "race_control_messages": race_control_messages,
        "total_laps": int(max_lap_number),
        "max_tyre_life": max_tyre_life_map,
    }

    print("The replay should begin in a new window shortly")
    return result


def get_qualifying_results(session):
    # Extract the qualifying results and return a list of the drivers, their positions and their lap times in each qualifying segment

    results = session.results

    qualifying_data = []

    for _, row in results.iterrows():
        driver_code = str(row["Abbreviation"]).strip()[:3].upper()
        # Skip drivers with no position (DNF/DNS/no lap data)
        if pd.isna(row["Position"]):
            continue
        position = int(row["Position"])
        q1_time = row["Q1"]
        q2_time = row["Q2"]
        q3_time = row["Q3"]
        full_name = row["FullName"]

        def convert_time_to_seconds(time_val) -> str:
            if pd.isna(time_val):
                return None
            return str(safe_to_seconds(time_val))

        qualifying_data.append(
            {
                "code": driver_code,
                "full_name": full_name,
                "position": position,
                "color": get_driver_info(session).get(driver_code, {}).get("color", "#808080"),
                "Q1": convert_time_to_seconds(q1_time),
                "Q2": convert_time_to_seconds(q2_time),
                "Q3": convert_time_to_seconds(q3_time),
            }
        )
    return qualifying_data


def get_driver_quali_telemetry(session, driver_code: str, quali_segment: str):
    # Split Q1/Q2/Q3 sections
    q1, q2, q3 = session.laps.split_qualifying_sessions()

    segments = {"Q1": q1, "Q2": q2, "Q3": q3}

    # Validate the segment
    if quali_segment not in segments:
        raise ValueError("quali_segment must be 'Q1', 'Q2', or 'Q3'")

    segment_laps = segments[quali_segment]
    if segment_laps is None:
        raise ValueError(f"{quali_segment} does not exist for this session.")

    # Robust driver lookup using helper
    try:
        year = int(session.event['EventDate'].year)
    except Exception:
        year = 2025
    _quali_num = get_driver_num_from_session(session, driver_code, year)
    driver_laps = _pick_driver_laps(segment_laps, driver_code, _quali_num)
    if driver_laps is None or driver_laps.empty:
        raise ValueError(f"No laps found for driver '{driver_code}' in {quali_segment}")

    # Pick fastest lap
    fastest_lap = driver_laps.pick_fastest()

    # Extract telemetry with xyz coordinates

    if fastest_lap is None:
        raise ValueError(f"No valid laps for driver '{driver_code}' in {quali_segment}")

    try:
        telemetry = fastest_lap.get_telemetry()
    except Exception as e:
        print(f"Telemetry unavailable for {driver_code} in {quali_segment}: {e}")
        return {"frames": [], "track_statuses": []}

    # Guard: if telemetry has no time data, return empty
    if (
        telemetry is None
        or telemetry.empty
        or "Time" not in telemetry
        or len(telemetry) == 0
    ):
        return {"frames": [], "track_statuses": []}

    global_t_min = telemetry["Time"].dt.total_seconds().min()
    global_t_max = telemetry["Time"].dt.total_seconds().max()

    max_speed = telemetry["Speed"].max()
    min_speed = telemetry["Speed"].min()

    # An array of objects containing the start and end disances of each time the driver used DRS during the lap
    lap_drs_zones = []

    # Build arrays directly from dataframes
    t_arr = telemetry["Time"].dt.total_seconds().to_numpy()
    x_arr = telemetry["X"].to_numpy()
    y_arr = telemetry["Y"].to_numpy()
    dist_arr = telemetry["Distance"].to_numpy()
    rel_dist_arr = telemetry["RelativeDistance"].to_numpy()
    speed_arr = telemetry["Speed"].to_numpy()
    gear_arr = telemetry["nGear"].to_numpy()
    throttle_arr = telemetry["Throttle"].to_numpy()
    brake_arr = (telemetry["Brake"].to_numpy() * 100).round().astype(int)
    drs_arr = telemetry["DRS"].to_numpy()

    # Recompute time bounds from the (possibly modified) telemetry times
    global_t_min = float(t_arr.min())
    global_t_max = float(t_arr.max())

    # Create timeline (relative times starting at zero) and include endpoint
    timeline = np.arange(global_t_min, global_t_max + DT / 2, DT) - global_t_min

    # Ensure we have at least one sample
    if t_arr.size == 0:
        return {"frames": [], "track_statuses": []}

    # Shift telemetry times to same reference as timeline (relative to global_t_min)
    t_rel = t_arr - global_t_min

    # Sort & deduplicate times using the relative times
    order = np.argsort(t_rel)
    t_sorted = t_rel[order]
    t_sorted_unique, unique_idx = np.unique(t_sorted, return_index=True)
    idx_map = order[unique_idx]

    x_sorted = x_arr[idx_map]
    y_sorted = y_arr[idx_map]
    dist_sorted = dist_arr[idx_map]
    rel_dist_sorted = rel_dist_arr[idx_map]
    speed_sorted = speed_arr[idx_map]
    gear_sorted = gear_arr[idx_map]
    throttle_sorted = throttle_arr[idx_map]
    brake_sorted = brake_arr[idx_map]
    drs_sorted = drs_arr[idx_map]

    # Continuous interpolation
    x_resampled = np.interp(timeline, t_sorted_unique, x_sorted)
    y_resampled = np.interp(timeline, t_sorted_unique, y_sorted)
    dist_resampled = np.interp(timeline, t_sorted_unique, dist_sorted)
    rel_dist_resampled = np.interp(timeline, t_sorted_unique, rel_dist_sorted)
    speed_resampled = np.round(np.interp(timeline, t_sorted_unique, speed_sorted), 1)
    throttle_resampled = np.round(
        np.interp(timeline, t_sorted_unique, throttle_sorted), 1
    )
    brake_resampled = np.interp(timeline, t_sorted_unique, brake_sorted).round().astype(int)
    drs_resampled = np.interp(timeline, t_sorted_unique, drs_sorted)

    # Forward-fill / step sampling for discrete fields (gear)
    idxs = np.searchsorted(t_sorted_unique, timeline, side="right") - 1
    idxs = np.clip(idxs, 0, len(t_sorted_unique) - 1)
    gear_resampled = gear_sorted[idxs].astype(int)

    resampled_data = {
        "t": timeline,
        "x": x_resampled,
        "y": y_resampled,
        "dist": dist_resampled,
        "rel_dist": rel_dist_resampled,
        "speed": speed_resampled,
        "gear": gear_resampled,
        "throttle": throttle_resampled,
        "brake": brake_resampled,
        "drs": drs_resampled,
    }

    try:
        track_status = session.track_status
    except Exception:
        track_status = pd.DataFrame()

    formatted_track_statuses = []

    if not track_status.empty:
        for status in track_status.to_dict("records"):
            seconds = timedelta.total_seconds(status["Time"])

            start_time = seconds - global_t_min  # Shift to match timeline
            end_time = None

            # Set the end time of the previous status
            if formatted_track_statuses:
                formatted_track_statuses[-1]["end_time"] = start_time

            formatted_track_statuses.append(
                {
                    "status": status["Status"],
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )

    # 4.1. Pre-compute nearest weather data per frame for playback
    weather_resampled = []
    try:
        weather_df = session.weather_data
    except Exception:
        weather_df = getattr(session, "weather_data", None)
        
    if weather_df is not None and not weather_df.empty:
        try:
            weather_times = weather_df["Time"].dt.total_seconds().to_numpy() - global_t_min
            weather_idx = np.abs(weather_times.reshape(-1, 1) - timeline).argmin(axis=0)

            track_temps = weather_df["TrackTemp"].to_numpy()
            air_temps = weather_df["AirTemp"].to_numpy()
            humidities = weather_df["Humidity"].to_numpy()
            wind_speeds = weather_df["WindSpeed"].to_numpy()
            wind_dirs = weather_df["WindDirection"].to_numpy()
            rainfalls = weather_df.get("Rainfall", pd.Series(np.zeros(len(weather_df)))).to_numpy()

            weather_resampled = {
                "track_temp": track_temps[weather_idx],
                "air_temp": air_temps[weather_idx],
                "humidity": humidities[weather_idx],
                "wind_speed": wind_speeds[weather_idx],
                "wind_direction": wind_dirs[weather_idx],
                "rainfall": rainfalls[weather_idx],
            }
        except Exception as e:
            print(f"Weather data could not be processed: {e}")
            weather_resampled = None

    # Build the frames
    frames = []
    num_frames = len(timeline)

    for i in range(num_frames):
        t = timeline[i]

        weather_snapshot = {}
        if weather_resampled:
            try:
                wt = weather_resampled
                rain_val = wt["rainfall"][i]
                weather_snapshot = {
                    "track_temp": float(wt["track_temp"][i]) if pd.notna(wt["track_temp"][i]) else None,
                    "air_temp": float(wt["air_temp"][i]) if pd.notna(wt["air_temp"][i]) else None,
                    "humidity": float(wt["humidity"][i]) if pd.notna(wt["humidity"][i]) else None,
                    "wind_speed": float(wt["wind_speed"][i]) if pd.notna(wt["wind_speed"][i]) else None,
                    "wind_direction": float(wt["wind_direction"][i]) if pd.notna(wt["wind_direction"][i]) else None,
                    "rain_state": "RAINING" if rain_val and float(rain_val) >= 0.5 else "DRY",
                }
            except Exception as e:
                print(f"Failed to attach weather data to frame {i}: {e}")

        # Check if drs has changed from the previous frame

        if i > 0:
            drs_prev = resampled_data["drs"][i - 1]
            drs_curr = resampled_data["drs"][i]

            if (drs_curr >= 10) and (drs_prev < 10):
                # DRS activated
                lap_drs_zones.append(
                    {
                        "zone_start": float(resampled_data["dist"][i]),
                        "zone_end": None,
                    }
                )
            elif (drs_curr < 10) and (drs_prev >= 10):
                # DRS deactivated
                if lap_drs_zones and lap_drs_zones[-1]["zone_end"] is None:
                    lap_drs_zones[-1]["zone_end"] = float(resampled_data["dist"][i])

        frame_payload = {
            "t": round(t, 3),
            "telemetry": {
                "x": float(resampled_data["x"][i]),
                "y": float(resampled_data["y"][i]),
                "dist": float(resampled_data["dist"][i]),
                "rel_dist": float(resampled_data["rel_dist"][i]),
                "speed": float(resampled_data["speed"][i]),
                "gear": int(resampled_data["gear"][i]),
                "throttle": float(resampled_data["throttle"][i]),
                "brake": float(resampled_data["brake"][i]),
                "drs": int(resampled_data["drs"][i]),
            },
        }
        if weather_snapshot:
            frame_payload["weather"] = weather_snapshot

        frames.append(frame_payload)

    # Set the time of the final frame to the exact lap time

    frames[-1]["t"] = round(parse_time_string(str(fastest_lap["LapTime"])), 3)

    sector_times = {
        "sector1": parse_time_string(str(fastest_lap.get("Sector1Time")))
        if pd.notna(fastest_lap.get("Sector1Time"))
        else None,
        "sector2": parse_time_string(str(fastest_lap.get("Sector2Time")))
        if pd.notna(fastest_lap.get("Sector2Time"))
        else None,
        "sector3": parse_time_string(str(fastest_lap.get("Sector3Time")))
        if pd.notna(fastest_lap.get("Sector3Time"))
        else None,
    }

    # Extract tyre compound from the lap
    compound = (
        str(fastest_lap.get("Compound", "UNKNOWN"))
        if pd.notna(fastest_lap.get("Compound"))
        else "UNKNOWN"
    )
    compound_number = get_tyre_compound_int(compound)
    return {
        "frames": frames,
        "track_statuses": formatted_track_statuses,
        "drs_zones": lap_drs_zones,
        "max_speed": max_speed,
        "min_speed": min_speed,
        "sector_times": sector_times,
        "compound": compound_number,
    }


def _process_quali_driver(session, driver_code):
    """Process qualifying telemetry data for a single driver.
    
    Returns None on complete failure — caller must handle gracefully.
    """
    # NOTE: runs sequentially — FastF1 session objects cannot be pickled.
    print(f"Getting qualifying telemetry for driver: {driver_code}")

    driver_telemetry_data = {}

    max_speed = 0.0
    min_speed = 0.0

    for segment in ["Q1", "Q2", "Q3"]:
        try:
            segment_telemetry = get_driver_quali_telemetry(
                session, driver_code, segment
            )
            driver_telemetry_data[segment] = segment_telemetry

            # Update global max/min speed
            if segment_telemetry["max_speed"] > max_speed:
                max_speed = segment_telemetry["max_speed"]
            if segment_telemetry["min_speed"] < min_speed or min_speed == 0.0:
                min_speed = segment_telemetry["min_speed"]

        except (ValueError, Exception) as e:
            print(f"Segment {segment} failed for {driver_code}: {e}")
            driver_telemetry_data[segment] = {"frames": [], "track_statuses": []}

    # Resolve full name safely
    driver_full_name = driver_code
    try:
        driver_full_name = session.get_driver(driver_code)["FullName"]
    except Exception:
        pass

    print(
        f"Finished processing qualifying telemetry for driver: {driver_code}, {driver_full_name}"
    )
    return {
        "driver_code": driver_code,
        "driver_full_name": driver_full_name,
        "driver_telemetry_data": driver_telemetry_data,
        "max_speed": max_speed,
        "min_speed": min_speed,
    }


def get_quali_telemetry(session, session_type="Q", progress_cb: ProgressCallback = None):
    # Get results from qualifying and the telemetry for each driver's fastest laps

    event_name = str(session).replace(" ", "_")
    cache_suffix = "sprintquali" if session_type == "SQ" else "quali"

    qualifying_results = get_qualifying_results(session)

    telemetry_data = {}

    max_speed = 0.0
    min_speed = 0.0

    # Build driver number → code map dynamically with per-driver error handling
    driver_codes = {}
    for num in session.drivers:
        try:
            drv = session.get_driver(num)
            driver_codes[num] = str(drv["Abbreviation"]).strip()[:3].upper()
        except Exception as e:
            print(f"WARNING: Could not resolve driver number {num} in quali: {e}")
            driver_codes[num] = str(num).strip()[:3].upper()

    telemetry_data = {}

    # Process each driver sequentially
    #    (FastF1 session objects cannot be pickled, so multiprocessing is not viable)
    total_drivers = len(session.drivers)
    print(f"Processing {total_drivers} drivers sequentially...")

    results = []
    for idx, driver_no in enumerate(session.drivers, start=1):
        code = driver_codes[driver_no]
        try:
            result = _process_quali_driver(session, code)
        except Exception as e:
            print(f"ERROR: _process_quali_driver failed for {code} (#{driver_no}): {e}")
            result = None
        results.append(result)
        print(f"[cache] Completed {code} ({idx}/{total_drivers})")
        if progress_cb:
            progress_cb(int(50 + (idx / total_drivers) * 40))

    for result in results:
        if result is None:
            continue
        driver_code = result["driver_code"]
        telemetry_data[driver_code] = {
            "full_name": result["driver_full_name"],
            **result["driver_telemetry_data"],
        }

        if result["max_speed"] > max_speed:
            max_speed = result["max_speed"]
        if result["min_speed"] < min_speed or min_speed == 0.0:
            min_speed = result["min_speed"]

    result = {
        "results": qualifying_results,
        "telemetry": telemetry_data,
        "max_speed": max_speed,
        "min_speed": min_speed,
    }

    return result


def get_race_weekends_by_year(year):
    """Returns a list of race weekends for a given year."""
    enable_cache()
    schedule = fastf1.get_event_schedule(int(year))
    weekends = []
    for _, event in schedule.iterrows():
        if event.is_testing():
            continue

        session_dates = {}
        for i in range(1, 6):
            session_name = event.get(f"Session{i}")
            session_date = event.get(f"Session{i}Date")
            if session_name and pd.notna(session_date):
                session_dates[str(session_name)] = session_date.isoformat()

        weekends.append(
            {
                "round_number": event["RoundNumber"],
                "event_name": event["EventName"],
                "date": str(event["EventDate"].date()),
                "country": event["Country"],
                "type": event["EventFormat"],
                "session_dates": session_dates,
            }
        )
    return weekends

def get_race_weekends_by_place(place):
    """Returns a list of past n race weekends for a given place."""
    enable_cache()
    place=place.lower().strip()
    weekends=[]
    current_year=date.today().year

    for year in range(2018,current_year): #Edit according to data availability (current data till last year)
        try:
            schedule=fastf1.get_event_schedule(int(year))
        except Exception:
            continue

        for _, event in schedule.iterrows():
            if event.is_testing():
                continue

            event_name=str(event["EventName"]).strip().lower()
            
            if place==event_name:
                weekends.append({
                    "round_number": event["RoundNumber"],
                    "event_name": event["EventName"],
                    "date": str(event["EventDate"].date()),
                    "country": event["Country"],
                    "year": int(event["EventDate"].date().year),
                    "type": event["EventFormat"],
                })
    return weekends

def get_all_unique_race_names(start_year=2018, end_year=2025): #update as necessary
    "Return a list of all unique race locations"
    enable_cache()
    race_names=set()
    
    for year in range(start_year, end_year+1):
        try:
            schedule=fastf1.get_event_schedule(int(year))
        except Exception:
            continue

        for _,event in schedule.iterrows():
            if event.is_testing():
                continue

            name=str(event["EventName"]).strip()
            race_names.add(name)

    return sorted(race_names)

def list_rounds(year):
    """Lists all rounds for a given year."""
    enable_cache()
    print(f"F1 Schedule {year}")
    schedule = fastf1.get_event_schedule(int(year))
    for _, event in schedule.iterrows():
        print(f"{event['RoundNumber']}: {event['EventName']}")


def list_sprints(year):
    """Lists all sprint rounds for a given year."""
    enable_cache()
    print(f"F1 Sprint Races {year}")
    schedule = fastf1.get_event_schedule(int(year))
    sprint_name = "sprint_qualifying"
    if year == 2023:
        sprint_name = "sprint_shootout"
    if year in [2021, 2022]:
        sprint_name = "sprint"
    sprints = schedule[schedule["EventFormat"] == sprint_name]
    if sprints.empty:
        print(f"No sprint races found for {year}.")
    else:
        for _, event in sprints.iterrows():
            print(f"{event['RoundNumber']}: {event['EventName']}")
