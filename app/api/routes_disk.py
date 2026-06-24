import os
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.connection import get_db
from app.database.models import Thumbnail, CompressJob, JobStatus, PublishLog
from app.utils.helpers import get_setting

router = APIRouter()


def _scan_dir(path: str) -> list[dict]:
    if not os.path.isdir(path):
        return []
    files = []
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            files.append({"name": f, "path": fp, "size": os.path.getsize(fp)})
    return files


def _scan_dir_recursive(path: str) -> list[dict]:
    """Recursively scan directory for all files with relative paths."""
    if not os.path.isdir(path):
        return []
    files = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, path)
            files.append({"name": rel, "path": fp, "size": os.path.getsize(fp)})
    return sorted(files, key=lambda x: x["name"])


@router.get("/disk/cleanup")
async def disk_cleanup_info(db: AsyncSession = Depends(get_db)):
    output_dir = await get_setting("output_dir", "/data/output")
    thumb_dir = await get_setting("thumbnail_dir", "/data/thumbnails")
    tmp_dir = "/tmp/compress_workers"
    bot_cache_dir = "/app/config/bot-api-data"

    # Scan directories
    output_files = _scan_dir(output_dir)
    thumb_files = _scan_dir(thumb_dir)
    tmp_files = _scan_dir(tmp_dir)
    bot_cache_files = _scan_dir_recursive(bot_cache_dir)

    # Build DB reference sets
    db_output_paths = set()
    rows = (await db.execute(
        select(CompressJob.output_path).where(CompressJob.output_path.isnot(None))
    )).scalars().all()
    for p in rows:
        db_output_paths.add(p)

    thumb_db_paths = set()
    trows = (await db.execute(
        select(Thumbnail.filepath).where(Thumbnail.filepath.isnot(None))
    )).scalars().all()
    for p in trows:
        thumb_db_paths.add(p)

    # Find orphan output files (no CompressJob references them)
    orphans = [f for f in output_files if f["path"] not in db_output_paths]
    orphan_thumbs = [f for f in thumb_files if f["path"] not in thumb_db_paths]

    # Find published videos: Video has successful PublishLog
    published_video_ids = set()
    pub_rows = (await db.execute(
        select(PublishLog.video_id).where(PublishLog.success == True)
    )).scalars().all()
    for vid in pub_rows:
        published_video_ids.add(vid)

    # Published compress outputs: CompressJob.done whose video has been published
    published_outputs = []
    pub_jobs = (await db.execute(
        select(CompressJob).where(
            CompressJob.status == JobStatus.done,
            CompressJob.output_path.isnot(None),
        )
    )).scalars().all()
    for j in pub_jobs:
        if j.video_id in published_video_ids and j.output_path and os.path.isfile(j.output_path):
            published_outputs.append({
                "name": os.path.basename(j.output_path),
                "path": j.output_path,
                "size": os.path.getsize(j.output_path),
            })

    # Published thumbnails of published videos
    published_thumbs = []
    pub_thumbs = (await db.execute(
        select(Thumbnail).where(Thumbnail.filepath.isnot(None))
    )).scalars().all()
    for t in pub_thumbs:
        if t.video_id in published_video_ids and t.filepath and os.path.isfile(t.filepath):
            published_thumbs.append({
                "name": os.path.basename(t.filepath),
                "path": t.filepath,
                "size": os.path.getsize(t.filepath),
            })

    return {
        "output": {"files": output_files, "orphans": orphans, "count": len(output_files),
                   "size": sum(f["size"] for f in output_files),
                   "published": published_outputs,
                   "published_size": sum(f["size"] for f in published_outputs)},
        "thumbnails": {"files": thumb_files, "orphans": orphan_thumbs, "count": len(thumb_files),
                       "size": sum(f["size"] for f in thumb_files),
                       "published": published_thumbs,
                       "published_size": sum(f["size"] for f in published_thumbs)},
        "tmp": {"files": tmp_files, "count": len(tmp_files),
                "size": sum(f["size"] for f in tmp_files)},
        "bot_cache": {"files": bot_cache_files, "count": len(bot_cache_files),
                      "size": sum(f["size"] for f in bot_cache_files)},
    }


@router.post("/disk/cleanup")
async def disk_cleanup_execute(data: dict, db: AsyncSession = Depends(get_db)):
    """Delete specified paths or clean entire directories."""
    paths = data.get("paths", [])
    clean_tmp = data.get("clean_tmp", False)
    clean_bot_cache = data.get("clean_bot_cache", False)

    deleted = []
    errors = []

    for p in paths:
        try:
            if os.path.isfile(p):
                os.remove(p)
                deleted.append(p)
        except Exception as e:
            errors.append({"path": p, "error": str(e)})

    if clean_tmp:
        for f in _scan_dir("/tmp/compress_workers"):
            try:
                os.remove(f["path"])
                deleted.append(f["path"])
            except Exception as e:
                errors.append({"path": f["path"], "error": str(e)})

    if clean_bot_cache:
        cache_dir = "/app/config/bot-api-data"
        if os.path.isdir(cache_dir):
            for root, dirs, files in os.walk(cache_dir, topdown=False):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                        deleted.append(os.path.join(root, f))
                    except Exception as e:
                        errors.append({"path": os.path.join(root, f), "error": str(e)})
                for d in dirs:
                    try:
                        os.rmdir(os.path.join(root, d))
                    except Exception:
                        pass

    return {"ok": True, "deleted": len(deleted), "errors": errors}
