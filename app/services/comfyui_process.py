"""
ComfyUI availability check.
redpaper never starts ComfyUI — it simply polls whether the user-configured
port is reachable and skips generation when it is not.
"""
import json
import logging
import os

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
    port = _load_config().get("comfyui_port", 8188)
    return f"http://127.0.0.1:{port}"


def invalidate_config_cache():
    global _config_cache
    _config_cache = None


async def is_running() -> bool:
    """Return True if ComfyUI is reachable on the configured port."""
    url = get_comfyui_url()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.get(f"{url}/system_stats") as resp:
                return resp.status == 200
    except Exception:
        return False
