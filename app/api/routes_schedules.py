import datetime
import random
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update as sql_update

from app.database.connection import get_db
from app.database.models import (
    Video, Thumbnail, CompressJob, JobStatus,
    Schedule, ScheduleItem, PublishLog, TargetChat,
    ItemStatus, QueueStrategy,
)
from app.modules.publisher import publish_video
from app.modules.thumbnails import generate_thumbnail
from app.utils.helpers import get_setting
from app.utils.cron_preview import get_next_run_times

router = APIRouter()


async def _get_chat_name(chat_id, db: AsyncSession) -> str:
    if chat_id is None:
        return "-"
    try:
        tc = await db.get(TargetChat, chat_id)
        return tc.chat_name if tc else str(chat_id)
    except Exception:
        return str(chat_id) if chat_id else "-"


@router.get("/cron/preview")
async def preview_cron(expr: str = Query("0 20 * * *")):
    return {"times": get_next_run_times(expr)}


# ── Schedule CRUD ──

@router.get("/schedules")
async def list_schedules(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Schedule).order_by(Schedule.created_at.desc())
    )).scalars().all()

    items = []
    for s in rows:
        item_count = (await db.execute(
            select(func.count(ScheduleItem.id)).where(ScheduleItem.schedule_id == s.id)
        )).scalar() or 0
        items.append({
            "id": s.id,
            "name": s.name,
            "target_chat_id": s.target_chat_id,
            "target_chat_name": await _get_chat_name(s.target_chat_id, db),
            "cron_expr": s.cron_expr,
            "queue_strategy": s.queue_strategy.value if s.queue_strategy else "sequential",
            "enabled": s.enabled,
            "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "item_count": item_count,
            "thumb_caption_template": s.thumb_caption_template or "",
            "video_caption_template": s.video_caption_template or "",
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return {"items": items}


@router.post("/schedules")
async def create_schedule(body: dict, db: AsyncSession = Depends(get_db)):
    cron_expr = body.get("cron_expr", "0 20 * * *")
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger.from_crontab(cron_expr)
    except Exception:
        raise HTTPException(422, f"无效的 Cron 表达式: {cron_expr}")

    schedule = Schedule(
        name=body.get("name", "Unnamed"),
        target_chat_id=int(body.get("target_chat_id", 0)),
        cron_expr=cron_expr,
        queue_strategy=QueueStrategy(body.get("queue_strategy", "sequential")),
        thumb_caption_template=body.get("thumb_caption_template", ""),
        video_caption_template=body.get("video_caption_template", ""),
        enabled=True,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    # Also schedule via APScheduler
    try:
        from app.modules.scheduler import schedule_job
        await schedule_job(schedule)
    except Exception:
        pass

    return {"ok": True, "id": schedule.id}


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    s = await db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")

    for field in ["name", "cron_expr", "queue_strategy", "target_chat_id", "thumb_caption_template", "video_caption_template"]:
        if field in body:
            val = body[field]
            if field == "target_chat_id":
                val = int(val)
            if field == "queue_strategy" and isinstance(val, str):
                val = QueueStrategy(val)
            if field == "cron_expr":
                try:
                    from apscheduler.triggers.cron import CronTrigger
                    CronTrigger.from_crontab(val)
                except Exception:
                    raise HTTPException(422, f"无效的 Cron 表达式: {val}")
            setattr(s, field, val)
    if "enabled" in body:
        s.enabled = body["enabled"]

    await db.commit()
    return {"ok": True}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    await db.delete(s)
    await db.commit()
    return {"ok": True}


# ── Schedule Items (video queue) ──

@router.get("/schedules/{schedule_id}/items")
async def get_schedule_items(schedule_id: int, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ScheduleItem)
        .where(ScheduleItem.schedule_id == schedule_id)
        .order_by(ScheduleItem.sort_order)
    )).scalars().all()

    items = []
    for r in rows:
        video = await db.get(Video, r.video_id)
        items.append({
            "id": r.id,
            "video_id": r.video_id,
            "video_name": video.filename if video else "Unknown",
            "sort_order": r.sort_order,
            "status": r.status.value if r.status else "queued",
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "error_msg": r.error_msg,
        })

    return {"items": items}


@router.put("/schedules/{schedule_id}/items")
async def update_schedule_items(
    schedule_id: int,
    item_ids: list[int],
    action: str = Query("set"),
    db: AsyncSession = Depends(get_db),
):
    """
    action:
      - "set": replace entire queue with these video IDs (in order)
      - "add": add these video IDs to the queue
      - "remove": remove these item IDs from the queue
    """
    if action == "remove":
        for iid in item_ids:
            item = await db.get(ScheduleItem, iid)
            if item and item.schedule_id == schedule_id:
                await db.delete(item)
        await db.commit()
        return {"ok": True}

    if action == "set":
        # Delete existing
        await db.execute(
            sql_update(ScheduleItem)
            .where(ScheduleItem.schedule_id == schedule_id)
            .values(status=ItemStatus.skipped)
        )
        # Actually delete non-published
        existing = (await db.execute(
            select(ScheduleItem).where(
                ScheduleItem.schedule_id == schedule_id,
                ScheduleItem.status.notin_([ItemStatus.published])
            )
        )).scalars().all()
        for e in existing:
            await db.delete(e)

    for idx, vid in enumerate(item_ids):
        # Skip already published in this schedule
        already = (await db.execute(
            select(ScheduleItem).where(
                ScheduleItem.schedule_id == schedule_id,
                ScheduleItem.video_id == vid,
                ScheduleItem.status == ItemStatus.published,
            )
        )).scalar_one_or_none()
        if already:
            continue

        item = ScheduleItem(
            schedule_id=schedule_id,
            video_id=vid,
            sort_order=idx,
            status=ItemStatus.queued,
        )
        db.add(item)

    await db.commit()
    return {"ok": True}


# ── Trigger / Publish ──

@router.post("/schedules/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")

    return await _publish_next_from_schedule(s, db)


async def _publish_next_from_schedule(schedule: Schedule, db: AsyncSession) -> dict:
    """Dequeue next item and create an async PublishTask."""
    q = select(ScheduleItem).where(
        ScheduleItem.schedule_id == schedule.id,
        ScheduleItem.status == ItemStatus.queued,
    ).order_by(ScheduleItem.sort_order)

    if schedule.queue_strategy == QueueStrategy.random:
        all_queued = (await db.execute(q)).scalars().all()
        item = random.choice(all_queued) if all_queued else None
    else:
        item = (await db.execute(q.limit(1))).scalar_one_or_none()

    if not item:
        return {"ok": False, "message": "No queued items"}

    video = await db.get(Video, item.video_id)
    if not video:
        item.status = ItemStatus.failed
        item.error_msg = "Video not found"
        await db.commit()
        return {"ok": False, "message": "Video not found"}

    channel_name = ""
    try:
        channel_name = schedule.name or str(schedule.target_chat_id)
    except Exception:
        pass

    from app.api.routes_publish import enqueue_publish
    tid = await enqueue_publish(
        video_id=video.id,
        channel_id=schedule.target_chat_id,
        channel_name=str(schedule.target_chat_id),
    )

    item.status = ItemStatus.publishing_video
    item.scheduled_at = datetime.datetime.utcnow()
    schedule.last_run_at = datetime.datetime.utcnow()
    await db.commit()

    return {"ok": True, "task_id": tid, "video_name": video.filename}


@router.post("/schedules/{schedule_id}/batch-add")
async def batch_add_to_schedule(schedule_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """Batch add video IDs to a schedule queue."""
    video_ids = data.get("video_ids", [])
    if not video_ids:
        raise HTTPException(400, "video_ids required")

    sched = await db.get(Schedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")

    count = 0
    for vid in video_ids:
        existing = (await db.execute(
            select(ScheduleItem).where(
                ScheduleItem.schedule_id == schedule_id,
                ScheduleItem.video_id == vid,
                ScheduleItem.status == ItemStatus.queued,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        current_count = (await db.execute(
            select(func.count()).select_from(ScheduleItem).where(
                ScheduleItem.schedule_id == schedule_id,
                ScheduleItem.status == ItemStatus.queued,
            )
        )).scalar() or 0

        db.add(ScheduleItem(
            schedule_id=schedule_id, video_id=vid,
            sort_order=current_count, status=ItemStatus.queued,
        ))
        count += 1

    await db.commit()
    return {"ok": True, "added": count}
