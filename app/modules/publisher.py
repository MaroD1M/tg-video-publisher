from pathlib import Path

from app.utils.templates import (
    build_caption_vars, render_template,
    DEFAULT_THUMB_CAPTION, DEFAULT_VIDEO_CAPTION,
)


async def publish_video(
    video_path: str,
    thumb_path: str,
    channel_id: int,
    video_filename: str = "",
    duration_sec: float = 0,
    size_bytes: int = 0,
    original_size_bytes: int = 0,
    width: int = 0,
    height: int = 0,
    title: str = "",
    thumb_template: str = "",
    video_template: str = "",
) -> dict:
    from app.bot.client import get_bot
    from app.utils.helpers import get_setting

    bot = await get_bot()
    if not bot:
        return {"success": False, "error": "Bot not configured"}

    if not Path(video_path).exists():
        return {"success": False, "error": f"Video file not found: {video_path}"}
    if not Path(thumb_path).exists():
        return {"success": False, "error": f"Thumbnail not found: {thumb_path}"}

    # Read custom templates from settings if not explicitly passed
    if not thumb_template:
        thumb_template = await get_setting("thumb_caption_template", "")
    if not video_template:
        video_template = await get_setting("video_caption_template", "")

    # Build caption variables
    vars_dict = build_caption_vars(
        video_filename=video_filename,
        title=title,
        duration_sec=duration_sec,
        width=width,
        height=height,
        size_bytes=size_bytes,
        original_size_bytes=original_size_bytes,
    )

    thumb_caption = render_template(
        thumb_template or DEFAULT_THUMB_CAPTION, vars_dict
    )
    video_caption = render_template(
        video_template or DEFAULT_VIDEO_CAPTION, vars_dict
    )

    thumb_msg_id = None
    discussion_chat_id = None

    # Resolve discussion group (linked chat) for comments section
    try:
        from app.database.connection import async_session
        from app.database.models import TargetChat
        from sqlalchemy import select
        async with async_session() as db:
            tc = (await db.execute(
                select(TargetChat).where(TargetChat.chat_id == channel_id)
            )).scalar_one_or_none()
            if tc and tc.linked_chat_id:
                discussion_chat_id = tc.linked_chat_id
    except Exception:
        pass

    # Send thumbnail to channel (always in main channel)
    try:
        with open(thumb_path, "rb") as f:
            thumb_msg = await bot.send_photo(
                chat_id=channel_id, photo=f, caption=thumb_caption,
                has_spoiler=True,
            )
            thumb_msg_id = thumb_msg.message_id
    except Exception as e:
        return {"success": False, "error": f"Thumbnail send failed: {e}"}

    # Send video — to discussion group thread if available, otherwise reply in channel
    try:
        with open(video_path, "rb") as f:
            kwargs = dict(
                video=f, caption=video_caption, supports_streaming=True,
                has_spoiler=True,
                duration=int(duration_sec) if duration_sec else None,
                width=width if width else None,
                height=height if height else None,
            )
            if discussion_chat_id:
                try:
                    kwargs["message_thread_id"] = thumb_msg_id
                    video_msg = await bot.send_video(chat_id=discussion_chat_id, **kwargs)
                except Exception:
                    kwargs.pop("message_thread_id", None)
                    kwargs["reply_to_message_id"] = thumb_msg_id
                    video_msg = await bot.send_video(chat_id=channel_id, **kwargs)
            else:
                kwargs["reply_to_message_id"] = thumb_msg_id
                video_msg = await bot.send_video(chat_id=channel_id, **kwargs)

            return {
                "success": True,
                "thumb_message_id": thumb_msg_id,
                "video_message_id": video_msg.message_id,
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Video send failed: {e}",
            "thumb_message_id": thumb_msg_id,
        }


async def resolve_video_path(video) -> tuple[str, int]:
    """Find compressed output path or fallback to original."""
    from app.database.connection import async_session
    from app.database.models import CompressJob, JobStatus
    from sqlalchemy import select

    async with async_session() as db:
        comp_job = (await db.execute(
            select(CompressJob)
            .where(CompressJob.video_id == video.id, CompressJob.status == JobStatus.done)
            .order_by(CompressJob.id.desc()).limit(1)
        )).scalar_one_or_none()

    if comp_job and comp_job.output_path:
        return comp_job.output_path, comp_job.output_size_bytes
    return video.filepath, video.size_bytes


async def ensure_thumbnail(video, video_path: str, db=None) -> str:
    """Find existing thumbnail or generate one. Returns thumbnail file path."""
    from app.database.connection import async_session
    from app.database.models import Thumbnail
    from app.modules.thumbnails import generate_thumbnail
    from app.utils.helpers import get_setting
    from sqlalchemy import select

    if db is None:
        async with async_session() as s:
            return await _ensure_thumb_impl(video, video_path, s)
    return await _ensure_thumb_impl(video, video_path, db)


async def _ensure_thumb_impl(video, video_path: str, db) -> str:
    from app.database.models import Thumbnail
    from app.modules.thumbnails import generate_thumbnail
    from app.utils.helpers import get_setting
    from sqlalchemy import select

    thumb = (await db.execute(
        select(Thumbnail).where(Thumbnail.video_id == video.id).order_by(Thumbnail.id.desc()).limit(1)
    )).scalar_one_or_none()

    if thumb and thumb.filepath:
        return thumb.filepath

    layout = await get_setting("thumbnail_layout", "3x3")
    thumb_dir = await get_setting("thumbnail_dir", "/data/thumbnails")
    Path(thumb_dir).mkdir(parents=True, exist_ok=True)
    thumb_path = str(Path(thumb_dir) / f"{Path(video.filename).stem}_thumb_{layout}.png")
    result = await generate_thumbnail(video_path, thumb_path, video.duration_sec, layout)
    if result["success"]:
        db.add(Thumbnail(video_id=video.id, layout=layout, filepath=thumb_path,
                         width=result["width"], height=result["height"], size_bytes=result["size_bytes"]))
        await db.commit()
        return thumb_path
    return ""
