"""
Async-safe wrappers around synchronous FastF1 / f1_data functions.

FastF1 performs blocking I/O (network + disk), so every call is dispatched
to the default executor via ``asyncio.get_event_loop().run_in_executor``.
"""

import asyncio
import functools

from core import f1_data


async def _run(func, *args, **kwargs):
    """Run *func* in the default thread-pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


# ── public async API ─────────────────────────────────────────────────────

async def load_session(year: int, round_number: int, session_type: str = "R"):
    """Load a FastF1 session (blocking call pushed to executor)."""
    return await _run(f1_data.load_session, year, round_number, session_type)


async def get_race_telemetry(session, session_type: str = "R"):
    """Build race telemetry frames (CPU-heavy, blocking)."""
    return await _run(f1_data.get_race_telemetry, session, session_type)


async def get_quali_telemetry(session, session_type: str = "Q"):
    """Build qualifying telemetry frames (CPU-heavy, blocking)."""
    return await _run(f1_data.get_quali_telemetry, session, session_type)


async def get_circuit_rotation(session):
    """Return the circuit rotation angle."""
    return await _run(f1_data.get_circuit_rotation, session)


async def list_rounds(year: int):
    """Print the schedule for *year*."""
    return await _run(f1_data.list_rounds, year)


async def list_sprints(year: int):
    """Print sprint rounds for *year*."""
    return await _run(f1_data.list_sprints, year)
