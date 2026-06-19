import datetime
import os
from pydantic import BaseModel as PydanticBaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from pathlib import Path

from app.database.connection import get_db
from app.database.models import Video, VideoStatus, Thumbnail, PublishLog, CompressJob, JobStatus
from app.modules.file_scanner import scan_directory, probe_video, compute_file_hash
from app.modules.publisher import publish_video
from app.modules.thumbnails import generate_thumbnail
from app.utils.helpers import get_setting

router = APIRouter()


@router.get("/videos")
async def list_videos(
    path: str = Query(""),
    parent: str = Query(""),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Video)
    if path:
        q = q.where(Video.filepath.ilike(f"{path}%"))
    elif parent:
        q = q.where(Video.filepath.ilike(f"{parent}/%"))
        q = q.where(~Video.filepath.ilike(f"{parent}/%/%"))
    if status:
        q = q.where(Video.status == status)
    q = q.order_by(Video.filename)

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    offset = (page - 1) * page_size
    q = q.offset(offset).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    items = []
    for v in rows:
        items.append({
            "id": v.id,
            "filename": v.filename,
            "folder": Path(v.filepath).parent.name if v.filepath else "",
            "filepath": v.filepath,
            "ext": v.ext,
            "size_bytes": v.size_bytes,
            "duration_sec": v.duration_sec,
            "width": v.width,
            "height": v.height,
            "codec": v.codec,
            "fps": v.fps,
            "bitrate_kbps": v.bitrate_kbps,
            "status": v.status.value if v.status else "pending",
            "error_msg": v.error_msg,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/videos/scan")
async def do_scan(path: str = Query(...), db: AsyncSession = Depends(get_db)):
    files = await scan_directory(path)
    if not files:
        return {"ok": True, "count": 0, "message": "No video files found"}

    added = 0
    updated = 0
    skipped = 0

    for f in files:
        existing = (await db.execute(
            select(Video).where(Video.filepath == f["filepath"])
        )).scalar_one_or_none()

        if existing:
            if existing.size_bytes != f["size_bytes"]:
                existing.size_bytes = f["size_bytes"]
                existing.updated_at = datetime.datetime.utcnow()
                updated += 1
            else:
                skipped += 1
            continue

        probe = await probe_video(f["filepath"])
        file_hash = await compute_file_hash(f["filepath"])

        video = Video(
            filename=f["filename"],
            filepath=f["filepath"],
            ext=f["ext"],
            size_bytes=f["size_bytes"],
            file_hash=file_hash,
            status=VideoStatus.pending,
        )

        if probe:
            video.duration_sec = probe["duration_sec"]
            video.width = probe["width"]
            video.height = probe["height"]
            video.codec = probe["codec"]
            video.fps = probe["fps"]
            video.bitrate_kbps = probe["bitrate_kbps"]

        db.add(video)
        added += 1

    await db.commit()
    return {
        "ok": True,
        "count": added,
        "updated": updated,
        "skipped": skipped,
        "message": f"新增 {added} 个视频" + (f"，更新 {updated} 个" if updated else ""),
    }


# ── Fixed-path routes (MUST come before /videos/{video_id} to avoid 422) ──

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.ts'}


@router.get("/videos/browse")
async def browse_directory(
    path: str = Query("/data/videos"),
):
    """Browse a directory: return subdirectories and video files."""
    p = Path(path)
    if not p.exists():
        return {"path": path, "dirs": [], "videos": [], "error": f"目录不存在: {path}"}
    if not p.is_dir():
        return {"path": path, "dirs": [], "videos": [], "error": "不是有效目录"}

    dirs = []
    videos_list = []
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
            elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                st = entry.stat()
                videos_list.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size_bytes": st.st_size,
                })
    except PermissionError:
        return {"path": path, "dirs": [], "videos": [], "error": "无权限访问目录"}
    except Exception as e:
        return {"path": path, "dirs": [], "videos": [], "error": str(e)}

    return {"path": path, "dirs": dirs, "videos": videos_list}


@router.get("/videos/estimate-size")
async def estimate_compressed_size(
    path: str = Query(...),
    preset: str = Query("balanced"),
    target_size_mb: int = Query(1000),
):
    """Estimate compressed output size for a video."""
    video_path = Path(path)
    if not video_path.exists():
        return {"estimated_mb": 0, "error": "文件不存在"}

    size_bytes = video_path.stat().st_size
    if size_bytes <= target_size_mb * 1_000_000:
        return {"estimated_mb": round(size_bytes / 1_000_000, 1), "original_mb": round(size_bytes / 1_000_000, 1), "will_skip": True}

    try:
        import asyncio
        import json as _json
        from app.utils.helpers import get_ffprobe_path

        proc = await asyncio.create_subprocess_exec(
            get_ffprobe_path(), "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(video_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        info = _json.loads(stdout.decode("utf-8", errors="ignore"))
        fmt = info.get("format", {})
        duration = float(fmt.get("duration", 0))

        if duration > 0:
            if preset == "fast":
                target_br = 1500
            elif preset == "balanced":
                target_br = 1000
            else:
                target_br = 800

            estimated_video_bits = target_br * 1000 * duration
            estimated_total = estimated_video_bits / 8 * 1.1
            estimated_mb = round(estimated_total / 1_000_000, 1)
            estimated_mb = min(estimated_mb, target_size_mb)

            return {
                "estimated_mb": estimated_mb,
                "original_mb": round(size_bytes / 1_000_000, 1),
                "saving_pct": round((1 - estimated_mb / (size_bytes / 1_000_000)) * 100, 1) if size_bytes > 0 else 0,
                "will_skip": False,
            }
    except Exception:
        if proc and proc.returncode is None:
            proc.kill()

    estimated_mb = round(min(size_bytes / 1_000_000 * 0.5, target_size_mb), 1)
    return {
        "estimated_mb": estimated_mb,
        "original_mb": round(size_bytes / 1_000_000, 1),
        "saving_pct": round((1 - estimated_mb / (size_bytes / 1_000_000)) * 100, 1) if size_bytes > 0 else 0,
        "will_skip": False,
    }


# ── Path-parameter routes (MUST come AFTER fixed-path routes) ──

@router.get("/videos/{video_id}")
async def get_video(video_id: int, db: AsyncSession = Depends(get_db)):
    v = await db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "Video not found")

    return {
        "id": v.id,
        "filename": v.filename,
        "filepath": v.filepath,
        "ext": v.ext,
        "size_bytes": v.size_bytes,
        "duration_sec": v.duration_sec,
        "width": v.width,
        "height": v.height,
        "codec": v.codec,
        "fps": v.fps,
        "bitrate_kbps": v.bitrate_kbps,
        "file_hash": v.file_hash,
        "status": v.status.value if v.status else "pending",
        "error_msg": v.error_msg,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


@router.delete("/videos/{video_id}")
async def delete_video(video_id: int, db: AsyncSession = Depends(get_db)):
    v = await db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    await db.delete(v)
    await db.commit()
    return {"ok": True}


class PublishNowRequest(PydanticBaseModel):
    channel_id: int
    title: str = ""
    thumb_caption_template: str = ""
    video_caption_template: str = ""


@router.post("/videos/{video_id}/publish")
async def publish_now(video_id: int, data: PublishNowRequest, db: AsyncSession = Depends(get_db)):

    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    from app.api.routes_publish import enqueue_publish

    tid = await enqueue_publish(video_id=video_id, channel_id=data.channel_id)
    return {"status": "queued", "task_id": tid, "video_id": video_id, "message": f"发布任务已创建: {video.filename}"}
