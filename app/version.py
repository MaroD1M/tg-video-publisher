import os
import json
import asyncio
from urllib import request as urllib_request
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def get_local_version() -> str:
    """Read the current version from the VERSION file."""
    try:
        vf = VERSION_FILE
        if not vf.exists():
            # Docker layout: /app/VERSION
            vf = Path("/app/VERSION")
        if vf.exists():
            return vf.read_text().strip()
    except Exception:
        pass
    return "unknown"


CURRENT_VERSION = get_local_version()


def get_build_date() -> str:
    """Read the build date from BUILD_DATE file."""
    try:
        bf = Path(__file__).resolve().parent.parent / "BUILD_DATE"
        if not bf.exists():
            bf = Path("/app/BUILD_DATE")
        if bf.exists():
            return bf.read_text().strip()
    except Exception:
        pass
    return "unknown"


BUILD_DATE = get_build_date()

VERSION_CHECK_URL = "https://raw.githubusercontent.com/MaroD1M/tg-video-publisher/main/VERSION"


async def check_remote_version() -> dict:
    """Fetch remote VERSION from GitHub and compare."""
    local = CURRENT_VERSION

    def _fetch():
        req = urllib_request.Request(VERSION_CHECK_URL)
        req.add_header("User-Agent", "TGVideoPublisher")
        with urllib_request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8").strip()

    try:
        remote = await asyncio.to_thread(_fetch)
    except Exception:
        return {"local": local, "remote": None, "has_update": False, "error": "无法获取远端版本"}

    has_update = False
    try:
        local_parts = [int(x) for x in local.split(".")]
        remote_parts = [int(x) for x in remote.split(".")]
        for i in range(max(len(local_parts), len(remote_parts))):
            lv = local_parts[i] if i < len(local_parts) else 0
            rv = remote_parts[i] if i < len(remote_parts) else 0
            if rv > lv:
                has_update = True
                break
            if rv < lv:
                break
    except Exception:
        has_update = remote != local

    return {"local": local, "remote": remote, "has_update": has_update}
