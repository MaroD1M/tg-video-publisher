import asyncio
import os
import re
import signal
import json
import shutil
import time
from pathlib import Path

from app.utils.helpers import get_ffmpeg_path
from app.database.models import CompressPreset

# Hardware acceleration detection
HW_ACCEL = "software"
_hw_checked = False


def get_hw_accel() -> str:
    global HW_ACCEL, _hw_checked
    if not _hw_checked:
        _hw_checked = True
        detect_hw_accel()
    return HW_ACCEL


def detect_hw_accel():
    global HW_ACCEL
    # Check NVIDIA NVENC
    if shutil.which("nvidia-smi"):
        try:
            result = os.popen("nvidia-smi -L 2>/dev/null").read()
            if "GPU" in result:
                HW_ACCEL = "nvenc"
                return HW_ACCEL
        except Exception:
            pass
    # Check Intel QSV
    if os.path.exists("/dev/dri/renderD128"):
        test = os.popen(f"{get_ffmpeg_path()} -hide_banner -init_hw_device qsv=hw 2>&1").read()
        if "qsv" in test.lower() and "error" not in test.lower():
            HW_ACCEL = "qsv"
            return HW_ACCEL
    # Check VAAPI
    if os.path.exists("/dev/dri/renderD128"):
        HW_ACCEL = "vaapi"
        return HW_ACCEL
    return HW_ACCEL


# WebSocket broadcast callback
broadcast_fn = None

# Cancel and pause events: dict[job_id] = asyncio.Event
cancel_events: dict[int, asyncio.Event] = {}
pause_events: dict[int, asyncio.Event] = {}

# Stderr capture: dict[job_id] = str (FFmpeg last stderr)
job_stderr: dict[int, str] = {}


def set_broadcast_callback(fn):
    global broadcast_fn
    broadcast_fn = fn


async def broadcast(msg: dict):
    if broadcast_fn:
        await broadcast_fn(json.dumps(msg))


def calc_target_bitrate(duration_sec: float, target_size_mb: int = 1000) -> int:
    if not duration_sec or duration_sec <= 0:
        return target_size_mb * 1000
    target_bits = target_size_mb * 1_000_000 * 8 * 0.85
    return int(target_bits / duration_sec / 1000)


def should_skip_compression(size_bytes: int, target_size_mb: int = 1000) -> bool:
    return size_bytes <= target_size_mb * 1_000_000


def build_ffmpeg_args(
    input_path: str,
    output_path: str,
    duration_sec: float,
    preset: CompressPreset,
    target_size_mb: int = 1000,
    target_width: int = 0,
    target_height: int = 0,
) -> list[str]:
    target_br = calc_target_bitrate(duration_sec, target_size_mb)
    max_br = int(target_br * 1.1)
    hw = get_hw_accel()

    # Select encoder — prefer HW when available
    if hw == "nvenc":
        vcodec = "h264_nvenc" if preset == CompressPreset.fast else "hevc_nvenc"
    elif hw == "qsv":
        vcodec = "h264_qsv" if preset == CompressPreset.fast else "hevc_qsv"
    elif hw == "vaapi":
        vcodec = "h264_vaapi" if preset == CompressPreset.fast else "hevc_vaapi"
    else:
        vcodec = "libx264" if preset == CompressPreset.fast else "libx265"

    args = [get_ffmpeg_path(), "-y"]

    if preset == CompressPreset.fast:
        codec_args = ["-c:v", vcodec, "-crf", "28", "-preset", "veryfast"]
    elif preset == CompressPreset.balanced:
        # N100-friendly: x265 fast preset instead of medium (2x speed, ~5% size increase)
        if hw == "software":
            codec_args = ["-c:v", vcodec, "-crf", "25", "-preset", "fast"]
        else:
            codec_args = ["-c:v", vcodec, "-crf", "25", "-preset", "medium"]
    elif preset == CompressPreset.high_quality:
        # N100-friendly: single-pass instead of 2-pass (3x speed)
        if hw == "software":
            codec_args = [
                "-c:v", "libx265",
                "-crf", "23",
                "-preset", "medium",
                "-x265-params", f"vbv-maxrate={max_br}:vbv-bufsize={target_br * 2}",
            ]
        else:
            codec_args = ["-c:v", vcodec, "-crf", "23", "-preset", "slow"]

    args += ["-i", input_path]

    # Scale filter if target resolution specified
    if target_width > 0 and target_height > 0:
        args += ["-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease"]

    args += codec_args
    args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]

    # Progress output to stderr for parsing
    args += ["-progress", "pipe:2", "-nostats"]

    args.append(output_path)
    return args


def parse_ffmpeg_progress(line: str) -> dict:
    """Parse FFmpeg -progress pipe:2 output line. Returns dict with optional keys."""
    result: dict = {}
    # out_time or time → current encoded timestamp
    m = re.search(r"(?:out_time|time)=(\d+):(\d+):(\d+\.\d+)", line)
    if m:
        h, m_, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        result["current_sec"] = h * 3600 + m_ * 60 + s
    # speed
    m = re.search(r"speed=\s*([\d.]+)x", line)
    if m:
        result["speed"] = float(m.group(1))
    # fps
    m = re.search(r"fps=\s*([\d.]+)", line)
    if m:
        result["fps"] = float(m.group(1))
    return result


async def run_compress_job(
    job_id: int, video_id: int,
    input_path: str, output_filename: str, output_dir: str,
    duration_sec: float, size_bytes: int,
    preset: CompressPreset,
    target_size_mb: int = 1000,
    target_width: int = 0,
    target_height: int = 0,
    thumbnail_layout: str = "3x3",
    thumbnail_id: int = None,
):
    # Init cancel/pause events for this job
    cancel_events.setdefault(job_id, asyncio.Event())
    pause_events.setdefault(job_id, asyncio.Event())
    job_stderr.setdefault(job_id, "")

    if should_skip_compression(size_bytes, target_size_mb):
        reason = f"文件已小于目标体积 ({size_bytes / 1_000_000:.1f}MB ≤ {target_size_mb}MB)"
        await broadcast({
            "type": "job_skip", "job_id": job_id,
            "reason": reason,
            "thumbnail_id": thumbnail_id,
        })
        _cleanup_job(job_id)
        return {"status": "skipped", "output_size": size_bytes, "output_path": input_path}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    await broadcast({
        "type": "job_start", "job_id": job_id,
        "video": Path(input_path).name,
        "preset": preset.value, "original_size": size_bytes,
        "thumbnail_id": thumbnail_id,
        "phase": "encoding",
    })

    start_time = time.time()

    cmd = build_ffmpeg_args(input_path, str(output_path), duration_sec, preset, target_size_mb, target_width, target_height)
    code, _, stderr_text = await _run_ffmpeg(cmd, duration_sec, job_id, 100, start_time)

    cancel_ev = cancel_events.get(job_id)
    if cancel_ev and cancel_ev.is_set():
        if output_path.exists():
            output_path.unlink()
        await broadcast({"type": "job_error", "job_id": job_id, "error": "Cancelled by user"})
        _cleanup_job(job_id)
        return {"status": "cancelled", "output_size": 0, "output_path": "", "stderr": stderr_text}

    if code != 0:
        await broadcast({"type": "job_error", "job_id": job_id, "error": stderr_text[:500]})
        _cleanup_job(job_id)
        return {"status": "failed", "output_size": 0, "output_path": "", "error": stderr_text[:500], "stderr": stderr_text}

    # Phase 2: Check size — retry with aggressive settings if needed (20% tolerance)
    if output_path.exists():
        output_size = output_path.stat().st_size
        target_bytes = target_size_mb * 1_000_000
        if output_size > target_bytes * 1.2:  # 20% tolerance
            await broadcast({
                "type": "progress", "job_id": job_id,
                "percent": 100, "eta_sec": 0, "phase": "retry_pass2",
                "elapsed_sec": round(time.time() - start_time),
                "speed": 0, "fps": 0,
            })
            retry_path = output_dir / f"retry_{output_filename}"
            cmd_retry = [
                get_ffmpeg_path(), "-y", "-i", input_path,
                "-c:v", "libx265", "-crf", "28", "-preset", "veryfast",
                "-vf", f"scale='min({target_width or 1280},iw)':min({target_height or 720},ih):force_original_aspect_ratio=decrease",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                str(retry_path),
            ]
            code2, _, _ = await _run_ffmpeg(cmd_retry, duration_sec, job_id, 100, start_time, "retry_pass2")
            cancel_ev = cancel_events.get(job_id)
            if cancel_ev and cancel_ev.is_set():
                if retry_path.exists(): retry_path.unlink()
                _cleanup_job(job_id)
                return {"status": "cancelled", "output_size": 0, "output_path": ""}
            if code2 == 0 and retry_path.exists():
                retry_size = retry_path.stat().st_size
                if retry_size <= target_bytes * 1.2:
                    output_path.unlink()
                    retry_path.rename(output_path)
                    output_size = retry_size
                else:
                    output_size = min(output_size, retry_size)
                    if output_size == retry_size:
                        output_path.unlink()
                        retry_path.rename(output_path)
                    else:
                        retry_path.unlink()
            else:
                # Retry failed — keep original output even if oversized
                stderr_text += f"\n[Retry pass failed; output may exceed target size ({output_size/1e6:.1f}MB > {target_size_mb}MB)]"
    else:
        output_size = 0

    # Cleanup
    log_file = Path(str(output_path) + ".log")
    if log_file.exists():
        log_file.unlink()

    await broadcast({
        "type": "job_done", "job_id": job_id,
        "output_size": output_size, "output_path": str(output_path),
        "ratio": round((1 - output_size / size_bytes) * 100, 1) if size_bytes else 0,
    })
    _cleanup_job(job_id)
    return {"status": "done", "output_size": output_size, "output_path": str(output_path), "stderr": stderr_text}


async def _run_ffmpeg(
    cmd: list[str], duration_sec: float, job_id: int,
    max_pct: float, start_time: float, phase: str = "encoding",
) -> tuple[int, float, str]:
    # Pre-flight cancel check — avoid spawning FFmpeg if already cancelled
    cancel_ev = cancel_events.get(job_id)
    if cancel_ev and cancel_ev.is_set():
        return -1, max_pct, "Cancelled before start"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    last_pct = 0.0
    last_broadcast = 0.0
    stderr_lines: list[str] = []
    latest_speed = 0.0
    latest_fps = 0.0

    async for line in proc.stderr:
        line_str = line.decode("utf-8", errors="ignore")
        stderr_lines.append(line_str)

        # Check cancel
        cancel_ev = cancel_events.get(job_id)
        if cancel_ev and cancel_ev.is_set():
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                proc.terminate()
            break

        # Check pause (SIGSTOP the FFmpeg process, listen for both resume and cancel)
        pause_ev = pause_events.get(job_id)
        if pause_ev and pause_ev.is_set():
            proc.send_signal(signal.SIGSTOP)
            pause_ev.clear()
            # Wait for either resume or cancel, to avoid deadlock
            done, pending = await asyncio.wait(
                [asyncio.create_task(pause_ev.wait()),
                 asyncio.create_task(cancel_ev.wait())] if cancel_ev else
                [asyncio.create_task(pause_ev.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            # If cancel was the trigger, break out of stderr loop
            if cancel_ev and cancel_ev.is_set():
                proc.send_signal(signal.SIGCONT)  # wake up FFmpeg so SIGTERM can be delivered
                try:
                    proc.send_signal(signal.SIGTERM)
                except Exception:
                    proc.terminate()
                break
            proc.send_signal(signal.SIGCONT)
            continue

        # Parse progress
        parsed = parse_ffmpeg_progress(line_str)
        if parsed.get("speed"):
            latest_speed = parsed["speed"]
        if parsed.get("fps"):
            latest_fps = parsed["fps"]

        if "current_sec" in parsed and duration_sec > 0:
            pct = min(parsed["current_sec"] / duration_sec * 100, max_pct * 0.99)
            now = time.time()
            if pct > last_pct + 1 or now - last_broadcast > 0.5:
                last_pct = pct
                last_broadcast = now
                elapsed = now - start_time
                eta = (elapsed / (pct / 100) - elapsed) if pct > 0 else 0
                await broadcast({
                    "type": "progress", "job_id": job_id,
                    "percent": round(pct, 1), "eta_sec": round(eta),
                    "elapsed_sec": round(elapsed),
                    "speed": round(latest_speed, 1) if latest_speed else 0,
                    "fps": round(latest_fps, 1) if latest_fps else 0,
                    "phase": phase,
                })

    await proc.wait()

    # Fallback: if no progress parsed, estimate from elapsed time
    if last_pct == 0.0:
        elapsed = time.time() - start_time
        if duration_sec > 0 and elapsed > 0:
            last_pct = min(round(elapsed / duration_sec * 100, 1), max_pct * 0.99)

    stderr_tail = "".join(stderr_lines[-50:]) if stderr_lines else ""
    job_stderr[job_id] = stderr_tail

    await broadcast({
        "type": "progress", "job_id": job_id,
        "percent": max_pct, "eta_sec": 0,
        "elapsed_sec": round(time.time() - start_time),
        "speed": round(latest_speed, 1) if latest_speed else 0,
        "fps": round(latest_fps, 1) if latest_fps else 0,
        "phase": phase + "_done",
    })

    return proc.returncode, max_pct, stderr_tail


def _cleanup_job(job_id: int):
    cancel_events.pop(job_id, None)
    pause_events.pop(job_id, None)
    job_stderr.pop(job_id, None)
