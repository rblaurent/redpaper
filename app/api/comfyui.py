from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services import comfyui_process
from app.services.comfyui_client import get_queue_status
from app.services.desktop_detector import get_desktops
from app.services.generator import generate_all, generate_for_desktop
from app.services.scheduler import get_next_run, trigger_now

router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])

# Track in-progress generation to avoid duplicates
_generating: bool = False


@router.get("/status")
async def comfyui_status():
    running = await comfyui_process.is_running()
    queue = await get_queue_status() if running else {}
    return {
        "running": running,
        "url": comfyui_process.get_comfyui_url(),
        "queue": queue,
        "next_scheduled": get_next_run(),
        "generating": _generating,
    }


@router.post("/start")
async def start_comfyui():
    if await comfyui_process.is_running():
        return {"status": "already_running"}
    ok = comfyui_process.start()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to start ComfyUI")
    return {"status": "starting"}


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
