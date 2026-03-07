"""
Pit stop position prediction engine.

Uses per-circuit pit loss data to predict where a driver would rejoin
the field if they pitted on this lap.

Ported from F1ReplayTiming — prediction algorithm kept identical.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Load pit loss data ───────────────────────────────────────────────────

_PIT_LOSS_PATH = Path(__file__).resolve().parent.parent / "data" / "pit_loss.json"
_pit_loss_data: dict[str, Any] | None = None


def _load_pit_loss() -> dict[str, Any]:
    """Load and cache the pit_loss.json data."""
    global _pit_loss_data
    if _pit_loss_data is None:
        try:
            with open(_PIT_LOSS_PATH, "r", encoding="utf-8") as f:
                _pit_loss_data = json.load(f)
        except Exception as e:
            logger.warning("Could not load pit_loss.json: %s", e)
            _pit_loss_data = {"circuits": {}, "global_averages": {}}
    return _pit_loss_data


def get_pit_loss_for_event(event_name: str) -> dict[str, float] | None:
    """Look up pit loss data for a given event name.

    Returns
    -------
    dict with keys: pit_loss_green, pit_loss_sc, pit_loss_vsc
    or None if the circuit is not found.
    """
    data = _load_pit_loss()
    circuits = data.get("circuits", {})

    # Try exact match first
    if event_name in circuits:
        c = circuits[event_name]
        return {
            "pit_loss_green": c["pit_loss_green"],
            "pit_loss_sc": c["pit_loss_sc"],
            "pit_loss_vsc": c["pit_loss_vsc"],
        }

    # Try case-insensitive partial match
    event_lower = event_name.lower()
    for name, c in circuits.items():
        if name.lower() == event_lower:
            return {
                "pit_loss_green": c["pit_loss_green"],
                "pit_loss_sc": c["pit_loss_sc"],
                "pit_loss_vsc": c["pit_loss_vsc"],
            }
        # Also match by circuit name
        circuit = c.get("circuit", "")
        if circuit and circuit.lower() in event_lower:
            return {
                "pit_loss_green": c["pit_loss_green"],
                "pit_loss_sc": c["pit_loss_sc"],
                "pit_loss_vsc": c["pit_loss_vsc"],
            }

    # Fall back to global averages
    avgs = data.get("global_averages", {})
    if avgs:
        return {
            "pit_loss_green": avgs.get("green", 23.5),
            "pit_loss_sc": avgs.get("sc", 17.2),
            "pit_loss_vsc": avgs.get("vsc", 17.2),
        }

    return None


def get_all_pit_loss() -> dict[str, Any]:
    """Return the full pit_loss.json data for the API endpoint."""
    return _load_pit_loss()


# ── Prediction engine ────────────────────────────────────────────────────


def compute_pit_predictions(
    drivers: list[dict[str, Any]],
    pit_loss_green: float,
    pit_loss_sc: float,
    pit_loss_vsc: float,
    flag: str,
    lap: int,
) -> dict[str, dict[str, Any] | None]:
    """Compute pit position predictions for every driver.

    Parameters
    ----------
    drivers:
        List of driver dicts, each with at least:
        ``code``, ``position``, ``gap_to_leader``, ``is_out``
    pit_loss_green / pit_loss_sc / pit_loss_vsc:
        Pit time loss in seconds for each track condition.
    flag:
        Current track flag: "GREEN", "SAFETY_CAR", "VSC", "RED", "YELLOW", etc.
    lap:
        Current lap number.

    Returns
    -------
    dict mapping driver code → prediction dict or None.
    Each prediction dict contains:
        predicted_position, margin_ahead, margin_behind, free_air
    """
    # Don't show before lap 5
    if lap < 5:
        return {d["code"]: None for d in drivers}

    # Select pit loss based on track status
    flag_upper = flag.upper() if flag else "GREEN"
    if "SAFETY_CAR" in flag_upper or flag_upper == "SC":
        pit_loss = pit_loss_sc
    elif "VSC" in flag_upper:
        pit_loss = pit_loss_vsc
    else:
        pit_loss = pit_loss_green

    # Build gap list for on-track drivers
    driver_gaps: list[tuple[str, float]] = []  # (code, gap_seconds)
    for d in drivers:
        if d.get("is_out") or d.get("retired"):
            continue
        code = d["code"]
        pos = d.get("position")

        if pos == 1:
            driver_gaps.append((code, 0.0))
        else:
            gap = d.get("gap_to_leader")
            if gap is not None:
                try:
                    gap_sec = float(gap) if not isinstance(gap, str) else _parse_gap(gap)
                except (ValueError, TypeError):
                    continue
                if gap_sec is not None:
                    driver_gaps.append((code, gap_sec))

    if not driver_gaps:
        return {d["code"]: None for d in drivers}

    # Sort by gap ascending (leader first)
    driver_gaps.sort(key=lambda x: x[1])

    result: dict[str, dict | None] = {}

    for d in drivers:
        code = d["code"]

        if d.get("is_out") or d.get("retired"):
            result[code] = None
            continue

        current_gap: float | None = None
        if d.get("position") == 1:
            current_gap = 0.0
        else:
            gap = d.get("gap_to_leader")
            if gap is not None:
                try:
                    current_gap = float(gap) if not isinstance(gap, str) else _parse_gap(gap)
                except (ValueError, TypeError):
                    current_gap = None

        if current_gap is None:
            result[code] = None
            continue

        projected_gap = current_gap + pit_loss

        # Build gap list excluding this driver
        other_gaps = [g for abbr, g in driver_gaps if abbr != code]

        # Find what position this projected gap would be
        predicted_pos = 1
        for g in other_gaps:
            if projected_gap > g:
                predicted_pos += 1
            else:
                break

        # Cap at field size
        predicted_pos = min(predicted_pos, len(other_gaps) + 1)

        # Only show if they'd lose at least 1 position
        current_pos = d.get("position") or 0
        if predicted_pos > current_pos:
            # Margin behind — gap to the car one position behind predicted
            behind_idx = predicted_pos - 1  # 0-indexed into other_gaps
            margin_behind = None
            if behind_idx < len(other_gaps):
                margin_behind = round(max(0.0, other_gaps[behind_idx] - projected_gap), 3)

            # Margin ahead — gap to car one position ahead of predicted
            ahead_idx = predicted_pos - 2
            margin_ahead = None
            if ahead_idx >= 0:
                margin_ahead = round(max(0.0, projected_gap - other_gaps[ahead_idx]), 3)

            # Free air — is there clean air (>2s gap to car ahead)?
            free_air = margin_ahead is not None and margin_ahead > 2.0

            result[code] = {
                "predicted_position": predicted_pos,
                "margin_ahead": margin_ahead,
                "margin_behind": margin_behind,
                "free_air": free_air,
            }
        else:
            result[code] = None

    return result


def _parse_gap(gap_str: str) -> float | None:
    """Parse a gap string like '+1.234' or '1.234' into seconds."""
    if not gap_str:
        return None
    s = gap_str.strip().lstrip("+")
    if s.startswith("LAP"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
