"""
Orchestrates the full wallpaper generation flow:
  prompt → ComfyUI workflow → image download → DB record → apply wallpaper
"""
import asyncio
import json
import logging
import os
import random
from datetime import datetime, date
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, Desktop, Prompt, Wallpaper
from app.services import comfyui_client, comfyui_process, wallpaper_setter
from app.services.desktop_detector import get_desktops, get_current_desktop_guid, DesktopInfo

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_last_generated: Optional[date] = None


def last_generation_date() -> Optional[date]:
    return _last_generated


def _load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.json")) as f:
        return json.load(f)


def _load_workflow() -> dict | None:
    path = os.path.join(BASE_DIR, "workflow.json")
    if not os.path.isfile(path):
        logger.warning("workflow.json not found at %s", path)
        return None
    with open(path) as f:
        return json.load(f)


async def _get_active_prompt(session: AsyncSession, desktop_id: int, default: str) -> tuple[int | None, str]:
    """Return (prompt_id, prompt_text) for the given desktop."""
    result = await session.execute(
        select(Prompt)
        .where(Prompt.desktop_id == desktop_id, Prompt.is_active == True)
        .order_by(Prompt.created_at.desc())
        .limit(1)
    )
    prompt = result.scalar_one_or_none()
    if prompt:
        return prompt.id, prompt.text
    return None, default


async def _get_or_create_desktop(session: AsyncSession, info: DesktopInfo) -> Desktop:
    result = await session.execute(select(Desktop).where(Desktop.guid == info.guid))
    desktop = result.scalar_one_or_none()
    if not desktop:
        desktop = Desktop(guid=info.guid, name=info.name, display_order=info.index)
        session.add(desktop)
        await session.flush()
    else:
        desktop.name = info.name
        desktop.display_order = info.index
    return desktop


async def generate_for_desktop(desktop_info: DesktopInfo, prompt_text: str | None = None) -> bool:
    """
    Generate a wallpaper for one virtual desktop.
    Returns True on success.
    """
    cfg = _load_config()
    workflow = _load_workflow()
    if workflow is None:
        logger.error("Cannot generate: workflow.json missing")
        return False

    # Check ComfyUI is reachable
    if not await comfyui_process.is_running():
        logger.info("ComfyUI not available on port %s — skipping", cfg.get("comfyui_port", 8188))
        return False

    async with AsyncSessionLocal() as session:
        desktop = await _get_or_create_desktop(session, desktop_info)
        await session.commit()

        default_prompt = cfg.get("default_prompt", "a beautiful landscape wallpaper")
        if prompt_text is None:
            _, prompt_text = await _get_active_prompt(session, desktop.id, default_prompt)

        # Inject prompts into workflow
        pos_node = cfg.get("positive_prompt_node_id")
        neg_node = cfg.get("negative_prompt_node_id")
        seed_node = cfg.get("seed_node_id")
        if pos_node:
            comfyui_client.inject_prompt(workflow, str(pos_node), prompt_text)
        if neg_node:
            neg_text = cfg.get("negative_prompt", "")
            comfyui_client.inject_prompt(workflow, str(neg_node), neg_text)
        if seed_node and seed_node in workflow:
            workflow[seed_node]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

        # Submit to ComfyUI
        try:
            prompt_id = await comfyui_client.submit_workflow(workflow)
        except Exception as e:
            logger.error("Failed to submit workflow: %s", e)
            return False

        # Poll for completion
        outputs = await comfyui_client.poll_until_done(prompt_id)
        if not outputs:
            logger.error("Generation timed out for desktop %s", desktop_info.guid)
            return False

        # Find the output image
        image_info = _extract_first_image(outputs)
        if not image_info:
            logger.error("No output image found in ComfyUI response")
            return False

        filename, subfolder = image_info

        # Save image locally
        today = date.today().isoformat()
        output_dir = cfg.get("output_dir", os.path.join(BASE_DIR, "output"))
        dest_path = os.path.join(output_dir, today, f"{desktop_info.guid[:8]}_{filename}")
        if not await comfyui_client.download_image(filename, subfolder, dest_path):
            return False

        # Deactivate all previous wallpapers for this desktop first
        await session.execute(
            update(Wallpaper)
            .where(Wallpaper.desktop_id == desktop.id)
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )

        # Insert the new active wallpaper
        wallpaper = Wallpaper(
            desktop_id=desktop.id,
            file_path=dest_path,
            generated_at=datetime.utcnow(),
            is_active=True,
        )
        session.add(wallpaper)
        await session.commit()

        # Apply wallpaper — pass index info so inactive desktops get a brief
        # keyboard-driven switch to apply immediately rather than waiting for
        # the user to manually switch to them.
        try:
            current_guid = get_current_desktop_guid()
            all_desktops = get_desktops()
            current_idx  = next(
                (d.index for d in all_desktops
                 if current_guid and d.guid.lower() == current_guid.lower()),
                None,
            )
        except Exception:
            current_idx = None

        await asyncio.to_thread(
            wallpaper_setter.set_wallpaper_for_desktop,
            desktop_info.guid,
            dest_path,
            desktop_index=desktop_info.index,
            current_index=current_idx,
        )

    logger.info("Generated wallpaper for desktop %s → %s", desktop_info.name, dest_path)
    return True


async def generate_all() -> dict[str, bool]:
    """Generate wallpapers for all virtual desktops. Returns {guid: success}."""
    global _last_generated
    desktops = get_desktops()
    results: dict[str, bool] = {}
    for desktop_info in desktops:
        logger.info("Generating for desktop: %s (%s)", desktop_info.name, desktop_info.guid)
        results[desktop_info.guid] = await generate_for_desktop(desktop_info)
    _last_generated = date.today()
    return results


def _extract_first_image(outputs: dict) -> tuple[str, str] | None:
    """Walk the ComfyUI outputs dict and return (filename, subfolder) of the first image."""
    for node_output in outputs.values():
        images = node_output.get("images", [])
        for img in images:
            if img.get("type") == "output":
                return img["filename"], img.get("subfolder", "")
    return None
