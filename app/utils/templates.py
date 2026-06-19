"""Simple template engine for video publish captions."""

import re
from datetime import datetime


def format_duration(sec: float) -> str:
    if not sec:
        return ""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def format_size(bytes_val: int) -> str:
    if not bytes_val:
        return "0MB"
    if bytes_val < 1_000_000_000:
        return f"{bytes_val / 1_000_000:.0f}MB"
    return f"{bytes_val / 1_000_000_000:.2f}GB"


def render_template(template: str, variables: dict) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return result


def build_caption_vars(
    video_filename: str = "",
    title: str = "",
    duration_sec: float = 0,
    width: int = 0,
    height: int = 0,
    size_bytes: int = 0,
    original_size_bytes: int = 0,
) -> dict:
    from pathlib import Path
    stem = Path(video_filename).stem if video_filename else ""
    ext = Path(video_filename).suffix.lstrip(".") if video_filename else ""

    res_str = f"{width}×{height}" if width and height else ""
    dur_str = format_duration(duration_sec) if duration_sec else ""
    size_str = format_size(size_bytes) if size_bytes else ""
    orig_str = format_size(original_size_bytes) if original_size_bytes else ""

    ratio = ""
    if original_size_bytes and size_bytes and original_size_bytes > 0:
        ratio = f"{round((1 - size_bytes / original_size_bytes) * 100)}%"

    return {
        "title": title or stem,
        "filename": video_filename,
        "ext": ext,
        "duration": dur_str,
        "resolution": res_str,
        "size": size_str,
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "original_size": orig_str,
        "ratio": ratio,
        "nl": "\n",
        "year": str(datetime.now().year),
        "month": datetime.now().strftime("%m"),
        "day": datetime.now().strftime("%d"),
    }


# Default templates
DEFAULT_THUMB_CAPTION = "🎬 {{title}} | ⏱ {{duration}} | 📐 {{resolution}}{{nl}}视频评论区 👇"
DEFAULT_VIDEO_CAPTION = "{{title}}{{nl}}💾 {{size}} | 📐 {{resolution}} | ⏱ {{duration}}"
