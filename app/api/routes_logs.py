from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database.connection import get_db
from app.database.models import PublishLog, Video, TargetChat, Thumbnail, CompressJob, JobStatus

router = APIRouter()


@router.get("/logs")
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    success: bool = Query(None),
    search: str = Query(None),
    chat_id: int = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(PublishLog).order_by(PublishLog.published_at.desc())

    if success is not None:
        q = q.where(PublishLog.success == success)

    if search:
        # Search by filename via video join
        video_subq = select(Video.id).where(Video.filename.ilike(f"%{search}%")).subquery()
        q = q.where(PublishLog.video_id.in_(video_subq))

    if chat_id:
        q = q.where(PublishLog.target_chat_id == chat_id)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            q = q.where(PublishLog.published_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            q = q.where(PublishLog.published_at <= dt_to)
        except ValueError:
            pass

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    items = []
    # Batch load related entities
    video_ids = [log.video_id for log in rows if log.video_id]
    chat_ids = [log.target_chat_id for log in rows if log.target_chat_id]

    videos = {}
    if video_ids:
        vrows = (await db.execute(select(Video).where(Video.id.in_(video_ids)))).scalars().all()
        videos = {v.id: v for v in vrows}

    chats = {}
    if chat_ids:
        crows = (await db.execute(select(TargetChat).where(TargetChat.chat_id.in_(chat_ids)))).scalars().all()
        chats = {c.chat_id: c for c in crows}

    # Batch load latest thumbnails per video
    thumb_map = {}
    if video_ids:
        from sqlalchemy import distinct
        subq = select(
            Thumbnail.video_id, func.max(Thumbnail.id).label('max_id')
        ).where(Thumbnail.video_id.in_(video_ids)).group_by(Thumbnail.video_id).subquery()
        trows = (await db.execute(
            select(Thumbnail).join(subq, Thumbnail.id == subq.c.max_id)
        )).scalars().all()
        thumb_map = {t.video_id: t.id for t in trows}

    # Batch load latest compress ratios
    ratio_map = {}
    if video_ids:
        csub = select(
            CompressJob.video_id, func.max(CompressJob.id).label('max_id')
        ).where(
            CompressJob.video_id.in_(video_ids), CompressJob.status == JobStatus.done
        ).group_by(CompressJob.video_id).subquery()
        crows = (await db.execute(
            select(CompressJob).join(csub, CompressJob.id == csub.c.max_id)
        )).scalars().all()
        ratio_map = {c.video_id: c.compression_ratio for c in crows if c.compression_ratio}

    for log in rows:
        video = videos.get(log.video_id) if log.video_id else None
        tc = chats.get(log.target_chat_id) if log.target_chat_id else None
        chat_name = tc.chat_name if tc else str(log.target_chat_id or '')

        items.append({
            "id": log.id,
            "video_id": log.video_id,
            "filename": video.filename if video else "Unknown",
            "target_chat_id": log.target_chat_id,
            "target_chat_name": chat_name,
            "thumb_message_id": log.thumb_message_id,
            "video_message_id": log.video_message_id,
            "success": log.success,
            "error_msg": log.error_msg,
            "retry_count": log.retry_count,
            "published_at": log.published_at.isoformat() if log.published_at else None,
            "thumbnail_id": thumb_map.get(log.video_id) if log.video_id else None,
            "size": video.size_bytes if video else None,
            "original_size": video.size_bytes if video else None,
            "compression_ratio": ratio_map.get(log.video_id) if log.video_id else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/logs/{log_id}")
async def get_log(log_id: int, db: AsyncSession = Depends(get_db)):
    log = await db.get(PublishLog, log_id)
    if not log:
        raise HTTPException(404, f"Log {log_id} not found")
    video = await db.get(Video, log.video_id) if log.video_id else None
    return {
        "id": log.id,
        "video_id": log.video_id,
        "filename": video.filename if video else "Unknown",
        "target_chat_id": log.target_chat_id,
        "thumb_message_id": log.thumb_message_id,
        "video_message_id": log.video_message_id,
        "success": log.success,
        "error_msg": log.error_msg,
        "retry_count": log.retry_count,
        "published_at": log.published_at.isoformat() if log.published_at else None,
    }


@router.delete("/logs/{log_id}")
async def delete_log(log_id: int, db: AsyncSession = Depends(get_db)):
    log = await db.get(PublishLog, log_id)
    if not log:
        raise HTTPException(404, f"Log {log_id} not found")
    await db.delete(log)
    await db.commit()
    return {"ok": True}
