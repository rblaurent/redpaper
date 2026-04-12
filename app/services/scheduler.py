"""
APScheduler wrapper for daily wallpaper generation.
Exposes start/stop/trigger functions used by main.py and the API.
"""
import json
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
JOB_ID = "daily_generate"

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


def start_scheduler():
    """Start the scheduler with the daily generation job."""
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
    scheduler.start()
    logger.info("Scheduler started with cron: %s", _load_cron())


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
