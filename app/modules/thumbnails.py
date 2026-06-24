import asyncio
from pathlib import Path
from app.utils.helpers import get_ffmpeg_path

def _find_font() -> str:
    """Find a suitable CJK font for drawtext, with Alpine/Debian fallback."""
    candidates = [
        # Alpine
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
        # Debian/Ubuntu
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        # Generic fallback
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""

_FONT_FILE = ""
_font_checked = False


def _get_font() -> str:
    global _FONT_FILE, _font_checked
    if not _font_checked:
        _font_checked = True
        _FONT_FILE = _find_font()
    return _FONT_FILE


LAYOUTS = {
    "3x3": (3, 3),
    "2x3": (2, 3),
    "4x4": (4, 4),
    "2x2": (2, 2),
    "3x2": (3, 2),
}


async def generate_thumbnail(
    input_path: str,
    output_path: str,
    duration_sec: float,
    layout: str = "3x3",
    add_timestamp: bool = True,
    watermark_path: str = "",
) -> dict:
    cols, rows = LAYOUTS.get(layout, (3, 3))
    total_frames = cols * rows

    if duration_sec <= 0:
        duration_sec = 60

    # Calculate FPS such that we get exactly (cols * rows) frames across the duration
    # Skip first and last 5% to avoid black frames
    effective_start = duration_sec * 0.05
    effective_end = duration_sec * 0.95
    effective_duration = effective_end - effective_start
    fps_value = total_frames / effective_duration if effective_duration > 0 else 1

    thumb_w = 640
    thumb_h = 360

    filter_parts = []
    filter_parts.append(f"trim=start={effective_start}:end={effective_end},setpts=PTS-STARTPTS")
    filter_parts.append(f"fps={fps_value:.4f}")

    if add_timestamp:
        font = _get_font()
        font_opt = f":fontfile={font}" if font else ""
        filter_parts.append(
            f"drawtext=text='%{{pts\\:hms}}'{font_opt}:"
            "fontsize=14:fontcolor=white:box=1:boxcolor=black@0.6:"
            "x=8:y=h-th-8"
        )

    filter_parts.append(
        f"scale={thumb_w}:{thumb_h}:force_original_aspect_ratio=decrease,"
        f"pad={thumb_w}:{thumb_h}:(ow-iw)/2:(oh-ih)/2"
    )

    filter_parts.append(f"tile={cols}x{rows}")

    filter_str = ",".join(filter_parts)

    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-vf", filter_str,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"success": False, "error": "Thumbnail generation timed out"}

    output_file = Path(output_path)
    if proc.returncode != 0 or not output_file.exists():
        err = stderr.decode("utf-8", errors="ignore")[-500:]
        return {"success": False, "error": err}

    size = output_file.stat().st_size
    return {
        "success": True,
        "path": output_path,
        "size_bytes": size,
        "width": thumb_w * cols,
        "height": thumb_h * rows,
        "layout": layout,
    }
