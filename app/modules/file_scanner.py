import json
import hashlib
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from app.utils.helpers import get_ffprobe_path


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".mts", ".m2ts", ".mpg", ".mpeg"}


async def scan_directory(directory: str) -> list[dict]:
    """Scan a directory for video files, return basic info. Runs in thread pool."""
    return await asyncio.to_thread(_sync_scan, directory)


def _sync_scan(directory: str) -> list[dict]:
    path = Path(directory)
    results = []
    try:
        for p in path.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                stat = p.stat()
                results.append({
                    "filename": p.name,
                    "filepath": str(p),
                    "ext": p.suffix.lower(),
                    "size_bytes": stat.st_size,
                })
    except (PermissionError, FileNotFoundError):
        pass
    return sorted(results, key=lambda x: x["filename"])


async def compute_file_hash(filepath: str, chunk_size: int = 65536) -> str:
    """Compute SHA256 hash. Runs in thread pool to avoid blocking."""
    return await asyncio.to_thread(_sync_hash, filepath, chunk_size)


def _sync_hash(filepath: str, chunk_size: int) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for _ in range(16):
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except (PermissionError, FileNotFoundError):
        pass
    return h.hexdigest()[:16]


async def probe_video(filepath: str) -> Optional[dict]:
    """Run ffprobe on a video file, return parsed metadata."""
    ffprobe = get_ffprobe_path()
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            return None

        data = json.loads(stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})

        duration = float(fmt.get("duration", 0))
        bitrate = int(fmt.get("bit_rate", 0)) // 1000 if fmt.get("bit_rate") else 0

        return {
            "duration_sec": round(duration, 2),
            "width": video_stream.get("width", 0),
            "height": video_stream.get("height", 0),
            "codec": video_stream.get("codec_name", ""),
            "fps": _parse_fps(video_stream),
            "bitrate_kbps": bitrate,
        }
    except Exception:
        if proc and proc.returncode is None:
            proc.kill()
        return None


def _parse_fps(video_stream: dict) -> float:
    r_frame_rate = video_stream.get("r_frame_rate", "")
    if "/" in r_frame_rate:
        parts = r_frame_rate.split("/")
        if len(parts) == 2 and int(parts[1]) != 0:
            return round(int(parts[0]) / int(parts[1]), 2)
    avg = video_stream.get("avg_frame_rate", "")
    if "/" in avg:
        parts = avg.split("/")
        if len(parts) == 2 and int(parts[1]) != 0:
            return round(int(parts[0]) / int(parts[1]), 2)
    return 0.0
