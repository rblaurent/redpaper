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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import AsyncSessionLocal, Desktop, Prompt, Wallpaper
from app.services import comfyui_client, comfyui_process, wallpaper_setter
from app.services.desktop_detector import get_desktops, get_current_desktop_guid, DesktopInfo
from app.services.monitor_detector import get_monitors

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_progress: dict = {"desktop_current": 0, "desktop_total": 0, "image_current": 0, "image_total": 0, "label": "", "prompt": ""}


def get_progress() -> dict:
    return dict(_progress)


async def last_generation_date() -> Optional[date]:
    """Return the date of the most recent wallpaper generation, queried from the DB."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.max(Wallpaper.generated_at)))
        last_dt = result.scalar_one_or_none()
        if last_dt is None:
            return None
        return last_dt.date()


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


async def _generate_one_image(
    workflow_template: dict,
    cfg: dict,
    prompt_text: str,
) -> tuple[str, str] | None:
    """
    Submit one ComfyUI generation (with a fresh random seed) and return
    (filename, subfolder) of the output image, or None on failure.
    """
    workflow = json.loads(json.dumps(workflow_template))  # deep copy

    pos_node = cfg.get("positive_prompt_node_id")
    neg_node = cfg.get("negative_prompt_node_id")
    seed_node = cfg.get("seed_node_id")

    if pos_node:
        comfyui_client.inject_prompt(workflow, str(pos_node), prompt_text)
    if neg_node:
        comfyui_client.inject_prompt(workflow, str(neg_node), cfg.get("negative_prompt", ""))
    if seed_node and str(seed_node) in workflow:
        workflow[str(seed_node)]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

    try:
        comfy_id = await comfyui_client.submit_workflow(workflow)
    except Exception as e:
        logger.error("Failed to submit workflow: %s", e)
        return None

    outputs = await comfyui_client.poll_until_done(comfy_id)
    if not outputs:
        logger.error("Generation timed out")
        return None

    return _extract_first_image(outputs)


async def generate_for_desktop(desktop_info: DesktopInfo, prompt_text: str | None = None) -> bool:
    """
    Generate a wallpaper for one virtual desktop.
    Respects per-monitor config: disabled monitors are skipped; mode=original
    produces a unique image per active monitor, mode=repeated shares one image.
    Returns True on success.
    """
    global _progress
    cfg = _load_config()
    workflow_template = _load_workflow()
    if workflow_template is None:
        logger.error("Cannot generate: workflow.json missing")
        return False

    if not await comfyui_process.is_running():
        logger.info("ComfyUI not available on port %s — skipping", cfg.get("comfyui_port", 8188))
        return False

    # Update desktop label (generate_all sets desktop_current/total before calling us)
    if _progress["desktop_total"] == 0:
        _progress["desktop_current"] = 1
        _progress["desktop_total"] = 1
    _progress["label"] = desktop_info.name
    _progress["image_current"] = 0
    _progress["image_total"] = 0

    async with AsyncSessionLocal() as session:
        desktop = await _get_or_create_desktop(session, desktop_info)
        await session.commit()

        # Reload with monitor_configs relationship
        desktop = (await session.execute(
            select(Desktop)
            .options(selectinload(Desktop.monitor_configs))
            .where(Desktop.id == desktop.id)
        )).scalar_one()

        # ── Resolve prompt ────────────────────────────────────────────────────
        default_prompt = cfg.get("default_prompt", "a beautiful landscape wallpaper")
        db_prompt_id: int | None = None
        if prompt_text is None:
            if desktop.theme:
                from app.services.prompt_generator import generate_prompt_for_desktop as _ai_gen
                ai_text = await _ai_gen(desktop, date.today())
                if ai_text:
                    await session.execute(
                        update(Prompt)
                        .where(Prompt.desktop_id == desktop.id)
                        .values(is_active=False)
                        .execution_options(synchronize_session=False)
                    )
                    new_prompt = Prompt(
                        desktop_id=desktop.id,
                        text=ai_text,
                        is_active=True,
                        is_ai_generated=True,
                    )
                    session.add(new_prompt)
                    await session.flush()
                    prompt_text = ai_text
                    db_prompt_id = new_prompt.id
                else:
                    logger.warning("AI prompt generation failed for %s, falling back", desktop_info.guid)
                    db_prompt_id, prompt_text = await _get_active_prompt(session, desktop.id, default_prompt)
            else:
                db_prompt_id, prompt_text = await _get_active_prompt(session, desktop.id, default_prompt)

        # Store resolved prompt in progress so frontend can display it
        _progress["prompt"] = (prompt_text or "")[:400]

        # ── Determine per-monitor mode ────────────────────────────────────────
        detected = await asyncio.to_thread(get_monitors)
        configs_map = {c.monitor_device_path: c for c in desktop.monitor_configs}

        shared_monitors = []
        individual_monitors = []
        for mon in detected:
            mon_cfg = configs_map.get(mon.device_path)
            mon_mode = mon_cfg.mode if mon_cfg else "shared"
            if mon_mode == "off":
                continue
            elif mon_mode == "individual":
                individual_monitors.append(mon)
            else:
                shared_monitors.append(mon)

        if not shared_monitors and not individual_monitors:
            logger.warning("All monitors off for desktop %s — skipping", desktop_info.guid)
            return False

        # targets: None = "one shared image"; device_path = "unique image for that monitor"
        targets: list[str | None] = (
            ([None] if shared_monitors else []) +
            [mon.device_path for mon in individual_monitors]
        )

        # ── Generate images ───────────────────────────────────────────────────
        today = date.today().isoformat()
        output_dir = cfg.get("output_dir", os.path.join(BASE_DIR, "output"))
        generated_pairs: list[tuple[str | None, str]] = []

        _progress["image_total"] = len(targets)
        for img_idx, target_path in enumerate(targets):
            _progress["image_current"] = img_idx + 1
            image_info = await _generate_one_image(workflow_template, cfg, prompt_text)
            if image_info is None:
                return False

            filename, subfolder = image_info
            if target_path is not None:
                all_active = shared_monitors + individual_monitors
                mon_idx = next((m.index for m in all_active if m.device_path == target_path), 0)
                dest_name = f"{desktop_info.guid[:8]}_m{mon_idx}_{filename}"
            else:
                dest_name = f"{desktop_info.guid[:8]}_{filename}"

            dest_path = os.path.join(output_dir, today, dest_name)
            if not await comfyui_client.download_image(filename, subfolder, dest_path):
                return False

            generated_pairs.append((target_path, dest_path))

        # ── Update DB ─────────────────────────────────────────────────────────
        # Deactivate per-slot (NULL = shared image slot; device_path = individual slot)
        for target_path, _ in generated_pairs:
            await session.execute(
                update(Wallpaper)
                .where(
                    Wallpaper.desktop_id == desktop.id,
                    Wallpaper.monitor_device_path == target_path,
                )
                .values(is_active=False)
                .execution_options(synchronize_session=False)
            )

        now = datetime.utcnow()
        all_active = shared_monitors + individual_monitors
        for target_path, dest_path in generated_pairs:
            mon_index = None
            if target_path is not None:
                mon_index = next((m.index for m in all_active if m.device_path == target_path), None)
            session.add(Wallpaper(
                desktop_id=desktop.id,
                prompt_id=db_prompt_id,
                file_path=dest_path,
                generated_at=now,
                is_active=True,
                monitor_index=mon_index,
                monitor_device_path=target_path,
            ))

        await session.commit()

        # ── Apply wallpapers ──────────────────────────────────────────────────
        try:
            current_guid = get_current_desktop_guid()
            all_desktops = get_desktops()
            current_idx = next(
                (d.index for d in all_desktops
                 if current_guid and d.guid.lower() == current_guid.lower()),
                None,
            )
        except Exception:
            current_idx = None

        # Build (device_path, file_path) pairs for the setter.
        # Shared image gets applied to every shared monitor; individual images go to their specific monitor.
        apply_pairs: list[tuple[str | None, str]] = []
        shared_path = next((fp for tp, fp in generated_pairs if tp is None), None)
        if shared_path:
            for mon in shared_monitors:
                apply_pairs.append((mon.device_path or None, shared_path))
        for mon in individual_monitors:
            indiv_path = next((fp for tp, fp in generated_pairs if tp == mon.device_path), None)
            if indiv_path:
                apply_pairs.append((mon.device_path or None, indiv_path))

        await asyncio.to_thread(
            wallpaper_setter.set_wallpapers_for_desktop,
            desktop_info.guid,
            apply_pairs,
            desktop_index=desktop_info.index,
            current_index=current_idx,
        )

    logger.info("Generated wallpaper(s) for desktop %s (%d shared + %d individual monitors, %d image(s))",
                desktop_info.name, len(shared_monitors), len(individual_monitors), len(generated_pairs))
    return True


async def generate_all() -> dict[str, bool]:
    """Generate wallpapers for all virtual desktops. Returns {guid: success}."""
    global _progress
    desktops = get_desktops()
    total = len(desktops)
    _progress = {"desktop_current": 0, "desktop_total": total, "image_current": 0, "image_total": 0, "label": "", "prompt": ""}
    results: dict[str, bool] = {}
    for i, desktop_info in enumerate(desktops):
        _progress["desktop_current"] = i + 1
        _progress["label"] = desktop_info.name
        logger.info("Generating for desktop: %s (%s)", desktop_info.name, desktop_info.guid)
        results[desktop_info.guid] = await generate_for_desktop(desktop_info)
    return results


def _extract_first_image(outputs: dict) -> tuple[str, str] | None:
    """Walk the ComfyUI outputs dict and return (filename, subfolder) of the first image."""
    for node_output in outputs.values():
        images = node_output.get("images", [])
        for img in images:
            if img.get("type") == "output":
                return img["filename"], img.get("subfolder", "")
    return None
