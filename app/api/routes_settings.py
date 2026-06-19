import shutil
import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.utils.helpers import (
    get_setting, set_setting, get_all_settings,
    regenerate_bot_api_env, restart_bot_api, check_bot_api_process, is_configured
)
from app.database.connection import get_db
from app.database.models import Video, CompressJob, ScheduleItem, PublishLog

router = APIRouter()


class SettingsUpdate(BaseModel):
    bot_token: Optional[str] = None
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    video_source_dir: Optional[str] = None
    output_dir: Optional[str] = None
    thumbnail_dir: Optional[str] = None
    compress_preset: Optional[str] = None
    thumbnail_layout: Optional[str] = None
    max_workers: Optional[str] = None
    proxy_enabled: Optional[str] = None
    proxy_type: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[str] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None
    admin_chat_id: Optional[str] = None
    thumb_caption_template: Optional[str] = None
    video_caption_template: Optional[str] = None
    admin_username: Optional[str] = None
    admin_password: Optional[str] = None


@router.get("/settings")
async def get_settings():
    return await get_all_settings()


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    AUTH_FIELDS = {"admin_username", "admin_password"}
    for key, value in data.model_dump(exclude_none=True).items():
        if value is not None and key not in AUTH_FIELDS:
            await set_setting(key, str(value))

    await regenerate_bot_api_env()

    if not await is_configured():
        raise HTTPException(400, "Missing required fields: bot_token, api_id, api_hash")

    return {"ok": True}


@router.post("/settings/setup")
async def complete_setup(data: SettingsUpdate, request: Request = None):
    from app.auth.utils import verify_jwt
    # If already configured, require auth (re-prevented by middleware, belt-and-suspenders)
    if await is_configured():
        auth_header = request.headers.get("authorization", "") if request else ""
        token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()
        if not token or not await verify_jwt(token):
            raise HTTPException(401, "System already configured. Please login.")

    if not data.bot_token or not data.api_id or not data.api_hash:
        raise HTTPException(400, "bot_token, api_id, api_hash are required")

    AUTH_FIELDS = {"admin_username", "admin_password"}
    for key, value in data.model_dump(exclude_none=True).items():
        if value is not None and key not in AUTH_FIELDS:
            await set_setting(key, str(value))

    await regenerate_bot_api_env()

    # Create admin user if this is first setup and credentials provided
    if data.admin_username and data.admin_password:
        from app.database.connection import async_session
        from app.database.models import User
        from app.auth.utils import hash_password
        from sqlalchemy import select
        async with async_session() as db:
            existing = (await db.execute(select(User))).scalars().all()
            if not existing:
                db.add(User(
                    username=data.admin_username,
                    password_hash=hash_password(data.admin_password),
                ))
                await db.commit()

    return {"ok": True, "configured": True}


@router.get("/settings/proxy")
async def get_proxy():
    return {
        "enabled": await get_setting("proxy_enabled"),
        "type": await get_setting("proxy_type", "socks5"),
        "host": await get_setting("proxy_host", "127.0.0.1"),
        "port": await get_setting("proxy_port", "1080"),
        "username": await get_setting("proxy_user"),
        "password": "****" if await get_setting("proxy_pass") else "",
    }


@router.put("/settings/proxy")
async def update_proxy(data: SettingsUpdate):
    fields = ["proxy_enabled", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass"]
    for f in fields:
        val = getattr(data, f, None)
        if val is not None:
            await set_setting(f, str(val))

    await regenerate_bot_api_env()
    return {"ok": True}


@router.post("/settings/proxy/test")
async def test_proxy():
    proxy_enabled = await get_setting("proxy_enabled")
    if proxy_enabled != "true":
        return {"success": True, "message": "No proxy configured, using direct connection"}

    ptype = await get_setting("proxy_type", "socks5")
    phost = await get_setting("proxy_host", "127.0.0.1")
    pport = await get_setting("proxy_port", "1080")

    try:
        import urllib.request
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((phost, int(pport)))
        sock.close()
        return {"success": True, "message": f"{ptype} proxy {phost}:{pport} is reachable"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/settings/apply")
async def apply_settings():
    await regenerate_bot_api_env()
    ok, info = await restart_bot_api()
    if not ok:
        return {"ok": False, "message": f"Bot API 重启失败: {info[:200]}"}
    return {"ok": True, "message": "Bot API 已发送重启指令，约需 3 秒生效"}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    total_videos = (await db.execute(select(func.count(Video.id)))).scalar() or 0
    compressed = (await db.execute(
        select(func.count(Video.id)).where(Video.status.in_(["compressed", "skipped"]))
    )).scalar() or 0
    queued = (await db.execute(
        select(func.count(ScheduleItem.id)).where(ScheduleItem.status == "queued")
    )).scalar() or 0
    today = (await db.execute(
        select(func.count(PublishLog.id)).where(
            PublishLog.success == True,
            func.date(PublishLog.published_at) == func.date('now'),
        )
    )).scalar() or 0

    # Real Bot API check (fast timeout — don't block page load)
    import asyncio as _asyncio
    bot_ok = False
    bot_error = None
    try:
        from app.bot.client import ensure_bot
        bot_ok, bot_error, _ = await _asyncio.wait_for(
            ensure_bot(), timeout=2
        )
    except _asyncio.TimeoutError:
        bot_ok = False
        bot_error = "连接超时 (Bot API 正在启动...)"
    except Exception as e:
        bot_ok = False
        bot_error = str(e)[:200]

    # Compress job counts
    compress_running = (await db.execute(
        select(func.count(CompressJob.id)).where(CompressJob.status == "running")
    )).scalar() or 0
    compress_queued = (await db.execute(
        select(func.count(CompressJob.id)).where(CompressJob.status == "queued")
    )).scalar() or 0

    # Last publish time
    last_publish = None
    last_row = (await db.execute(
        select(PublishLog.published_at).where(PublishLog.success == True).order_by(PublishLog.published_at.desc()).limit(1)
    )).scalar_one_or_none()
    if last_row:
        now = datetime.datetime.utcnow()
        diff = now - last_row
        if diff.total_seconds() < 120:
            last_publish = "刚刚"
        elif diff.total_seconds() < 3600:
            last_publish = f"{int(diff.total_seconds() / 60)} 分钟前"
        elif diff.total_seconds() < 86400:
            last_publish = f"{int(diff.total_seconds() / 3600)} 小时前"
        else:
            last_publish = f"{diff.days} 天前"

    return {
        "total_videos": total_videos,
        "compressed": compressed,
        "queued": queued,
        "today_published": today,
        "bot": bot_ok,
        "bot_error": bot_error,
        "api": True,
        "compress_running": compress_running,
        "compress_queued": compress_queued,
        "last_publish": last_publish,
    }


@router.get("/disk")
async def get_disk():
    output_dir = await get_setting("output_dir", "/data/output")
    try:
        usage = shutil.disk_usage(output_dir)
        used_gb = (usage.total - usage.free) / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        percent = round((used_gb / total_gb) * 100, 1)
        return {"used_gb": round(used_gb, 2), "total_gb": round(total_gb, 2), "percent": percent}
    except Exception:
        return {"used_gb": 0, "total_gb": 100, "percent": 0}


# ── Chat / Channel management ──

@router.get("/chats")
async def list_chats():
    from app.bot.client import discover_chats
    chats = await discover_chats()
    return {"items": chats}


@router.post("/chats/verify")
async def verify_chat(chat_id: int = Query(...)):
    from app.bot.client import verify_chat as do_verify
    return await do_verify(chat_id)


@router.post("/chats/refresh")
async def refresh_chats():
    from app.bot.client import discover_chats
    chats = await discover_chats()
    return {"items": chats}


@router.get("/bot/status")
async def bot_status():
    """Detailed Bot API diagnostic info."""
    from app.utils.helpers import get_setting
    from app.bot.client import get_bot
    from app.database.connection import async_session
    from app.database.models import TargetChat
    from sqlalchemy import select, func
    from app.config import BOT_API_ENV_FILE
    import socket

    token = await get_setting("bot_token")
    api_id = await get_setting("api_id")
    api_hash = await get_setting("api_hash")
    admin_chat_id = await get_setting("admin_chat_id")
    proxy_enabled = await get_setting("proxy_enabled", "false")

    config = {
        "bot_token": bool(token),
        "bot_token_preview": (token[:10] + "..." + token[-5:]) if token else None,
        "api_id": api_id or None,
        "api_hash": bool(api_hash),
        "admin_chat_id": admin_chat_id or None,
        "proxy_enabled": proxy_enabled == "true",
    }

    # Proxy config details
    proxy_config = None
    if proxy_enabled == "true":
        proxy_config = {
            "type": await get_setting("proxy_type", "socks5"),
            "host": await get_setting("proxy_host", ""),
            "port": await get_setting("proxy_port", ""),
            "has_auth": bool(await get_setting("proxy_user", "")),
        }

    bot_server_ok = False
    bot_server_error = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(('127.0.0.1', 8081))
        sock.close()
        bot_server_ok = True
    except Exception as e:
        bot_server_error = str(e)[:200]

    bot_ok = False
    bot_error = None
    bot_username = None
    try:
        from app.bot.client import ensure_bot
        bot_ok, bot_error, bot_username = await ensure_bot()
    except Exception as e:
        bot_error = str(e)[:200]

    # DNS check — test MTProto DC, not just HTTP API
    dns_ok = False
    dns_ips = []
    dns_error = None
    try:
        addrs = socket.getaddrinfo("pluto.web.telegram.org", 443, socket.AF_INET, socket.SOCK_STREAM)
        dns_ips = sorted(set(a[4][0] for a in addrs))
        dns_ok = len(dns_ips) > 0
    except Exception as e:
        dns_error = str(e)[:200]

    # Proxy connectivity test
    proxy_ok = None
    proxy_error = None
    if proxy_enabled == "true":
        try:
            phost = await get_setting("proxy_host", "")
            pport = int(await get_setting("proxy_port", "0"))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((phost, pport))
            sock.close()
            proxy_ok = True
        except Exception as e:
            proxy_ok = False
            proxy_error = str(e)[:200]

    # Env file check
    env_exists = BOT_API_ENV_FILE.exists()
    env_has_api_id = False
    env_has_proxy = False
    if env_exists:
        content = BOT_API_ENV_FILE.read_text()
        env_has_api_id = "API_ID=" in content
        env_has_proxy = "TD_PROXY=" in content

    # Bot API server process status via supervisorctl
    proc_status = await check_bot_api_process()

    # Generate diagnosis
    diagnosis = []
    if not token:
        diagnosis.append({"level": "error", "msg": "Bot Token 未配置，请到系统设置页填写"})
    if not api_id or not api_hash:
        diagnosis.append({"level": "error", "msg": "API ID 或 API Hash 未配置，请从 my.telegram.org 获取"})
    if not bot_server_ok:
        diag = f"Bot API 服务器 (localhost:8081) 无法连接: {bot_server_error or '未知'}."
        if proc_status["state"] in ("BACKOFF", "EXITED", "FATAL"):
            diag += f" 进程状态: {proc_status['state']} (反复启动失败，请检查 DNS/代理/API 凭证)"
        elif proc_status["state"] == "STOPPED":
            diag += " 进程已停止，请点系统设置 > 应用并重启"
        diagnosis.append({"level": "error", "msg": diag})
    if not dns_ok:
        diagnosis.append({"level": "error", "msg": f"DNS 无法解析 Telegram MTProto DC (pluto.web.telegram.org): {dns_error}. 国内服务器不能使用 8.8.8.8，请改为 223.5.5.5 等国内 DNS"})
    if proxy_enabled != "true" and not dns_ok:
        diagnosis.append({"level": "warn", "msg": "容器无法直连 Telegram，请到系统设置页启用代理"})
    if proxy_enabled == "true" and proxy_ok is False:
        diagnosis.append({"level": "error", "msg": f"代理 {proxy_config.get('host','')}:{proxy_config.get('port','')} 连接失败: {proxy_error}. 检查代理服务器是否运行"})
    if proxy_enabled == "true" and proxy_ok and bot_server_ok and dns_ok and not bot_ok:
        diagnosis.append({"level": "warn", "msg": f"代理和网络正常但 Bot 连接失败: {bot_error}. 请检查 Bot Token 或 API ID/Hash 是否正确"})
    if proxy_enabled == "true" and proxy_ok and env_exists and not env_has_proxy:
        diagnosis.append({"level": "warn", "msg": "代理已配置但 bot-api.env 未写入代理设置，请点系统设置 > 应用并重启"})
    if bot_ok:
        diagnosis.append({"level": "success", "msg": f"Bot @{bot_username} 连接正常"})
    if not diagnosis:
        diagnosis.append({"level": "info", "msg": "正在诊断中..."})

    channel_count = 0
    try:
        async with async_session() as db:
            channel_count = (await db.execute(
                select(func.count(TargetChat.id))
            )).scalar() or 0
    except Exception:
        pass

    return {
        "config": config,
        "bot_server": {"ok": bot_server_ok, "error": bot_server_error, "process": {
            "state": proc_status["state"],
            "pid": proc_status["pid"],
            "uptime": proc_status["uptime"],
        }},
        "bot": {"ok": bot_ok, "error": bot_error, "username": bot_username},
        "dns": {"ok": dns_ok, "ips": dns_ips, "error": dns_error, "target": "pluto.web.telegram.org"},
        "proxy": {"check": proxy_ok, "error": proxy_error, "config": proxy_config},
        "env": {"exists": env_exists, "has_api_id": env_has_api_id, "has_proxy": env_has_proxy},
        "diagnosis": diagnosis,
        "channel_count": channel_count,
    }


@router.get("/version")
async def get_version():
    from app.version import CURRENT_VERSION, BUILD_DATE
    return {"version": CURRENT_VERSION, "build_date": BUILD_DATE}


@router.get("/version/check")
async def check_version():
    from app.version import CURRENT_VERSION, check_remote_version
    return await check_remote_version()
