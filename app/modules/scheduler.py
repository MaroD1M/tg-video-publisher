from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from app.config import CONFIG_DIR
from app.database.connection import async_session
from app.database.models import Schedule, ScheduleItem, ItemStatus

scheduler: AsyncIOScheduler | None = None
_schedule_jobs: dict[int, str] = {}  # schedule_id -> job_id


def get_scheduler() -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        jobstores = {
            "default": SQLAlchemyJobStore(
                url=f"sqlite:///{CONFIG_DIR}/scheduler.db"
            )
        }
        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone="Asia/Shanghai",
            job_defaults={
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 600,
            },
        )
    return scheduler


async def start_scheduler():
    global scheduler, _schedule_jobs
    sched = get_scheduler()
    if not sched.running:
        sched.start()

    _schedule_jobs.clear()

    # Load existing schedules and add jobs
    async with async_session() as db:
        from sqlalchemy import select
        rows = (await db.execute(
            select(Schedule).where(Schedule.enabled == True)
        )).scalars().all()

        for s in rows:
            await schedule_job(s)


async def schedule_job(schedule: Schedule):
    sched = get_scheduler()
    job_id = f"sch_{schedule.id}"

    # Remove existing job if any
    if job_id in _schedule_jobs:
        try:
            sched.remove_job(_schedule_jobs[job_id])
        except Exception:
            pass

    if not schedule.enabled:
        return

    async def job_func():
        async with async_session() as db:
            from app.modules.schedule_executor import publish_next_from_schedule
            s = await db.get(Schedule, schedule.id)
            if s:
                await publish_next_from_schedule(s, db)

    try:
        trigger = CronTrigger.from_crontab(schedule.cron_expr)
        sched.add_job(
            job_func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _schedule_jobs[schedule.id] = job_id
    except Exception as e:
        import logging
        logging.getLogger("tgvp.scheduler").warning(
            f"Invalid cron for schedule {schedule.id}: {schedule.cron_expr} — {e}"
        )


async def remove_schedule_job(schedule_id: int):
    sched = get_scheduler()
    job_id = f"sch_{schedule_id}"
    try:
        sched.remove_job(job_id)
    except Exception:
        pass
    _schedule_jobs.pop(schedule_id, None)


async def trigger_now(schedule_id: int):
    """Manually trigger a schedule immediately."""
    async with async_session() as db:
        s = await db.get(Schedule, schedule_id)
        if s:
            from app.modules.schedule_executor import publish_next_from_schedule
            return await publish_next_from_schedule(s, db)
    return {"ok": False, "message": "Schedule not found"}
