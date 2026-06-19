import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.connection import get_db
from app.database.models import Video, Thumbnail, CompressJob, JobStatus
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
    bot_cache_files = []
    if os.path.isdir(bot_cache_dir):
        total = 0
        for root, dirs, files in os.walk(bot_cache_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        bot_cache_files.append({"name": bot_cache_dir, "path": bot_cache_dir, "size": total, "is_dir": True})

    # Find orphan output files (no CompressJob references them)
    async with db.begin() as t:
        db_paths = set()
        rows = (await db.execute(
            select(CompressJob.output_path).where(CompressJob.output_path.isnot(None))
        )).scalars().all()
        for p in rows:
            db_paths.add(p)

    orphans = [f for f in output_files if f["path"] not in db_paths]

    # Find orphan thumbnail files
    async with db.begin() as t:
        thumb_db_paths = set()
        trows = (await db.execute(
            select(Thumbnail.filepath).where(Thumbnail.filepath.isnot(None))
        )).scalars().all()
        for p in trows:
            thumb_db_paths.add(p)

    orphan_thumbs = [f for f in thumb_files if f["path"] not in thumb_db_paths]

    return {
        "output": {"files": output_files, "orphans": orphans, "count": len(output_files),
                   "size": sum(f["size"] for f in output_files)},
        "thumbnails": {"files": thumb_files, "orphans": orphan_thumbs, "count": len(thumb_files),
                       "size": sum(f["size"] for f in thumb_files)},
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
