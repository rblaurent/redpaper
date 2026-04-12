from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Desktop, Prompt, Wallpaper, get_db
from app.services.desktop_detector import get_desktops, get_current_desktop_guid

router = APIRouter(prefix="/api/desktops", tags=["desktops"])


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

        active_wallpaper = None
        active_prompt = None
        if desktop_row:
            wp = (await db.execute(
                select(Wallpaper)
                .where(Wallpaper.desktop_id == desktop_row.id, Wallpaper.is_active == True)
                .order_by(Wallpaper.generated_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if wp:
                active_wallpaper = {
                    "id": wp.id,
                    "file_path": wp.file_path,
                    "generated_at": wp.generated_at.isoformat(),
                }

            pr = (await db.execute(
                select(Prompt)
                .where(Prompt.desktop_id == desktop_row.id, Prompt.is_active == True)
                .order_by(Prompt.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if pr:
                active_prompt = pr.text

        result.append({
            "index": info.index,
            "guid": info.guid,
            "name": info.name,
            "is_current": info.guid == current_guid,
            "active_wallpaper": active_wallpaper,
            "active_prompt": active_prompt,
        })

    return result
