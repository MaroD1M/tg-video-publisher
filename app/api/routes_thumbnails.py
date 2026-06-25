from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.connection import get_db
from app.database.models import Video, Thumbnail
from app.modules.thumbnails import generate_thumbnail
from app.utils.helpers import get_setting

router = APIRouter()


@router.get("/thumbnails")
async def list_thumbnails(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Thumbnail).order_by(Thumbnail.id.desc()).limit(50)
    )).scalars().all()

    # Batch load videos
    video_ids = [t.video_id for t in rows]
    videos = {}
    if video_ids:
        from app.database.models import Video
        vrows = (await db.execute(select(Video).where(Video.id.in_(video_ids)))).scalars().all()
        videos = {v.id: v for v in vrows}

    items = []
    for t in rows:
        video = videos.get(t.video_id)
        items.append({
            "id": t.id,
            "video_id": t.video_id,
            "video_name": video.filename if video else "Unknown",
            "layout": t.layout,
            "filepath": t.filepath,
            "width": t.width,
            "height": t.height,
            "size_bytes": t.size_bytes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"items": items}


@router.post("/thumbnails/generate")
async def do_generate(
    video_id: int = Query(...),
    layout: str = Query("3x3"),
    add_timestamp: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    thumb_dir = await get_setting("thumbnail_dir", "/data/thumbnails")
    Path(thumb_dir).mkdir(parents=True, exist_ok=True)

    stem = Path(video.filename).stem
    output_path = str(Path(thumb_dir) / f"{stem}_thumb_{layout}.png")

    result = await generate_thumbnail(
        input_path=video.filepath,
        output_path=output_path,
        duration_sec=video.duration_sec,
        layout=layout,
        add_timestamp=add_timestamp,
    )

    if not result["success"]:
        raise HTTPException(500, f"Thumbnail generation failed: {result.get('error', '')}")

    thumb = Thumbnail(
        video_id=video.id,
        layout=layout,
        filepath=result["path"],
        width=result["width"],
        height=result["height"],
        size_bytes=result["size_bytes"],
        has_timestamp=add_timestamp,
    )
    db.add(thumb)
    await db.commit()
    await db.refresh(thumb)

    return {
        "ok": True,
        "id": thumb.id,
        "path": thumb.filepath,
        "width": thumb.width,
        "height": thumb.height,
        "size_bytes": thumb.size_bytes,
    }


@router.get("/thumbnails/{thumbnail_id}")
async def get_thumbnail(thumbnail_id: int, db: AsyncSession = Depends(get_db)):
    thumb = await db.get(Thumbnail, thumbnail_id)
    if not thumb:
        raise HTTPException(404, "Thumbnail not found")

    return {
        "id": thumb.id,
        "video_id": thumb.video_id,
        "layout": thumb.layout,
        "filepath": thumb.filepath,
        "width": thumb.width,
        "height": thumb.height,
        "size_bytes": thumb.size_bytes,
        "has_timestamp": thumb.has_timestamp,
        "created_at": thumb.created_at.isoformat() if thumb.created_at else None,
    }


@router.get("/thumbnails/{thumbnail_id}/image")
async def get_thumbnail_image(thumbnail_id: int, db: AsyncSession = Depends(get_db)):
    thumb = await db.get(Thumbnail, thumbnail_id)
    if not thumb:
        raise HTTPException(404, "Thumbnail not found")

    path = Path(thumb.filepath)
    if not path.exists():
        raise HTTPException(404, "Thumbnail file not found")

    return FileResponse(path, media_type="image/png")


@router.post("/thumbnails/{thumbnail_id}/regenerate")
async def regenerate_thumbnail(
    thumbnail_id: int,
    layout: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    thumb = await db.get(Thumbnail, thumbnail_id)
    if not thumb:
        raise HTTPException(404, "Thumbnail not found")

    video = await db.get(Video, thumb.video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    new_layout = layout or thumb.layout
    result = await generate_thumbnail(
        input_path=video.filepath,
        output_path=thumb.filepath,
        duration_sec=video.duration_sec,
        layout=new_layout,
        add_timestamp=thumb.has_timestamp,
    )

    if not result["success"]:
        raise HTTPException(500, f"Regeneration failed: {result.get('error', '')}")

    thumb.layout = new_layout
    thumb.width = result["width"]
    thumb.height = result["height"]
    thumb.size_bytes = result["size_bytes"]
    await db.commit()

    return {"ok": True}


@router.delete("/thumbnails/{thumbnail_id}")
async def delete_thumbnail(thumbnail_id: int, db: AsyncSession = Depends(get_db)):
    thumb = await db.get(Thumbnail, thumbnail_id)
    if not thumb:
        raise HTTPException(404, "Thumbnail not found")

    # Try to delete the file
    try:
        path = Path(thumb.filepath)
        if path.exists():
            path.unlink()
    except Exception:
        pass

    await db.delete(thumb)
    await db.commit()
    return {"ok": True}
