#!/usr/bin/env python3
"""
Pre-compute and cache F1 session data for GridSight.
"""

import sys
import os
import argparse
import time
import logging

_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import fastf1
from core.f1_data import enable_cache
from core.cache_manager import preload_session_sync

# Set up logging and caching
logging.basicConfig(level=logging.WARNING)
enable_cache()

def get_sprint_rounds(year):
    try:
        schedule = fastf1.get_event_schedule(year)
        sprint_rounds = []
        for _, event in schedule.iterrows():
            if 'sprint' in str(event.get('EventFormat', '')).lower():
                sprint_rounds.append(int(event['RoundNumber']))
        return sprint_rounds
    except Exception:
        return []

def get_sessions_for_round(year, round_num, has_sprint=False):
    if has_sprint:
        return [(year, round_num, s) for s in ['FP1', 'SQ', 'S', 'Q', 'R']]
    else:
        return [(year, round_num, s) for s in ['FP1', 'FP2', 'FP3', 'Q', 'R']]


# Build SESSIONS_TO_PRECOMPUTE dynamically
print("Detecting sprint rounds and building schedule...")
SESSIONS_TO_PRECOMPUTE = []
SPRINT_ROUNDS = {}
for year in [2022, 2023, 2024, 2025, 2026]:
    SPRINT_ROUNDS[year] = get_sprint_rounds(year)

# 2026 — first 3 rounds all sessions
for rnd in range(1, 4):
    SESSIONS_TO_PRECOMPUTE.extend(
        get_sessions_for_round(2026, rnd, rnd in SPRINT_ROUNDS[2026])
    )

# 2025 — full season all sessions
for rnd in range(1, 25):
    SESSIONS_TO_PRECOMPUTE.extend(
        get_sessions_for_round(2025, rnd, rnd in SPRINT_ROUNDS[2025])
    )

# 2024 — selected rounds all sessions
for rnd in [1, 4, 6, 7, 9, 13, 16, 19, 20, 22, 24]:
    SESSIONS_TO_PRECOMPUTE.extend(
        get_sessions_for_round(2024, rnd, rnd in SPRINT_ROUNDS[2024])
    )

# 2023 — selected rounds all sessions
for rnd in [1, 6, 7, 10, 15, 20, 22]:
    SESSIONS_TO_PRECOMPUTE.extend(
        get_sessions_for_round(2023, rnd, rnd in SPRINT_ROUNDS[2023])
    )

# 2022 — selected rounds all sessions
for rnd in [1, 5, 8, 10, 14, 18, 22]:
    SESSIONS_TO_PRECOMPUTE.extend(
        get_sessions_for_round(2022, rnd, rnd in SPRINT_ROUNDS[2022])
    )


def cache_path(year, rnd, stype):
    return os.path.join(_BACKEND_DIR, 'computed_data', f'{year}_{rnd}_{stype}.json.gz')

def already_cached(year, rnd, stype):
    return os.path.exists(cache_path(year, rnd, stype))

def run_precompute(sessions, force=False):
    total = len(sessions)
    if total == 0:
        print("No sessions to process.")
        return

    completed = skipped = failed = 0
    start_total = time.time()

    for i, (year, rnd, stype) in enumerate(sessions, 1):
        label = f"{year} R{rnd} {stype}"
        prefix = f"[{i}/{total}]"

        if not force and already_cached(year, rnd, stype):
            print(f"{prefix} SKIP {label} — already cached")
            skipped += 1
            continue

        print(f"{prefix} Precomputing {label}...")
        t0 = time.time()
        try:
            preload_session_sync(year, rnd, stype)
            elapsed = time.time() - t0
            print(f"{prefix} DONE {label} ({elapsed:.1f}s)")
            completed += 1
        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ['not found', 'sessionnotavailable', 'available', 'does not exist', 'cannot find']):
                print(f"{prefix} SKIP {label} — unavailable or does not exist ({type(e).__name__})")
                skipped += 1
            else:
                print(f"{prefix} FAIL {label} — {e}")
                failed += 1

    total_time = time.time() - start_total
    mins = int(total_time // 60)
    secs = int(total_time % 60)
    print(f"\n✓ Completed: {completed}")
    print(f"⟳ Skipped:   {skipped}  (already cached or not available)")
    print(f"✗ Failed:    {failed}  (logged above)")
    print(f"Total time:  {mins}m {secs}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Recompute even if cached')
    parser.add_argument('--year', type=int, help='Only precompute a specific year')
    parser.add_argument('--session', nargs=3, metavar=('YEAR', 'ROUND', 'TYPE'), help='Precompute single session e.g. --session 2026 3 R')
    args = parser.parse_args()

    if args.session:
        sessions = [(int(args.session[0]), int(args.session[1]), args.session[2])]
    elif args.year:
        sessions = [(y, r, s) for (y, r, s) in SESSIONS_TO_PRECOMPUTE if y == args.year]
    else:
        sessions = SESSIONS_TO_PRECOMPUTE

    print(f"Starting precomputation for {len(sessions)} sessions...")
    run_precompute(sessions, force=args.force)
