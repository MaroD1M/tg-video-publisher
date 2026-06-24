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
    for log in rows:
        video = await db.get(Video, log.video_id) if log.video_id else None
        chat_name = str(log.target_chat_id)
        if log.target_chat_id:
            tc = await db.get(TargetChat, log.target_chat_id)
            if tc:
                chat_name = tc.chat_name or chat_name

        thumb_id = None
        if log.video_id:
            thumb_row = (await db.execute(
                select(Thumbnail.id).where(Thumbnail.video_id == log.video_id)
                .order_by(Thumbnail.id.desc()).limit(1)
            )).scalar_one_or_none()
            if thumb_row:
                thumb_id = thumb_row

        ratio = None
        if log.video_id:
            comp = (await db.execute(
                select(CompressJob).where(
                    CompressJob.video_id == log.video_id, CompressJob.status == JobStatus.done
                ).order_by(CompressJob.id.desc()).limit(1)
            )).scalar_one_or_none()
            if comp and comp.compression_ratio:
                ratio = comp.compression_ratio

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
            "thumbnail_id": thumb_id,
            "size": video.size_bytes if video else None,
            "original_size": video.size_bytes if video else None,
            "compression_ratio": ratio,
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
