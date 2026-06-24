import datetime
import asyncio
import json
import time
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.database.connection import get_db, async_session
from app.database.models import Video, VideoStatus, CompressJob, JobStatus, CompressPreset, Thumbnail, Schedule, ScheduleItem, ItemStatus
from app.modules.compressor import (
    run_compress_job, set_broadcast_callback, broadcast,
    cancel_events, pause_events, job_stderr,
)
from app.utils.helpers import get_setting

router = APIRouter()

job_queue: asyncio.Queue = asyncio.Queue()
worker_task: Optional[asyncio.Task] = None
worker_tasks: list[asyncio.Task] = []
_worker_lock = asyncio.Lock()


class CompressRequest(BaseModel):
    video_ids: list[int]
    preset: str = "balanced"
    target_size_mb: int = 1000
    target_width: int = 0
    target_height: int = 0
    schedule_id: int = 0
    publish_after: bool = False
    publish_channel_id: int = 0


async def _broadcast_fn(msg: str):
    from app.api.websocket import active_connections

    # Persist progress to DB
    try:
        data = json.loads(msg)
        if data.get("type") == "progress":
            async with async_session() as s:
                j = await s.get(CompressJob, data["job_id"])
                if j:
                    j.progress = data["percent"]
                    await s.commit()
    except Exception:
        pass

    for ws in active_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            pass


async def _compression_worker():
    while True:
        try:
            job_data = await job_queue.get()
            await _execute_one(job_data)
        except asyncio.CancelledError:
            break
        except Exception as e:
            import logging
            logging.getLogger("tgvp.compress").error(f"Worker crashed: {e}", exc_info=True)


async def _execute_one(job_data: dict):
    job_id = job_data["job_id"]
    video_id = job_data["video_id"]
    step_logs = []

    async with async_session() as db:
        job = await db.get(CompressJob, job_id)
        video = await db.get(Video, video_id)
        if not job or not video:
            return
        job.status = JobStatus.running
        job.started_at = datetime.datetime.utcnow()
        video.status = VideoStatus.compressing

        input_path = video.filepath
        output_filename = job.output_filename or f"compressed_{video.filename}"
        duration_sec = video.duration_sec
        size_bytes = video.size_bytes
        preset = job.preset
        filename = video.filename
        target_size_mb = job.target_size_mb
        target_width = job.target_width
        target_height = job.target_height
        schedule_id = job.schedule_id
        publish_after = job.publish_after
        publish_channel_id = job.publish_channel_id
        await db.commit()

    try:
        layout = await get_setting("thumbnail_layout", "3x3")
        output_dir = await get_setting("output_dir", "/data/output")

        # Phase 1: Generate thumbnail from original video (before compression)
        thumb_id_val = None
        thumb_start = time.time()
        try:
            from app.modules.publisher import ensure_thumbnail
            async with async_session() as db:
                video_obj = await db.get(Video, video_id)
                if video_obj:
                    thumb_path = await ensure_thumbnail(video_obj, input_path, db)
                    if thumb_path:
                        thumb_row = (await db.execute(
                            select(Thumbnail.id).where(Thumbnail.video_id == video_id)
                            .order_by(Thumbnail.id.desc()).limit(1)
                        )).scalar_one_or_none()
                        if thumb_row:
                            thumb_id_val = thumb_row
        except Exception:
            pass
        thumb_elapsed = round(time.time() - thumb_start, 1)
        step_logs.append({"step":"thumbnail","elapsed":thumb_elapsed,"result":"done" if thumb_id_val else "skipped","thumb_id":thumb_id_val})

        await broadcast({
            "type": "progress", "job_id": job_id,
            "percent": 0, "eta_sec": 0, "elapsed_sec": 0, "speed": 0, "fps": 0,
            "phase": "encoding", "step_log": step_logs,
            "thumbnail_id": thumb_id_val,
        })

        # Phase 2: Run compression
        compress_start = time.time()
        result = await run_compress_job(
            job_id=job_id, video_id=video_id,
            input_path=input_path, output_filename=output_filename,
            output_dir=output_dir, duration_sec=duration_sec,
            size_bytes=size_bytes, preset=preset, thumbnail_layout=layout,
            target_size_mb=target_size_mb,
            target_width=target_width,
            target_height=target_height,
            thumbnail_id=thumb_id_val,
        )
        compress_elapsed = round(time.time() - compress_start, 1)

        st = result["status"]
        if st in ("done", "skipped"):
            out_size = result.get("output_size", 0)
            speed = round(duration_sec / compress_elapsed, 1) if compress_elapsed > 0 and duration_sec > 0 else 0
            step_logs.append({"step":"encoding","elapsed":compress_elapsed,"result":"done" if st == "done" else "skipped","speed":speed,"output_gb":round(out_size/1e9,2)})
        elif st == "cancelled":
            step_logs.append({"step":"encoding","elapsed":compress_elapsed,"result":"cancelled"})
        else:
            step_logs.append({"step":"encoding","elapsed":compress_elapsed,"result":"failed","error":result.get("error","")[:200]})

        # Check for retry pass
        if result.get("phase") == "retry_pass2":
            step_logs.append({"step":"retry_pass2","elapsed":round(time.time()-compress_start-compress_elapsed,1),"result":"done" if st=="done" else "retried"})

        async with async_session() as db:
            job = await db.get(CompressJob, job_id)
            video = await db.get(Video, video_id)
            if job and video:
                job.finished_at = datetime.datetime.utcnow()
                job.output_size_bytes = result.get("output_size", 0)
                job.output_path = result.get("output_path", "")
                if job.output_size_bytes and size_bytes:
                    job.compression_ratio = round((1 - job.output_size_bytes / size_bytes) * 100, 1)

                job.status = JobStatus(st)
                job.error_log = result.get("stderr", "") or result.get("error", "")
                job.step_log = json.dumps(step_logs)
                if st == "done":
                    video.status = VideoStatus.compressed
                elif st == "skipped":
                    video.status = VideoStatus.skipped
                elif st == "cancelled":
                    video.status = VideoStatus.failed
                    video.error_msg = "Cancelled by user"
                else:
                    video.status = VideoStatus.failed
                await db.commit()

        # Broadcast final step_logs so frontend sees them immediately
        await broadcast({
            "type": "progress", "job_id": job_id,
            "percent": 100, "eta_sec": 0, "elapsed_sec": 0, "speed": 0, "fps": 0,
            "phase": st + "_done",
            "step_log": step_logs,
            "thumbnail_id": thumb_id_val,
        })

        # Notify admin
        from app.modules.notifier import notify_admin
        if result["status"] == "done":
            out_size = result.get("output_size", 0)
            ratio = round((1 - out_size / size_bytes) * 100, 1) if size_bytes and out_size else 0
            await notify_admin(
                f"✅ 压缩完成: {filename}\n{size_bytes/1e9:.2f}GB → {out_size/1e9:.2f}GB ({ratio}%)",
                event_type="compress_done",
                variables={"filename": filename, "size": f"{size_bytes/1e9:.2f}GB", "out_size": f"{out_size/1e9:.2f}GB", "ratio": f"{ratio}%"},
            )
        elif result["status"] == "failed":
            await notify_admin(
                f"❌ 压缩失败: {filename}\n{result.get('error', 'Unknown')[:200]}",
                event_type="compress_fail",
                variables={"filename": filename, "error": result.get('error', 'Unknown')[:200]},
            )
        elif result["status"] == "cancelled":
            await notify_admin(f"⏹ 压缩已取消: {filename}")

        # Auto-add to schedule if requested
        if schedule_id and result["status"] in ("done", "skipped"):
            await _auto_add_to_schedule(job_id, video_id, schedule_id)

        # Publish immediately if requested
        if publish_after and publish_channel_id and result["status"] in ("done", "skipped"):
            await _publish_compressed(job_id, video_id, publish_channel_id)

    except Exception as e:
        step_logs.append({"step":"error","elapsed":0,"result":"failed","error":str(e)[:200]})
        async with async_session() as db:
            job = await db.get(CompressJob, job_id)
            video = await db.get(Video, video_id)
            if job:
                job.status = JobStatus.failed
                job.error_log = str(e)
                job.step_log = json.dumps(step_logs)
                job.finished_at = datetime.datetime.utcnow()
            if video:
                video.status = VideoStatus.failed
                video.error_msg = str(e)
            await db.commit()

        await broadcast({
            "type": "progress", "job_id": job_id,
            "percent": 0, "eta_sec": 0, "elapsed_sec": 0, "speed": 0, "fps": 0,
            "phase": "error",
            "step_log": step_logs,
        })


async def start_worker():
    global worker_task, worker_tasks
    set_broadcast_callback(_broadcast_fn)
    async with _worker_lock:
        # Check if workers are already running
        active = [t for t in worker_tasks if not t.done()]
        if active:
            return  # Already running

        # Reset stuck running jobs (container restarted)
        try:
            async with async_session() as db:
                rows = (await db.execute(
                    select(CompressJob).where(CompressJob.status == JobStatus.running)
                )).scalars().all()
                for j in rows:
                    j.status = JobStatus.failed
                    j.error_log = "Task interrupted (container restarted)"
                    video = await db.get(Video, j.video_id)
                    if video:
                        video.status = VideoStatus.failed
                        video.error_msg = "Compression interrupted (container restarted)"
                await db.commit()
        except Exception:
            pass

        max_w = 1
        try:
            max_w_str = await get_setting("max_workers", "1")
            max_w = max(1, min(8, int(max_w_str)))
        except (ValueError, TypeError):
            max_w = 1

        worker_tasks = [asyncio.create_task(_compression_worker()) for _ in range(max_w)]
        worker_task = worker_tasks[0]


@router.post("/compress")
async def submit_compress(
    data: CompressRequest,
    db: AsyncSession = Depends(get_db),
):
    if not data.video_ids:
        raise HTTPException(400, "No video IDs provided")
    if data.preset not in {p.value for p in CompressPreset}:
        raise HTTPException(422, f"Invalid preset: {data.preset}")

    jobs = []
    for vid in data.video_ids:
        video = await db.get(Video, vid)
        if not video:
            continue
        if video.status in [VideoStatus.compressed, VideoStatus.compressing]:
            continue

        job = CompressJob(
            video_id=vid,
            preset=CompressPreset(data.preset),
            target_size_mb=data.target_size_mb,
            target_width=data.target_width,
            target_height=data.target_height,
            schedule_id=data.schedule_id,
            publish_after=data.publish_after,
            publish_channel_id=data.publish_channel_id,
            output_filename=f"compressed_{video.filename}",
            status=JobStatus.queued,
        )
        db.add(job)
        await db.flush()
        jobs.append({"job_id": job.id, "video_id": vid, "video_name": video.filename})
        video.status = VideoStatus.compressing

    await db.commit()

    for j in jobs:
        await job_queue.put(j)

    await start_worker()
    return {"ok": True, "jobs": jobs}


@router.get("/compress")
async def list_compress_jobs(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    q = select(CompressJob).order_by(CompressJob.id.desc())
    if status:
        q = q.where(CompressJob.status == status)
    q = q.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(q)).scalars().all()

    # Total count
    count_q = select(CompressJob)
    if status:
        count_q = count_q.where(CompressJob.status == status)
    total = (await db.execute(select(func.count()).select_from(count_q.subquery()))).scalar() or 0
    items = []
    if rows:
        video_ids = [j.video_id for j in rows if j.video_id]
        # Batch load videos
        videos = {}
        if video_ids:
            vids = (await db.execute(
                select(Video).where(Video.id.in_(video_ids))
            )).scalars().all()
            videos = {v.id: v for v in vids}
        # Batch load thumbnails (latest per video)
        thumbs = {}
        if video_ids:
            from sqlalchemy import and_
            thumb_rows = (await db.execute(
                select(Thumbnail).where(
                    Thumbnail.video_id.in_(video_ids)
                ).order_by(Thumbnail.id.desc())
            )).scalars().all()
            seen = set()
            for t in thumb_rows:
                if t.video_id not in seen:
                    seen.add(t.video_id)
                    thumbs[t.video_id] = t.id

        for j in rows:
            video = videos.get(j.video_id) if j.video_id else None
            thumb_id = thumbs.get(j.video_id) if j.video_id else None

            items.append({
                "id": j.id,
                "video_id": j.video_id,
                "video_name": video.filename if video else "Unknown",
                "original_size_bytes": video.size_bytes if video else 0,
                "preset": j.preset.value if j.preset else "balanced",
                "output_path": j.output_path,
                "output_size_bytes": j.output_size_bytes,
                "compression_ratio": j.compression_ratio,
                "progress": j.progress,
                "status": j.status.value if j.status else "queued",
                "error_log": j.error_log or job_stderr.get(j.id, ""),
                "step_log": json.loads(j.step_log) if j.step_log else [],
                "eta_sec": 0,
                "elapsed_sec": 0,
                "speed": 0,
                "fps": 0,
                "phase": "",
                "stderr": job_stderr.get(j.id, "") or j.error_log or "",
                "thumbnail_id": thumb_id,
            })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/compress/{job_id}")
async def get_compress_job(job_id: int, db: AsyncSession = Depends(get_db)):
    j = await db.get(CompressJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")

    video = await db.get(Video, j.video_id) if j.video_id else None
    return {
        "id": j.id, "video_id": j.video_id,
        "video_name": video.filename if video else "Unknown",
        "preset": j.preset.value if j.preset else "balanced",
        "status": j.status.value if j.status else "queued",
        "progress": j.progress,
        "output_size_bytes": j.output_size_bytes,
        "compression_ratio": j.compression_ratio,
        "error_log": j.error_log,
        "stderr": job_stderr.get(job_id, ""),
    }


@router.post("/compress/{job_id}/cancel")
async def cancel_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in [JobStatus.running, JobStatus.queued]:
        raise HTTPException(400, "Job is not running or queued")

    cancel_events.setdefault(job_id, asyncio.Event())
    cancel_events[job_id].set()

    if job.status == JobStatus.queued:
        job.status = JobStatus.cancelled
        video = await db.get(Video, job.video_id)
        if video:
            video.status = VideoStatus.failed
            video.error_msg = "Cancelled by user"
        await db.commit()

    return {"ok": True}


@router.post("/compress/{job_id}/pause")
async def pause_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.running:
        raise HTTPException(400, "Job is not running")

    pause_events.setdefault(job_id, asyncio.Event())
    pause_events[job_id].set()
    job.status = JobStatus.paused
    await db.commit()
    return {"ok": True}


@router.post("/compress/{job_id}/resume")
async def resume_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.paused:
        raise HTTPException(400, "Job is not paused")

    e = pause_events.get(job_id)
    if e:
        e.set()
    job.status = JobStatus.running
    await db.commit()
    return {"ok": True}


@router.post("/compress/{job_id}/retry")
async def retry_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in (JobStatus.failed, JobStatus.skipped, JobStatus.cancelled):
        raise HTTPException(400, "Job cannot be retried")

    # Reset job
    job.status = JobStatus.queued
    job.progress = 0
    job.error_log = ""
    job.started_at = None
    job.finished_at = None
    await db.commit()

    # Enqueue again with original parameters from the job record
    await job_queue.put({"job_id": job.id, "video_id": job.video_id})
    await start_worker()
    return {"ok": True}


async def _auto_add_to_schedule(job_id: int, video_id: int, schedule_id: int):
    """After compression completes, auto-add the video to a schedule's queue."""
    from app.modules.notifier import notify_admin

    try:
        async with async_session() as db:
            sched = await db.get(Schedule, schedule_id)
            if not sched:
                return

            # Check if already in queue (not yet published)
            existing = (await db.execute(
                select(ScheduleItem).where(
                    ScheduleItem.schedule_id == schedule_id,
                    ScheduleItem.video_id == video_id,
                    ScheduleItem.status.in_([ItemStatus.queued]),
                )
            )).scalar_one_or_none()

            if existing:
                return  # Already queued

            # Count existing to determine sort_order
            count = (await db.execute(
                select(func.count()).select_from(ScheduleItem).where(
                    ScheduleItem.schedule_id == schedule_id,
                    ScheduleItem.status == ItemStatus.queued,
                )
            )).scalar() or 0

            item = ScheduleItem(
                schedule_id=schedule_id,
                video_id=video_id,
                sort_order=count,
                status=ItemStatus.queued,
            )
            db.add(item)
            await db.commit()

            # Broadcast to WebSocket
            video_name = ""
            async with async_session() as db2:
                v = await db2.get(Video, video_id)
                video_name = v.filename if v else str(video_id)

            from app.api.websocket import active_connections
            msg = json.dumps({
                "type": "schedule_added",
                "job_id": job_id,
                "schedule_id": schedule_id,
                "schedule_name": sched.name,
                "video_id": video_id,
                "video_name": video_name,
            })
            for ws in active_connections:
                try:
                    await ws.send_text(msg)
                except Exception:
                    pass

            await notify_admin(
                f"📋 已加入发布队列: {video_name}\n计划: {sched.name}"
            )
    except Exception:
        pass


async def _publish_compressed(job_id: int, video_id: int, channel_id: int):
    """After compression completes, enqueue PublishTask to publish asynchronously."""
    from app.api.routes_publish import enqueue_publish
    from app.database.models import Video

    try:
        async with async_session() as db:
            video = await db.get(Video, video_id)
            if video:
                await enqueue_publish(video_id=video_id, channel_id=channel_id, channel_name=str(channel_id))
    except Exception:
        pass


@router.delete("/compress/{job_id}")
async def delete_compress_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == JobStatus.running:
        raise HTTPException(400, "Cannot delete running job, cancel it first")
    # Reset video status if it was stuck in compressing
    video = await db.get(Video, job.video_id)
    if video and video.status in (VideoStatus.compressing, VideoStatus.compressed, VideoStatus.skipped, VideoStatus.failed):
        video.status = VideoStatus.pending
        video.error_msg = None
    await db.delete(job)
    await db.commit()
    return {"ok": True}


@router.post("/compress/batch-delete")
async def batch_delete_compress(status: str = Query(""), db: AsyncSession = Depends(get_db)):
    q = select(CompressJob).where(
        CompressJob.status.in_([JobStatus.done, JobStatus.failed, JobStatus.skipped, JobStatus.cancelled])
    )
    if status:
        q = q.where(CompressJob.status == status)
    rows = (await db.execute(q)).scalars().all()
    for row in rows:
        await db.delete(row)
    await db.commit()
    return {"ok": True, "deleted": len(rows)}


@router.put("/compress/{job_id}/settings")
async def update_compress_settings(job_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """Update settings for a queued compress job before retrying."""
    job = await db.get(CompressJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in (JobStatus.queued, JobStatus.failed, JobStatus.skipped):
        raise HTTPException(400, "Only queued/failed/skipped jobs can be reconfigured")

    if "preset" in data:
        try:
            job.preset = CompressPreset(data["preset"])
        except ValueError:
            pass
    if "target_size_mb" in data:
        job.target_size_mb = int(data["target_size_mb"])
    if "target_width" in data:
        job.target_width = int(data["target_width"])
    if "target_height" in data:
        job.target_height = int(data["target_height"])
    await db.commit()
    return {"ok": True}


@router.put("/compress/batch-config")
async def batch_config_compress(data: dict, db: AsyncSession = Depends(get_db)):
    """Batch update settings for queued compress jobs."""
    job_ids = data.get("job_ids", [])
    updates = data.get("updates", {})
    if not job_ids:
        raise HTTPException(400, "job_ids required")

    updated = 0
    for jid in job_ids:
        job = await db.get(CompressJob, jid)
        if not job or job.status != JobStatus.queued:
            continue
        for key, val in updates.items():
            if key == "preset":
                try:
                    job.preset = CompressPreset(val)
                except ValueError:
                    pass
            elif key == "target_size_mb":
                job.target_size_mb = int(val)
            elif key == "target_width":
                job.target_width = int(val)
            elif key == "target_height":
                job.target_height = int(val)
        updated += 1
    await db.commit()
    return {"ok": True, "updated": updated}
