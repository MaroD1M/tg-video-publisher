import datetime
import random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Schedule, ScheduleItem, Video, ItemStatus, QueueStrategy


async def publish_next_from_schedule(schedule: Schedule, db: AsyncSession) -> dict:
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
        channel_name=channel_name,
        schedule_id=schedule.id,
    )

    item.status = ItemStatus.publishing_video
    item.scheduled_at = datetime.datetime.utcnow()
    schedule.last_run_at = datetime.datetime.utcnow()
    await db.commit()

    return {"ok": True, "task_id": tid, "video_name": video.filename}
