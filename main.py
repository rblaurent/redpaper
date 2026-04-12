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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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
        "positive_prompt_node_id": cfg.get("positive_prompt_node_id"),
        "negative_prompt_node_id": cfg.get("negative_prompt_node_id"),
        "default_prompt": cfg.get("default_prompt"),
        "negative_prompt": cfg.get("negative_prompt", ""),
    }


@app.post("/api/config")
async def save_config(body: dict):
    cfg = load_config()
    allowed = {
        "schedule_cron", "comfyui_port", "positive_prompt_node_id",
        "negative_prompt_node_id", "default_prompt", "negative_prompt",
    }
    for key in allowed:
        if key in body:
            cfg[key] = body[key]
    comfyui_process.invalidate_config_cache()
    with open(os.path.join(BASE_DIR, "config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    return {"status": "saved"}



if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("web_port", 8080)
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=False)
