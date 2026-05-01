"""
Regulation era definitions for different F1 seasons.

Provides technical regulation info (DRS, active aero, boost mode, etc.)
that affects how telemetry is displayed and interpreted.

Covers the ground-effect era (2022+) only.
"""

from __future__ import annotations

from typing import Any


def get_regulation_era(year: int) -> dict[str, Any]:
    """Return regulation metadata for a given season year."""
    if year <= 2025:
        return {
            "era": "ground_effect",
            "label": "V6 Hybrid Ground Effect",
            "years": "2022-2025",
            "year": year,
            "has_drs": True,
            "has_active_aero": False,
            "has_overtake_mode": False,
        }
    else:
        return {
            "era": "active_aero",
            "label": "Active Aero Era",
            "years": "2026+",
            "year": year,
            "has_drs": False,
            "has_active_aero": True,
            "has_overtake_mode": True,
            "has_boost_mode": True,
            "straight_mode_zones": True,
        }
