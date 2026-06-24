import json
import asyncio
from telegram.error import TelegramError
from app.utils.helpers import get_setting
import logging
import time

_log = logging.getLogger("tgvp.notifier")

_last_sent: dict[str, float] = {}
_freq_lock = asyncio.Lock()
_FREQUENCY_WINDOW = 30  # seconds between same-type notifications


async def notify_admin(message: str, event_type: str = "", variables: dict | None = None):
    """Send notification respecting user-configured settings."""
    from app.database.connection import async_session
    from app.database.models import NotificationConfig
    from sqlalchemy import select

    # Check frequency limit
    if not await _check_frequency(event_type):
        return

    # Read notification config
    template = message
    target_ids = []
    enabled = True

    if event_type:
        async with async_session() as db:
            row = (await db.execute(
                select(NotificationConfig).where(NotificationConfig.event_type == event_type)
            )).scalar_one_or_none()
            if row:
                enabled = row.enabled
                if row.template:
                    template = row.template
                if row.target_chat_ids:
                    target_ids = [int(x.strip()) for x in row.target_chat_ids.split(",") if x.strip()]

    if not enabled:
        return

    # Render template with variables
    if variables:
        try:
            for key, value in variables.items():
                template = template.replace(f"{{{key}}}", str(value) if value is not None else "")
        except Exception:
            pass

    # Determine targets
    if not target_ids:
        chat_id_str = await get_setting("admin_chat_id")
        if chat_id_str:
            try:
                target_ids = [int(chat_id_str)]
            except ValueError:
                target_ids = []

    if not target_ids:
        return

    from app.bot.client import get_bot
    bot = await get_bot()
    if not bot:
        return

    for chat_id in target_ids:
        try:
            text = template[:4096]  # Telegram message limit
            await bot.send_message(chat_id=chat_id, text=text)
        except TelegramError as e:
            _log.warning(f"Failed to notify {chat_id}: {e}")


async def _check_frequency(event_type: str) -> bool:
    if not event_type:
        return True
    now = time.time()
    async with _freq_lock:
        last = _last_sent.get(event_type, 0)
        if now - last < _FREQUENCY_WINDOW:
            return False
        _last_sent[event_type] = now
        return True
