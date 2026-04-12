"""
HTTP client for the ComfyUI API.
Handles workflow submission, polling, and image download.
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Any

import aiohttp

from app.services.comfyui_process import get_comfyui_url

logger = logging.getLogger(__name__)

CLIENT_ID = str(uuid.uuid4())


async def submit_workflow(workflow: dict[str, Any]) -> str:
    """
    Submit a workflow (API-format JSON) to ComfyUI.
    Returns the prompt_id string.
    """
    url = get_comfyui_url()
    payload = {"prompt": workflow, "client_id": CLIENT_ID}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{url}/prompt", json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            prompt_id = data["prompt_id"]
            logger.info("Submitted workflow, prompt_id=%s", prompt_id)
            return prompt_id


async def poll_until_done(prompt_id: str, timeout: int = 300) -> dict[str, Any] | None:
    """
    Poll /history/{prompt_id} until the job finishes or timeout is reached.
    Returns the outputs dict on success, None on timeout.
    """
    url = get_comfyui_url()
    deadline = asyncio.get_event_loop().time() + timeout
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            async with session.get(f"{url}/history/{prompt_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if prompt_id in data:
                        job = data[prompt_id]
                        if job.get("status", {}).get("completed", False):
                            return job.get("outputs", {})
            await asyncio.sleep(2)
    logger.warning("Timed out waiting for prompt_id=%s", prompt_id)
    return None


async def download_image(filename: str, subfolder: str, dest_path: str) -> bool:
    """
    Download a generated image from /view and save it to dest_path.
    Returns True on success.
    """
    url = get_comfyui_url()
    params = {"filename": filename, "subfolder": subfolder, "type": "output"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/view", params=params) as resp:
                resp.raise_for_status()
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(await resp.read())
        logger.info("Downloaded image to %s", dest_path)
        return True
    except Exception as e:
        logger.error("Failed to download image: %s", e)
        return False


def inject_prompt(workflow: dict[str, Any], node_id: str, prompt_text: str) -> dict[str, Any]:
    """
    Replace the text input of a specific node in the workflow with prompt_text.
    node_id is a string key in the top-level workflow dict (API format).
    """
    if node_id and node_id in workflow:
        workflow[node_id]["inputs"]["text"] = prompt_text
    return workflow


async def get_queue_status() -> dict:
    """Return the current queue status from ComfyUI."""
    url = get_comfyui_url()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"{url}/queue") as resp:
                return await resp.json()
    except Exception:
        return {}
