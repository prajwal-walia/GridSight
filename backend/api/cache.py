"""
/api/cache — REST endpoints for cache management.

Provides listing of precomputed caches and background preload triggers.
"""

from __future__ import annotations

import asyncio
import functools
import traceback

from fastapi import APIRouter

from core.cache_manager import list_cached, preload_session_sync, set_status
from models.schemas import (
    CacheListResponse, CacheEntry,
    PreloadRequest, PreloadResponse,
)

router = APIRouter(prefix="/api/cache", tags=["cache"])


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )


# ── GET /api/cache/list ──────────────────────────────────────────────────

@router.get("/list", response_model=CacheListResponse)
async def cache_list():
    """Return metadata for every precomputed session cache on disk."""
    entries = list_cached()
    return CacheListResponse(
        sessions=[CacheEntry(**e) for e in entries]
    )


# ── POST /api/cache/preload ─────────────────────────────────────────────

@router.post("/preload", response_model=PreloadResponse)
async def cache_preload(body: PreloadRequest):
    """
    Trigger background caching of a session.

    Returns immediately — the heavy work runs in a thread-pool executor
    so no client needs to wait.
    """
    async def _do_preload():
        try:
            await _run(preload_session_sync, body.year, body.round, body.type)
        except Exception as e:
            # Catch-all for any exception that escapes the sync function
            # (e.g. executor failures, multiprocessing deadlocks)
            traceback.print_exc()
            print(f"[cache] Background task FAILED for {body.year} R{body.round} {body.type}: {e}")
            set_status(body.year, body.round, body.type,
                       status="error", detail=str(e))

    asyncio.create_task(_do_preload())
    return PreloadResponse(status="started")
