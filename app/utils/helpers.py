import asyncio
import json
import shutil
from pathlib import Path

from app.config import CONFIG_DIR, BOT_API_ENV_FILE
from app.database.connection import async_session
from app.database.models import Setting


async def get_setting(key: str, default: str = "") -> str:
    async with async_session() as s:
        row = await s.get(Setting, key)
        return row.value if row else default


async def set_setting(key: str, value: str):
    async with async_session() as s:
        row = await s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        await s.commit()


async def get_all_settings() -> dict[str, str]:
    async with async_session() as s:
        from sqlalchemy import select
        rows = (await s.execute(select(Setting))).scalars().all()
        return {r.key: r.value for r in rows}


async def is_configured() -> bool:
    token = await get_setting("bot_token")
    api_id = await get_setting("api_id")
    api_hash = await get_setting("api_hash")
    return bool(token and api_id and api_hash)


async def get_video_source_dirs() -> list[str]:
    dirs_raw = await get_setting("video_source_dirs")
    if dirs_raw:
        try:
            dirs = json.loads(dirs_raw)
            if isinstance(dirs, list) and len(dirs) > 0 and all(isinstance(d, str) for d in dirs):
                return dirs
        except (json.JSONDecodeError, TypeError):
            pass
    old = await get_setting("video_source_dir")
    if old:
        return [old]
    return ["/data/videos"]


def _sanitize_env_value(value: str) -> str:
    return "".join(c for c in value if c.isprintable() and c not in "\r\n")

async def regenerate_bot_api_env():
    import os
    api_id = _sanitize_env_value(await get_setting("api_id"))
    api_hash = _sanitize_env_value(await get_setting("api_hash"))
    proxy_enabled = await get_setting("proxy_enabled")

    lines = []
    if api_id and api_hash:
        lines.append(f"API_ID={api_id}")
        lines.append(f"API_HASH={api_hash}")

    # Only generate proxy config from Web UI if no BOT_API_PROXY env var
    # (env var means proxychains handles all traffic transparently)
    if proxy_enabled == "true" and not os.environ.get("BOT_API_PROXY"):
        ptype = await get_setting("proxy_type", "http")
        phost = await get_setting("proxy_host", "127.0.0.1")
        pport = await get_setting("proxy_port", "7890")
        puser = await get_setting("proxy_user", "")
        ppass = await get_setting("proxy_pass", "")

        if ptype == "mtproto":
            from urllib.parse import quote
            proxy_url = f"mtproto://{quote(ppass, safe='')}@{phost}:{pport}"
        else:
            from urllib.parse import quote
            auth = f"{quote(puser, safe='')}:{quote(ppass, safe='')}@" if puser else ""
            # telegram-bot-api --proxy only accepts http:// format
            proxy_url = f"http://{auth}{phost}:{pport}"

        lines.append(f'TD_PROXY="--proxy {proxy_url}"')

        if ptype != "mtproto":
            lines.append(f'HTTP_PROXY={proxy_url}')

    BOT_API_ENV_FILE.write_text("\n".join(lines) + "\n")


async def restart_bot_api() -> tuple:
    import logging
    try:
        proc = await asyncio.create_subprocess_exec(
            "supervisorctl", "-c", "/etc/supervisor/conf.d/app.conf",
            "-s", "unix:///var/run/supervisor.sock",
            "restart", "bot-api",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            err = (stderr.decode() + stdout.decode()).strip()[:200] or f"exit code {proc.returncode}"
            logging.getLogger("tgvp").warning(f"Bot API restart failed: {err}")
            return False, err
        return True, stdout.decode()[:200]
    except Exception as e:
        logging.getLogger("tgvp").warning(f"Bot API restart error: {e}")
        return False, str(e)


async def check_bot_api_process() -> dict:
    import logging
    try:
        proc = await asyncio.create_subprocess_exec(
            "supervisorctl", "-c", "/etc/supervisor/conf.d/app.conf",
            "-s", "unix:///var/run/supervisor.sock",
            "status", "bot-api",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        output = stdout.decode().strip()
        if not output:
            return {"state": "UNKNOWN", "pid": None, "uptime": None}
        parts = output.split()
        state = parts[1] if len(parts) > 1 else "UNKNOWN"
        pid = None
        uptime = None
        if len(parts) > 3 and parts[3] != "pid" and "," in output:
            try:
                pid = int(parts[3].rstrip(","))
            except ValueError:
                pass
        if "uptime" in output:
            idx = output.find("uptime")
            if idx > 0:
                uptime = output[idx:].split()[1:][:3]
                uptime = " ".join(uptime) if uptime else None
        return {"state": state, "pid": pid, "uptime": uptime}
    except Exception as e:
        logging.getLogger("tgvp").warning(f"Bot API process check error: {e}")
        return {"state": "UNKNOWN", "pid": None, "uptime": None}


def get_ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    return path or "/usr/bin/ffmpeg"


def get_ffprobe_path() -> str:
    path = shutil.which("ffprobe")
    return path or "/usr/bin/ffprobe"
