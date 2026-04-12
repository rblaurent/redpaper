"""
redpaper — main FastAPI application entrypoint.
Run directly: python main.py
"""
import json
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.api import comfyui as comfyui_router
from app.api import desktops as desktops_router
from app.api import wallpapers as wallpapers_router
from app.services import comfyui_process
from app.services.scheduler import start_scheduler


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
# Console handler — skip if running without a console (e.g. pythonw)
import sys as _sys
if _sys.stderr is not None:
    _ch = logging.StreamHandler()
    _ch.setFormatter(_log_fmt)
    _root.addHandler(_ch)
# File handler — always write to server.log next to main.py
from logging.handlers import RotatingFileHandler as _RFH
_fh = _RFH(os.path.join(BASE_DIR, "server.log"), maxBytes=5 * 1024 * 1024, backupCount=2)
_fh.setFormatter(_log_fmt)
_root.addHandler(_fh)
# Suppress APScheduler's per-execution INFO noise (keeps WARNING+)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.json")) as f:
        return json.load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield


app = FastAPI(title="redpaper", description="AI Wallpaper Generator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(comfyui_router.router)
app.include_router(desktops_router.router)
app.include_router(desktops_router.monitors_router)
app.include_router(wallpapers_router.router)

# Serve generated wallpaper images
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Serve frontend static files
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/config")
async def get_config():
    cfg = load_config()
    # Don't expose internal paths unnecessarily; return relevant UI settings
    return {
        "schedule_cron": cfg.get("schedule_cron"),
        "comfyui_port": cfg.get("comfyui_port", 8188),
        "claude_path": cfg.get("claude_path", "claude"),
    }


@app.post("/api/config")
async def save_config(body: dict):
    cfg = load_config()
    allowed = {
        "schedule_cron", "comfyui_port", "claude_path",
    }
    for key in allowed:
        if key in body:
            cfg[key] = body[key]
    comfyui_process.invalidate_config_cache()
    with open(os.path.join(BASE_DIR, "config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    return {"status": "saved"}


@app.get("/api/claude/status")
async def claude_status():
    import shutil as _shutil
    cfg = load_config()
    path = cfg.get("claude_path", "") or _shutil.which("claude") or ""
    found = bool(path and os.path.isfile(path))
    return {"path": path, "found": found}


if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("web_port", 8080)
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=False)
