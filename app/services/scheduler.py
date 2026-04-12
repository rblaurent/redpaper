"""
APScheduler wrapper for daily wallpaper generation and ComfyUI availability polling.
Exposes start/stop/trigger functions used by main.py and the API.
"""
import json
import logging
import os
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
JOB_ID = "daily_generate"
POLL_JOB_ID = "comfyui_poll"
SWITCH_JOB_ID = "desktop_switch_watcher"
POLL_INTERVAL_MINUTES = 5

_last_desktop_guid: str | None = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_cron() -> str:
    try:
        with open(os.path.join(BASE_DIR, "config.json")) as f:
            cfg = json.load(f)
        return cfg.get("schedule_cron", "0 8 * * *")
    except Exception:
        return "0 8 * * *"


def _make_trigger() -> CronTrigger:
    cron = _load_cron()
    parts = cron.split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
        return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)
    return CronTrigger(hour=8, minute=0)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def _watch_desktop_switch():
    """
    Runs every 2 seconds. Detects virtual desktop switches and immediately
    applies the active wallpaper(s) for the newly-active desktop via COM.
    This is how inactive-desktop wallpapers get applied — no keyboard switching needed.
    """
    global _last_desktop_guid
    import asyncio

    try:
        from app.services.desktop_detector import get_current_desktop_guid
        current_guid = get_current_desktop_guid()   # single registry read, ~1 µs — no thread needed
    except Exception:
        return

    if not current_guid or current_guid == _last_desktop_guid:
        return

    prev = _last_desktop_guid
    _last_desktop_guid = current_guid

    if prev is None:
        # First poll after startup — apply wallpapers for the current desktop
        # so per-monitor assignments are restored (Windows registry only stores
        # one path per desktop, so all monitors show the same image after reboot).
        logger.info("Startup: applying wallpapers for current desktop %s", current_guid)

    logger.info("Desktop switched → %s, applying wallpapers", current_guid)

    try:
        from sqlalchemy import select
        from app.database import AsyncSessionLocal, Desktop, Wallpaper
        from app.services.wallpaper_setter import set_wallpapers_for_desktop

        async with AsyncSessionLocal() as session:
            desktop = (await session.execute(
                select(Desktop).where(Desktop.guid == current_guid)
            )).scalar_one_or_none()
            if not desktop:
                return

            wallpapers = (await session.execute(
                select(Wallpaper).where(
                    Wallpaper.desktop_id == desktop.id,
                    Wallpaper.is_active == True,
                )
            )).scalars().all()
            if not wallpapers:
                return

            pairs = [(wp.monitor_device_path, wp.file_path) for wp in wallpapers]

        await asyncio.to_thread(set_wallpapers_for_desktop, current_guid, pairs)
        logger.info("Applied %d wallpaper(s) for desktop %s after switch", len(pairs), current_guid)

    except Exception as exc:
        logger.warning("Desktop-switch wallpaper apply failed: %s", exc)


async def _poll_and_generate():
    """
    Runs every POLL_INTERVAL_MINUTES minutes.
    If ComfyUI is reachable and we haven't generated today yet, trigger generation.
    This catches up when ComfyUI wasn't running at the scheduled time.
    """
    from app.services import comfyui_process
    from app.services.generator import generate_all, last_generation_date

    if not await comfyui_process.is_running():
        return

    last = await last_generation_date()
    if last is not None and last >= date.today():
        return  # Already generated today

    logger.info("Poll: ComfyUI is up and no generation today — triggering catch-up generation")
    await generate_all()


def start_scheduler():
    """Start the scheduler with the daily generation job and the availability poll."""
    from app.services.generator import generate_all

    scheduler = get_scheduler()
    if scheduler.running:
        return

    scheduler.add_job(
        generate_all,
        trigger=_make_trigger(),
        id=JOB_ID,
        replace_existing=True,
        name="Daily wallpaper generation",
    )

    scheduler.add_job(
        _poll_and_generate,
        trigger=IntervalTrigger(minutes=POLL_INTERVAL_MINUTES),
        id=POLL_JOB_ID,
        replace_existing=True,
        name="ComfyUI availability poll",
    )

    scheduler.add_job(
        _watch_desktop_switch,
        trigger=IntervalTrigger(seconds=2),
        id=SWITCH_JOB_ID,
        replace_existing=True,
        name="Desktop switch watcher",
    )

    scheduler.start()
    logger.info("Scheduler started — cron: %s, poll every %dm", _load_cron(), POLL_INTERVAL_MINUTES)


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


async def trigger_now():
    """Trigger an immediate generation run."""
    from app.services.generator import generate_all
    return await generate_all()


def get_next_run() -> str | None:
    scheduler = get_scheduler()
    if not scheduler.running:
        return None
    job = scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def update_cron(cron_expr: str):
    """Replace the schedule cron expression at runtime."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.reschedule_job(JOB_ID, trigger=_make_trigger())
    logger.info("Schedule updated to: %s", cron_expr)
