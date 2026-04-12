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
    """Return all virtual desktops with their currently active wallpaper."""
    detected = get_desktops()
    current_guid = get_current_desktop_guid()
    result = []

    for info in detected:
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
    return [{"index": m.index, "device_path": m.device_path} for m in monitors]


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
            "disabled": cfg.disabled if cfg else False,
        })

    return {"wallpaper_mode": wallpaper_mode, "monitors": monitors}


class MonitorConfigItem(BaseModel):
    monitor_device_path: str
    monitor_index: int
    disabled: bool = False


class MonitorConfigBody(BaseModel):
    mode: str = "repeated"
    monitors: list[MonitorConfigItem]


@router.put("/{guid}/monitors")
async def update_desktop_monitors(
    guid: str,
    body: MonitorConfigBody,
    db: AsyncSession = Depends(get_db),
):
    """Upsert monitor config for a desktop and set its wallpaper mode."""
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

    desktop.wallpaper_mode = body.mode if body.mode in ("repeated", "original") else "repeated"

    # Replace all monitor configs with the submitted list
    await db.execute(
        delete(MonitorConfig).where(MonitorConfig.desktop_id == desktop.id)
    )
    for item in body.monitors:
        db.add(MonitorConfig(
            desktop_id=desktop.id,
            monitor_device_path=item.monitor_device_path,
            monitor_index=item.monitor_index,
            disabled=item.disabled,
        ))

    await db.commit()
    return {"saved": len(body.monitors), "mode": desktop.wallpaper_mode}
