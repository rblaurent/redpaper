"""
Manages the ComfyUI process: health-check, start, wait-until-ready.
"""
import asyncio
import json
import logging
import os
import subprocess

import aiohttp

logger = logging.getLogger(__name__)

_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(base, "config.json")) as f:
            _config_cache = json.load(f)
    return _config_cache


def get_comfyui_url() -> str:
    return _load_config().get("comfyui_url", "http://127.0.0.1:8188")


def invalidate_config_cache():
    global _config_cache
    _config_cache = None


async def is_running() -> bool:
    """Return True if ComfyUI is reachable."""
    url = get_comfyui_url()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.get(f"{url}/system_stats") as resp:
                return resp.status == 200
    except Exception:
        return False


def start() -> bool:
    """
    Launch ComfyUI via its run_comfyui.bat script.
    Returns True if the process was spawned (does not wait for readiness).
    """
    cfg = _load_config()
    comfyui_path = cfg.get("comfyui_path", "T:/Projects/ComfyUI")
    script = cfg.get("comfyui_launch_script", "run_comfyui.bat")
    bat_path = os.path.join(comfyui_path, script)

    if not os.path.isfile(bat_path):
        logger.error("ComfyUI launch script not found: %s", bat_path)
        return False

    try:
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            cwd=comfyui_path,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        logger.info("ComfyUI process spawned from %s", bat_path)
        return True
    except Exception as e:
        logger.error("Failed to start ComfyUI: %s", e)
        return False


async def wait_until_ready(timeout: int = 120) -> bool:
    """Poll ComfyUI health endpoint until ready or timeout (seconds)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await is_running():
            logger.info("ComfyUI is ready")
            return True
        await asyncio.sleep(2)
    logger.warning("ComfyUI did not become ready within %ds", timeout)
    return False


async def ensure_running(auto_start: bool = True) -> bool:
    """
    Check if ComfyUI is running; optionally start it and wait.
    Returns True if ComfyUI is (now) ready.
    """
    if await is_running():
        return True
    if not auto_start:
        return False
    logger.info("ComfyUI not running — starting...")
    if not start():
        return False
    return await wait_until_ready()
