import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Desktop, MonitorConfig, Prompt, Wallpaper, get_db
from app.services.desktop_detector import get_desktops, get_current_desktop_guid

router = APIRouter(prefix="/api/desktops", tags=["desktops"])
monitors_router = APIRouter(prefix="/api", tags=["monitors"])


@router.get("")
async def list_desktops(db: AsyncSession = Depends(get_db)):
    """Return all virtual desktops with their currently active wallpaper and monitor configs."""
    from app.services.monitor_detector import get_monitors as _get_monitors
    detected_vdesktops = get_desktops()
    current_guid = get_current_desktop_guid()
    detected_monitors = await asyncio.to_thread(_get_monitors)
    result = []

    for info in detected_vdesktops:
        # Look up active wallpaper from DB
        desktop_row = (await db.execute(
            select(Desktop).where(Desktop.guid == info.guid)
        )).scalar_one_or_none()

        active_wallpapers = []
        active_prompt = None
        if desktop_row:
            wps = (await db.execute(
                select(Wallpaper)
                .where(Wallpaper.desktop_id == desktop_row.id, Wallpaper.is_active == True)
                .order_by(Wallpaper.generated_at.desc())
            )).scalars().all()
            for wp in wps:
                wp_prompt_text = None
                wp_prompt_is_ai = False
                if wp.prompt_id:
                    wp_pr = (await db.execute(
                        select(Prompt).where(Prompt.id == wp.prompt_id)
                    )).scalar_one_or_none()
                    if wp_pr:
                        wp_prompt_text = wp_pr.text
                        wp_prompt_is_ai = wp_pr.is_ai_generated
                active_wallpapers.append({
                    "id": wp.id,
                    "file_path": wp.file_path,
                    "generated_at": wp.generated_at.isoformat(),
                    "prompt_text": wp_prompt_text,
                    "prompt_is_ai": wp_prompt_is_ai,
                    "monitor_index": wp.monitor_index,
                    "monitor_device_path": wp.monitor_device_path,
                })

            pr = (await db.execute(
                select(Prompt)
                .where(Prompt.desktop_id == desktop_row.id, Prompt.is_active == True)
                .order_by(Prompt.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if pr:
                active_prompt = {
                    "id": pr.id,
                    "text": pr.text,
                    "is_ai_generated": pr.is_ai_generated,
                    "created_at": pr.created_at.isoformat(),
                }

        # Build per-monitor config (detected monitors merged with saved configs)
        cfg_map: dict[str, MonitorConfig] = {}
        if desktop_row:
            cfg_rows = (await db.execute(
                select(MonitorConfig).where(MonitorConfig.desktop_id == desktop_row.id)
            )).scalars().all()
            cfg_map = {c.monitor_device_path: c for c in cfg_rows}

        wp_by_path = {}
        shared_wp = None
        for wp in active_wallpapers:
            if wp["monitor_device_path"]:
                wp_by_path[wp["monitor_device_path"]] = wp
            elif shared_wp is None:
                shared_wp = wp

        monitors_out = []
        for mon in detected_monitors:
            cfg = cfg_map.get(mon.device_path)
            mon_wp = wp_by_path.get(mon.device_path) or shared_wp
            monitors_out.append({
                "monitor_device_path": mon.device_path,
                "monitor_index": mon.index,
                "width": mon.width,
                "height": mon.height,
                "mode": cfg.mode if cfg else "shared",
                "active_wallpaper": mon_wp,
                # Only use the Windows-reported wallpaper for the currently active desktop.
                # GetWallpaper() always reflects the active desktop, so using it for
                # inactive desktops would show the wrong (current desktop's) images.
                "current_wallpaper_path": mon.current_wallpaper if info.guid == current_guid else None,
            })

        result.append({
            "index": info.index,
            "guid": info.guid,
            "name": info.name,
            "is_current": info.guid == current_guid,
            "active_wallpaper": active_wallpapers[0] if active_wallpapers else None,
            "active_wallpapers": active_wallpapers,
            "active_prompt": active_prompt,
            "theme": desktop_row.theme if desktop_row else None,
            "theme_style": desktop_row.theme_style if desktop_row else None,
            "workspace_path": desktop_row.workspace_path if desktop_row else None,
            "wallpaper_mode": desktop_row.wallpaper_mode if desktop_row else "repeated",
            "monitors": monitors_out,
        })

    return result


class ThemeBody(BaseModel):
    theme: str
    theme_style: str | None = None
    workspace_path: str | None = None


@router.post("/{guid}/theme")
async def set_theme(guid: str, body: ThemeBody, db: AsyncSession = Depends(get_db)):
    """Set the theme and art style for a desktop, enabling AI prompt generation."""
    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == guid)
    )).scalar_one_or_none()

    if not desktop:
        from app.services.desktop_detector import get_desktops as _get_desktops
        infos = {d.guid: d for d in _get_desktops()}
        info = infos.get(guid)
        if not info:
            raise HTTPException(status_code=404, detail="Desktop GUID not found")
        desktop = Desktop(guid=info.guid, name=info.name, display_order=info.index)
        db.add(desktop)
        await db.flush()

    desktop.theme = body.theme.strip()
    desktop.theme_style = body.theme_style.strip() if body.theme_style else None
    desktop.workspace_path = body.workspace_path.strip() if body.workspace_path else None
    await db.commit()
    return {
        "guid": guid,
        "theme": desktop.theme,
        "theme_style": desktop.theme_style,
        "workspace_path": desktop.workspace_path,
    }


class RefineThemeBody(BaseModel):
    instruction: str


@router.post("/{guid}/theme/refine")
async def refine_theme(guid: str, body: RefineThemeBody, db: AsyncSession = Depends(get_db)):
    """Use Claude to create or update the desktop theme from a natural-language instruction."""
    from app.services.prompt_generator import refine_theme as _refine_theme

    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == guid)
    )).scalar_one_or_none()

    current_theme = desktop.theme if desktop else None

    new_theme = await _refine_theme(current_theme, body.instruction.strip())
    if new_theme is None:
        raise HTTPException(status_code=502, detail="Claude did not return a theme. Check that the Claude CLI is configured.")

    if not desktop:
        from app.services.desktop_detector import get_desktops as _get_desktops
        infos = {d.guid: d for d in _get_desktops()}
        info = infos.get(guid)
        if not info:
            raise HTTPException(status_code=404, detail="Desktop GUID not found")
        desktop = Desktop(guid=info.guid, name=info.name, display_order=info.index)
        db.add(desktop)
        await db.flush()

    desktop.theme = new_theme
    await db.commit()
    return {"guid": guid, "theme": new_theme}


@router.delete("/{guid}/theme")
async def clear_theme(guid: str, db: AsyncSession = Depends(get_db)):
    """Clear the theme for a desktop, reverting to manual prompt mode."""
    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == guid)
    )).scalar_one_or_none()
    if not desktop:
        raise HTTPException(status_code=404, detail="Desktop not found")
    desktop.theme = None
    desktop.theme_style = None
    await db.commit()
    return {"guid": guid, "theme": None}


# ── Monitor config endpoints ──────────────────────────────────────────────────

@monitors_router.get("/monitors")
async def list_monitors():
    """Return all currently connected physical monitors."""
    from app.services.monitor_detector import get_monitors
    monitors = await asyncio.to_thread(get_monitors)
    return [{"index": m.index, "device_path": m.device_path, "width": m.width, "height": m.height, "current_wallpaper": m.current_wallpaper} for m in monitors]


@router.get("/{guid}/monitors")
async def get_desktop_monitors(guid: str, db: AsyncSession = Depends(get_db)):
    """Return monitor config for a desktop, merged with detected monitors."""
    from app.services.monitor_detector import get_monitors

    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == guid)
    )).scalar_one_or_none()

    detected = await asyncio.to_thread(get_monitors)

    configs_map: dict[str, MonitorConfig] = {}
    wallpaper_mode = "repeated"
    if desktop:
        wallpaper_mode = desktop.wallpaper_mode or "repeated"
        cfg_rows = (await db.execute(
            select(MonitorConfig).where(MonitorConfig.desktop_id == desktop.id)
        )).scalars().all()
        configs_map = {c.monitor_device_path: c for c in cfg_rows}

    monitors = []
    for mon in detected:
        cfg = configs_map.get(mon.device_path)
        monitors.append({
            "monitor_device_path": mon.device_path,
            "monitor_index": mon.index,
            "width": mon.width,
            "height": mon.height,
            "mode": cfg.mode if cfg else "shared",
        })

    return {"monitors": monitors}


class MonitorConfigItem(BaseModel):
    monitor_device_path: str
    monitor_index: int
    mode: str = "shared"  # "off" | "individual" | "shared"


class MonitorConfigBody(BaseModel):
    monitors: list[MonitorConfigItem]


@router.put("/{guid}/monitors")
async def update_desktop_monitors(
    guid: str,
    body: MonitorConfigBody,
    db: AsyncSession = Depends(get_db),
):
    """Save per-monitor mode config for a desktop."""
    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == guid)
    )).scalar_one_or_none()

    if not desktop:
        infos = {d.guid: d for d in get_desktops()}
        info = infos.get(guid)
        if not info:
            raise HTTPException(status_code=404, detail="Desktop GUID not found")
        desktop = Desktop(guid=info.guid, name=info.name, display_order=info.index)
        db.add(desktop)
        await db.flush()

    # Replace all monitor configs with the submitted list
    await db.execute(
        delete(MonitorConfig).where(MonitorConfig.desktop_id == desktop.id)
    )
    for item in body.monitors:
        mode = item.mode if item.mode in ("off", "individual", "shared") else "shared"
        db.add(MonitorConfig(
            desktop_id=desktop.id,
            monitor_device_path=item.monitor_device_path,
            monitor_index=item.monitor_index,
            disabled=(mode == "off"),
            mode=mode,
        ))

    await db.commit()
    return {"saved": len(body.monitors)}
