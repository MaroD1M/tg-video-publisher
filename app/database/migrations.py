"""Schema migration support: auto-add missing tables/columns on startup."""
import logging
from sqlalchemy import text
from app.database.connection import engine

_log = logging.getLogger("tgvp.migrations")


MISSING_COLUMNS = {
    "schedules": [
        ("thumb_caption_template", "TEXT DEFAULT ''"),
        ("video_caption_template", "TEXT DEFAULT ''"),
    ],
    "compress_jobs": [
        ("target_size_mb", "INTEGER DEFAULT 1000"),
        ("target_width", "INTEGER DEFAULT 0"),
        ("target_height", "INTEGER DEFAULT 0"),
        ("schedule_id", "INTEGER DEFAULT 0"),
        ("publish_after", "BOOLEAN DEFAULT 0"),
        ("publish_channel_id", "BIGINT DEFAULT 0"),
    ],
    "publish_tasks": [
        ("sort_order", "INTEGER DEFAULT 0"),
        ("is_paused", "BOOLEAN DEFAULT 0"),
        ("step_log", "TEXT"),
        ("schedule_id", "INTEGER DEFAULT 0"),
    ],
}


async def run_migrations():
    """Apply any pending schema changes to the database."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_tables)
        await _add_missing_columns(conn)

    _log.info("Migrations complete")


def _ensure_tables(connection):
    """Create any missing tables (idempotent)."""
    from app.database.models import Base
    Base.metadata.create_all(connection, checkfirst=True)


async def _add_missing_columns(conn):
    """Add missing columns to existing tables."""
    for table, columns in MISSING_COLUMNS.items():
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing:
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                ))
                _log.info(f"Migration: added {col_name} to {table}")
