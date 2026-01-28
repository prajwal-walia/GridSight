from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.f1_data import enable_cache
from core.live_bridge import LiveBridge
from core.cache_manager import _ensure_dirs as ensure_cache_dirs
from api.sessions import router as sessions_router
from api.laps import router as laps_router
from api.replay import router as replay_router
from api.live import router as live_router
from api.live_f1 import router as live_f1_router
from api.cache import router as cache_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    enable_cache()
    ensure_cache_dirs()
    yield
    # Shutdown
    bridge = LiveBridge.get()
    await bridge.stop()
    # Clean up any active live F1 sessions
    from api.live_f1 import _live_sessions
    for session in list(_live_sessions.values()):
        await session.stop()
    _live_sessions.clear()


app = FastAPI(title="GridSight API", version="1.0.0", lifespan=lifespan)

# CORS — allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(laps_router)
app.include_router(replay_router)
app.include_router(live_router)
app.include_router(live_f1_router)
app.include_router(cache_router)

app.mount("/logos", StaticFiles(directory="assets/logos"), name="logos")


@app.get("/health")
async def health():
    return {"status": "ok"}
