from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.database.connection import get_db
from app.database.models import NotificationConfig

router = APIRouter()

DEFAULT_TEMPLATES = {
    "compress_done": "✅ 压缩完成: {filename}\n{size} → {out_size} ({ratio}%)",
    "compress_fail": "❌ 压缩失败: {filename}\n{error}",
    "publish_done": "📤 发布成功: {filename}\n频道: {channel}",
    "publish_fail": "❌ 发布失败: {filename}\n{error}",
    "bot_status": "🤖 Bot 状态变更: {status} @{username}",
}

DEFAULT_TARGETS = ""


class NotificationConfigUpdate(BaseModel):
    event_type: str
    enabled: Optional[bool] = None
    template: Optional[str] = None
    target_chat_ids: Optional[str] = None


@router.get("/settings/notifications")
async def get_notifications(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(NotificationConfig).order_by(NotificationConfig.event_type))).scalars().all()
    existing = {r.event_type: r for r in rows}

    items = []
    for event_type in DEFAULT_TEMPLATES:
        row = existing.get(event_type)
        items.append({
            "event_type": event_type,
            "enabled": row.enabled if row else True,
            "template": row.template if row and row.template else DEFAULT_TEMPLATES[event_type],
            "target_chat_ids": row.target_chat_ids if row else DEFAULT_TARGETS,
        })

    return {"items": items}


@router.put("/settings/notifications")
async def update_notification(data: NotificationConfigUpdate, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(NotificationConfig).where(NotificationConfig.event_type == data.event_type)
    )).scalar_one_or_none()

    if not row:
        row = NotificationConfig(event_type=data.event_type)
        db.add(row)

    if data.enabled is not None:
        row.enabled = data.enabled
    if data.template is not None:
        row.template = data.template
    if data.target_chat_ids is not None:
        row.target_chat_ids = data.target_chat_ids

    if row.template == DEFAULT_TEMPLATES.get(data.event_type):
        row.template = ""
    await db.commit()
    return {"ok": True}
