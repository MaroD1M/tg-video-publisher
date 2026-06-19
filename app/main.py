import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database.models import Base
from app.database.connection import engine
from app.utils.helpers import is_configured
from app.config import CONFIG_DIR
from app.version import CURRENT_VERSION, check_remote_version


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    Path("/app/config/bot-api-data").mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run any pending migrations
    from app.database.migrations import run_migrations
    await run_migrations()

    try:
        if await is_configured():
            from app.modules.scheduler import start_scheduler
            await start_scheduler()
        await start_compress_worker()
        await start_publish_worker()
    except Exception as e:
        logging.getLogger("uvicorn").warning(f"Startup failed: {e}")

    yield


app = FastAPI(
    title="TG视频发布助手",
    version=CURRENT_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

# ── Auth middleware (must be before routes) ──
from app.auth.middleware import JWTAuthMiddleware
app.add_middleware(JWTAuthMiddleware)


@app.get("/api/health")
async def health():
    issues = []
    db_ok = True
    bot_ok = True
    disk_ok = True

    # Check DB
    try:
        from sqlalchemy import text
        from app.database.connection import async_session
        async with async_session() as s:
            await s.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        issues.append(f"db: {e}")

    # Check Bot API
    try:
        from app.bot.client import ensure_bot
        ok, err, _ = await ensure_bot()
        if not ok:
            bot_ok = False
            issues.append(f"bot: {err or 'not configured'}")
    except Exception as e:
        bot_ok = False
        issues.append(f"bot: {e}")

    # Check disk writable
    try:
        test_file = Path("/tmp/health_check_test")
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as e:
        disk_ok = False
        issues.append(f"disk: {e}")

    all_ok = db_ok and bot_ok and disk_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "configured": await is_configured(),
        "db": db_ok,
        "bot": bot_ok,
        "disk": disk_ok,
        "issues": issues if issues else None,
    }


@app.get("/api/setup/status")
async def setup_status():
    return {
        "configured": await is_configured(),
    }


# API routes
from app.auth.routes import router as auth_router
from app.api.routes_settings import router as settings_router
from app.api.routes_videos import router as videos_router
from app.api.routes_compress import router as compress_router, start_worker as start_compress_worker
from app.api.routes_thumbnails import router as thumbnails_router
from app.api.routes_schedules import router as schedules_router
from app.api.routes_logs import router as logs_router
from app.api.websocket import router as ws_router
from app.api.routes_publish import router as publish_router, start_publish_worker
from app.api.routes_notify import router as notify_router
from app.api.routes_disk import router as disk_router

app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(settings_router, prefix="/api", tags=["settings"])
app.include_router(videos_router, prefix="/api", tags=["videos"])
app.include_router(compress_router, prefix="/api", tags=["compress"])
app.include_router(thumbnails_router, prefix="/api", tags=["thumbnails"])
app.include_router(schedules_router, prefix="/api", tags=["schedules"])
app.include_router(logs_router, prefix="/api", tags=["logs"])
app.include_router(ws_router, tags=["websocket"])
app.include_router(publish_router, prefix="/api", tags=["publish"])
app.include_router(notify_router, prefix="/api", tags=["notifications"])
app.include_router(disk_router, prefix="/api", tags=["disk"])


# Serve SPA
frontend_dir = Path(__file__).resolve().parent.parent / "static"
if frontend_dir.exists():
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = frontend_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dir / "index.html")
