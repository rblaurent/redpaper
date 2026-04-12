import json
import os
import shutil

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services import comfyui_process
from app.services.comfyui_client import get_queue_status
from app.services.desktop_detector import get_desktops
from app.services.generator import generate_all, generate_for_desktop
from app.services.scheduler import get_next_run, trigger_now

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])

# Track in-progress generation to avoid duplicates
_generating: bool = False


@router.get("/claude-status")
async def claude_status():
    try:
        with open(os.path.join(_BASE_DIR, "config.json")) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    path = cfg.get("claude_path", "") or shutil.which("claude") or ""
    found = bool(path and os.path.isfile(path))
    return {"path": path, "found": found}


@router.get("/status")
async def comfyui_status():
    running = await comfyui_process.is_running()
    queue = await get_queue_status() if running else {}
    return {
        "running": running,
        "comfyui_port": comfyui_process._load_config().get("comfyui_port", 8188),
        "queue": queue,
        "next_scheduled": get_next_run(),
        "generating": _generating,
    }


class GenerateRequest(BaseModel):
    desktop_guid: str | None = None
    all: bool = False


@router.post("/generate")
async def generate(body: GenerateRequest, background_tasks: BackgroundTasks):
    """Trigger wallpaper generation. Pass desktop_guid for one desktop, or all=true for all."""
    global _generating
    if _generating:
        raise HTTPException(status_code=409, detail="Generation already in progress")

    if body.all or body.desktop_guid is None:
        background_tasks.add_task(_run_generate_all)
        return {"status": "started", "target": "all"}

    desktops = {d.guid: d for d in get_desktops()}
    info = desktops.get(body.desktop_guid)
    if not info:
        raise HTTPException(status_code=404, detail="Desktop GUID not found")

    background_tasks.add_task(_run_generate_one, info)
    return {"status": "started", "target": body.desktop_guid}


async def _run_generate_all():
    global _generating
    _generating = True
    try:
        await generate_all()
    finally:
        _generating = False


async def _run_generate_one(info):
    global _generating
    _generating = True
    try:
        await generate_for_desktop(info)
    finally:
        _generating = False
