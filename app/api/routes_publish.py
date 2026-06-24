import asyncio
import datetime
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database.connection import get_db, async_session
from app.database.models import Video, PublishTask, PublishTaskStatus, PublishLog, Thumbnail, CompressJob, JobStatus

router = APIRouter()

publish_queue: asyncio.Queue = asyncio.Queue()
worker_task: Optional[asyncio.Task] = None
_worker_lock = asyncio.Lock()


async def broadcast_publish(msg: dict):
    from app.api.websocket import active_connections
    data = json.dumps(msg)
    for ws in list(active_connections):
        try:
            await ws.send_text(data)
        except Exception:
            pass


async def _publish_worker():
    while True:
        try:
            task_data = await publish_queue.get()
            # Check if task is paused before executing
            async with async_session() as db:
                task = await db.get(PublishTask, task_data["task_id"])
                if task and task.is_paused:
                    # Re-enqueue paused tasks instead of losing them
                    await asyncio.sleep(1)
                    await publish_queue.put(task_data)
                    continue  # Skip; will be re-checked on next deque
            await _execute_publish(task_data["task_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            import logging
            logging.getLogger("tgvp.publish").error(f"PublishWorker: {e}", exc_info=True)


async def _execute_publish(task_id: int):
    start_time = time.time()
    cancel_event = asyncio.Event()
    step_logs = []
    video_name = "Unknown"
    channel_name = ""

    # Load task data
    async with async_session() as db:
        task = await db.get(PublishTask, task_id)
        if not task:
            import logging
            logging.getLogger("tgvp.publish").error(f"Publish task {task_id} not found, skipping")
            return
        if task.status != PublishTaskStatus.queued:
            return
        task.status = PublishTaskStatus.running
        task.step_log = json.dumps(step_logs)
        await db.commit()

        video = await db.get(Video, task.video_id) if task.video_id else None
        channel_id = task.channel_id
        channel_name = task.channel_name or str(channel_id or 0)
        video_name = video.filename if video else "Unknown"

    # Cancel watcher — polls DB for cancellation flag
    async def _cancel_watcher():
        while not cancel_event.is_set():
            async with async_session() as db:
                t = await db.get(PublishTask, task_id)
                if t and t.status == PublishTaskStatus.cancelled:
                    cancel_event.set()
            await asyncio.sleep(1)

    cancel_watcher_task = asyncio.create_task(_cancel_watcher())

    try:
        # Step 1: Resolve local files and thumbnail
        thumb_start = time.time()
        from app.modules.publisher import ensure_thumbnail, resolve_video_path

        # Resolve correct width/height: use compress target if compressed, else original
        pub_width = 0
        pub_height = 0
        thumb_tpl = ""
        video_tpl = ""

        async with async_session() as db:
            video_obj = await db.get(Video, task.video_id) if task.video_id else None
            if not video_obj:
                raise Exception("Video not found")
            vpath, vsize = await resolve_video_path(video_obj)
            thumb_path = await ensure_thumbnail(video_obj, vpath, db)
            size_bytes = video_obj.size_bytes

            thumb_row = (await db.execute(
                select(Thumbnail.id).where(Thumbnail.video_id == video_obj.id)
                .order_by(Thumbnail.id.desc()).limit(1)
            )).scalar_one_or_none()
            thumb_id = thumb_row

            # Resolve dimensions: use compress target if video was compressed
            pub_width = video_obj.width or 0
            pub_height = video_obj.height or 0
            if vpath != video_obj.filepath:
                from app.database.models import CompressJob
                comp_job = (await db.execute(
                    select(CompressJob).where(
                        CompressJob.video_id == video_obj.id,
                        CompressJob.status == JobStatus.done,
                    ).order_by(CompressJob.id.desc()).limit(1)
                )).scalar_one_or_none()
                if comp_job:
                    if comp_job.target_width > 0:
                        pub_width = comp_job.target_width
                    if comp_job.target_height > 0:
                        pub_height = comp_job.target_height

            # Resolve templates: schedule templates take priority over global settings
            if task.schedule_id:
                from app.database.models import Schedule
                sched = await db.get(Schedule, task.schedule_id)
                if sched:
                    thumb_tpl = sched.thumb_caption_template or ""
                    video_tpl = sched.video_caption_template or ""

        elapsed = time.time() - thumb_start
        step_logs.append({"step":"prepare","elapsed":round(elapsed,1),"result":"done"})
        await broadcast_publish({
            "type": "publish_progress", "task_id": task_id, "video_id": task.video_id,
            "video_name": video_name, "channel_name": channel_name,
            "step": "sending", "progress": 10, "elapsed_sec": round(elapsed), "eta_sec": 0,
            "thumbnail_id": thumb_id, "step_logs": step_logs,
        })

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        # Step 2: Publish to Telegram
        from app.modules.publisher import publish_video

        result = await publish_video(
            video_path=vpath, thumb_path=thumb_path, channel_id=channel_id,
            video_filename=video_name, duration_sec=video_obj.duration_sec,
            size_bytes=vsize, original_size_bytes=size_bytes,
            width=pub_width, height=pub_height,
            thumb_template=thumb_tpl,
            video_template=video_tpl,
        )

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        elapsed_total = round(time.time() - start_time)

        if result.get("success"):
            upload_elapsed = time.time() - thumb_start
            upload_speed = round(vsize / upload_elapsed / 1024) if upload_elapsed > 0 and vsize > 0 else 0
            step_logs.append({"step":"send","elapsed":round(upload_elapsed,1),"result":"done","speed_kbs":upload_speed})
            async with async_session() as db:
                task = await db.get(PublishTask, task_id)
                if task:
                    task.status = PublishTaskStatus.done
                    task.progress = 100
                    task.elapsed_sec = elapsed_total
                    task.thumb_message_id = result.get("thumb_message_id")
                    task.video_message_id = result.get("video_message_id")
                    task.channel_name = channel_name or str(channel_id)
                    task.step_log = json.dumps(step_logs)
                    await db.commit()

                db.add(PublishLog(
                    video_id=task.video_id, target_chat_id=channel_id,
                    thumb_message_id=result.get("thumb_message_id"),
                    video_message_id=result.get("video_message_id"),
                    success=True,
                ))
                await db.commit()

            from app.modules.notifier import notify_admin
            await notify_admin(
                f"📤 发布成功: {video_name}\n频道: {channel_name}",
                event_type="publish_done",
                variables={"filename": video_name, "channel": channel_name},
            )

            await broadcast_publish({
                "type": "publish_done", "task_id": task_id, "video_id": task.video_id,
                "video_name": video_name, "channel_name": channel_name,
            })
        else:
            upload_elapsed = time.time() - thumb_start
            upload_speed = round(vsize / upload_elapsed / 1024) if upload_elapsed > 0 and vsize > 0 else 0
            step_logs.append({"step":"send","elapsed":round(upload_elapsed,1),"result":"failed","error":result.get("error","")[:200],"speed_kbs":upload_speed})
            async with async_session() as db:
                task = await db.get(PublishTask, task_id)
                if task:
                    task.status = PublishTaskStatus.failed
                    task.error_log = result.get("error", "")[:500]
                    task.elapsed_sec = elapsed_total
                    task.step_log = json.dumps(step_logs)
                    await db.commit()
            await broadcast_publish({
                "type": "publish_error", "task_id": task_id, "video_id": task.video_id,
                "video_name": video_name, "error": result.get("error", "")[:200],
            })

    except asyncio.CancelledError:
        if not step_logs:
            step_logs = [{"step": "cancelled", "elapsed": round(time.time() - start_time), "result": "cancelled"}]
        async with async_session() as db:
            task = await db.get(PublishTask, task_id)
            if task and task.status == PublishTaskStatus.running:
                task.status = PublishTaskStatus.cancelled
                task.elapsed_sec = round(time.time() - start_time)
                task.step_log = json.dumps(step_logs)
                await db.commit()
        await broadcast_publish({
            "type": "publish_cancelled", "task_id": task_id,
            "video_name": video_name,
        })
    except Exception as e:
        if not step_logs:
            step_logs = [{"step": "error", "elapsed": round(time.time() - start_time), "result": "failed", "error": str(e)[:200]}]
        async with async_session() as db:
            task = await db.get(PublishTask, task_id)
            if task:
                task.status = PublishTaskStatus.failed
                task.error_log = str(e)[:500]
                task.elapsed_sec = round(time.time() - start_time)
                task.step_log = json.dumps(step_logs)
                await db.commit()
        await broadcast_publish({
            "type": "publish_error", "task_id": task_id, "video_id": task.video_id,
            "video_name": video_name, "error": str(e)[:200],
        })
    finally:
        cancel_watcher_task.cancel()


async def enqueue_publish(video_id: int, channel_id: int, channel_name: str = "", schedule_id: int = 0) -> int:
    """Create a PublishTask and enqueue it. Returns the new task id."""
    async with async_session() as db:
        task = PublishTask(
            video_id=video_id, channel_id=channel_id,
            channel_name=channel_name or str(channel_id),
            schedule_id=schedule_id,
            status=PublishTaskStatus.queued,
        )
        db.add(task)
        await db.commit()
        tid = task.id
    await publish_queue.put({"task_id": tid})
    await start_publish_worker()
    return tid


@router.get("/publish")
async def list_publish_tasks(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    q = select(PublishTask).order_by(PublishTask.id.desc())
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.where(PublishTask.status.in_(statuses))
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    count_q = select(func.count()).select_from(PublishTask)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            count_q = count_q.where(PublishTask.status.in_(statuses))
    total = (await db.execute(count_q)).scalar() or 0

    items = []
    if rows:
        video_ids = [t.video_id for t in rows if t.video_id]
        # Batch load videos
        videos = {}
        if video_ids:
            vids = (await db.execute(
                select(Video).where(Video.id.in_(video_ids))
            )).scalars().all()
            videos = {v.id: v for v in vids}
        # Batch load latest thumbnails per video
        thumbs = {}
        if video_ids:
            thumb_rows = (await db.execute(
                select(Thumbnail).where(Thumbnail.video_id.in_(video_ids))
                .order_by(Thumbnail.id.desc())
            )).scalars().all()
            seen = set()
            for t in thumb_rows:
                if t.video_id not in seen:
                    seen.add(t.video_id)
                    thumbs[t.video_id] = t.id
        # Batch load compression ratios
        ratios = {}
        if video_ids:
            comp_rows = (await db.execute(
                select(CompressJob).where(
                    CompressJob.video_id.in_(video_ids),
                    CompressJob.status == JobStatus.done,
                ).order_by(CompressJob.id.desc())
            )).scalars().all()
            seen = set()
            for c in comp_rows:
                if c.video_id not in seen and c.compression_ratio:
                    seen.add(c.video_id)
                    ratios[c.video_id] = c.compression_ratio

        for t in rows:
            video = videos.get(t.video_id)
            thumb_id = thumbs.get(t.video_id) if t.video_id else None
            ratio = ratios.get(t.video_id) if t.video_id else None

            items.append({
                "id": t.id, "video_id": t.video_id, "video_name": video.filename if video else "",
                "channel_id": t.channel_id, "channel_name": t.channel_name or str(t.channel_id or ""),
                "status": t.status.value if t.status else "queued",
                "progress": t.progress, "elapsed_sec": t.elapsed_sec, "eta_sec": t.eta_sec,
                "compression_ratio": ratio, "error_log": t.error_log,
                "thumbnail_id": thumb_id,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "sort_order": t.sort_order, "is_paused": t.is_paused,
                "step_log": json.loads(t.step_log) if t.step_log else [],
            })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/publish/{task_id}/cancel")
async def cancel_publish(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in (PublishTaskStatus.queued, PublishTaskStatus.running, PublishTaskStatus.uploading):
        raise HTTPException(400, "Task is not active")
    task.status = PublishTaskStatus.cancelled
    await db.commit()
    return {"ok": True}


@router.post("/publish/{task_id}/retry")
async def retry_publish(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in (PublishTaskStatus.failed, PublishTaskStatus.cancelled, PublishTaskStatus.done):
        raise HTTPException(400, "Task cannot be retried")
    task.status = PublishTaskStatus.queued
    task.progress = 0
    task.error_log = ""
    task.step_log = None
    task.elapsed_sec = 0
    task.eta_sec = 0
    await db.commit()
    await publish_queue.put({"task_id": task.id})
    await start_publish_worker()
    return {"ok": True}


@router.post("/publish/{task_id}/pause")
async def pause_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != PublishTaskStatus.queued:
        raise HTTPException(400, "Only queued tasks can be paused")
    task.is_paused = True
    await db.commit()
    return {"ok": True}


@router.post("/publish/{task_id}/resume")
async def resume_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not task.is_paused:
        raise HTTPException(400, "Task is not paused")
    task.is_paused = False
    await db.commit()
    await publish_queue.put({"task_id": task.id})
    await start_publish_worker()
    return {"ok": True}


@router.post("/publish/{task_id}/reorder")
async def reorder_task(task_id: int, direction: str = Query("up"), db: AsyncSession = Depends(get_db)):
    """Swap sort_order with adjacent task (up=earlier, down=later)."""
    task = await db.get(PublishTask, task_id)
    if not task or task.status != PublishTaskStatus.queued:
        raise HTTPException(400, "Only queued tasks can be reordered")
    
    if direction == "up":
        adjacent = (await db.execute(
            select(PublishTask).where(
                PublishTask.status == PublishTaskStatus.queued,
                PublishTask.sort_order < task.sort_order,
            ).order_by(PublishTask.sort_order.desc()).limit(1)
        )).scalar_one_or_none()
    else:
        adjacent = (await db.execute(
            select(PublishTask).where(
                PublishTask.status == PublishTaskStatus.queued,
                PublishTask.sort_order > task.sort_order,
            ).order_by(PublishTask.sort_order).limit(1)
        )).scalar_one_or_none()

    if adjacent:
        task.sort_order, adjacent.sort_order = adjacent.sort_order, task.sort_order
    await db.commit()
    return {"ok": True}


@router.delete("/publish/{task_id}")
async def delete_publish_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await db.delete(task)
    await db.commit()
    return {"ok": True}


@router.post("/publish/batch")
async def batch_publish(data: dict, db: AsyncSession = Depends(get_db)):
    video_ids = data.get("video_ids", [])
    channel_id = data.get("channel_id", 0)
    if not video_ids or not channel_id:
        raise HTTPException(400, "video_ids and channel_id required")

    from app.database.models import Video
    ids = []
    for vid in video_ids:
        video = await db.get(Video, vid)
        if video:
            tid = await enqueue_publish(video_id=vid, channel_id=channel_id)
            ids.append(tid)

    return {"ok": True, "task_ids": ids, "count": len(ids)}


async def start_publish_worker():
    global worker_task
    async with _worker_lock:
        if worker_task is None or worker_task.done():
            # Reset stuck running tasks
            try:
                async with async_session() as db:
                    rows = (await db.execute(
                        select(PublishTask).where(PublishTask.status == PublishTaskStatus.running)
                    )).scalars().all()
                    for t in rows:
                        t.status = PublishTaskStatus.failed
                        t.error_log = "Task interrupted (container restarted)"
                    await db.commit()
            except Exception:
                pass
            worker_task = asyncio.create_task(_publish_worker())
