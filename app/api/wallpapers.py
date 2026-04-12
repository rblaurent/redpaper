from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Desktop, Prompt, Wallpaper, get_db
from app.services.wallpaper_setter import set_wallpaper_for_desktop

router = APIRouter(prefix="/api", tags=["wallpapers"])


# ── Wallpapers ────────────────────────────────────────────────────────────────

@router.get("/wallpapers")
async def list_wallpapers(
    desktop_guid: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    q = select(Wallpaper).order_by(Wallpaper.generated_at.desc())
    if desktop_guid:
        desktop = (await db.execute(
            select(Desktop).where(Desktop.guid == desktop_guid)
        )).scalar_one_or_none()
        if not desktop:
            return []
        q = q.where(Wallpaper.desktop_id == desktop.id)

    q = q.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(q)).scalars().all()

    return [
        {
            "id": w.id,
            "desktop_id": w.desktop_id,
            "file_path": w.file_path,
            "generated_at": w.generated_at.isoformat(),
            "is_active": w.is_active,
        }
        for w in rows
    ]


@router.post("/wallpapers/{wallpaper_id}/apply")
async def apply_wallpaper(wallpaper_id: int, db: AsyncSession = Depends(get_db)):
    """Re-apply a historical wallpaper to its desktop."""
    wp = (await db.execute(
        select(Wallpaper).where(Wallpaper.id == wallpaper_id)
    )).scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Wallpaper not found")

    desktop = (await db.execute(
        select(Desktop).where(Desktop.id == wp.desktop_id)
    )).scalar_one_or_none()
    if not desktop:
        raise HTTPException(status_code=404, detail="Desktop not found")

    # Update active flag
    await db.execute(
        update(Wallpaper)
        .where(Wallpaper.desktop_id == desktop.id)
        .values(is_active=False)
    )
    wp.is_active = True
    await db.commit()

    set_wallpaper_for_desktop(desktop.guid, wp.file_path)
    return {"status": "applied", "file_path": wp.file_path}


# ── Prompts ───────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    desktop_guid: str
    text: str


@router.get("/prompts")
async def list_prompts(
    desktop_guid: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Prompt).order_by(Prompt.created_at.desc())
    if desktop_guid:
        desktop = (await db.execute(
            select(Desktop).where(Desktop.guid == desktop_guid)
        )).scalar_one_or_none()
        if not desktop:
            return []
        q = q.where(Prompt.desktop_id == desktop.id)

    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": p.id,
            "desktop_id": p.desktop_id,
            "text": p.text,
            "created_at": p.created_at.isoformat(),
            "is_active": p.is_active,
        }
        for p in rows
    ]


@router.post("/prompts")
async def create_prompt(body: PromptCreate, db: AsyncSession = Depends(get_db)):
    """Set a new active prompt for a desktop."""
    desktop = (await db.execute(
        select(Desktop).where(Desktop.guid == body.desktop_guid)
    )).scalar_one_or_none()

    if not desktop:
        # Auto-create desktop record
        from app.services.desktop_detector import get_desktops
        infos = {d.guid: d for d in get_desktops()}
        info = infos.get(body.desktop_guid)
        if not info:
            raise HTTPException(status_code=404, detail="Desktop GUID not found")
        desktop = Desktop(guid=info.guid, name=info.name, display_order=info.index)
        db.add(desktop)
        await db.flush()

    # Deactivate previous prompts
    await db.execute(
        update(Prompt)
        .where(Prompt.desktop_id == desktop.id)
        .values(is_active=False)
    )

    prompt = Prompt(desktop_id=desktop.id, text=body.text, is_active=True)
    db.add(prompt)
    await db.commit()
    return {"id": prompt.id, "text": prompt.text}
