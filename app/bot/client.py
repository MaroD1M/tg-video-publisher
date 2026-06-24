from telegram import Bot
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from app.utils.helpers import get_setting
from app.config import BOT_API_URL

_bot: Bot | None = None
_bot_ready: bool = False

_bot_request = HTTPXRequest(
    connect_timeout=10,
    write_timeout=120,
    read_timeout=7200,
    connection_pool_size=20,
    pool_timeout=15,
)


async def get_bot() -> Bot | None:
    global _bot
    if _bot is not None:
        return _bot
    token = await get_setting("bot_token")
    if not token:
        return None
    _bot = Bot(
        token=token,
        base_url=BOT_API_URL,
        local_mode=True,
        request=_bot_request,
    )
    return _bot


async def ensure_bot() -> tuple[bool, str | None, str | None]:
    """Validate bot connection. Returns (ok, error, username)."""
    global _bot_ready
    try:
        bot = await get_bot()
        if not bot:
            return (False, "bot_token 未配置", None)
        me = await bot.get_me()
        _bot_ready = True
        return (True, None, me.username)
    except Exception as e:
        _bot_ready = False
        return (False, str(e)[:200], None)


async def reset_bot():
    global _bot, _bot_ready
    _bot = None
    _bot_ready = False


async def discover_chats() -> list[dict]:
    """Return all known chats: DB-stored + recently discovered."""
    from app.database.connection import async_session
    from app.database.models import TargetChat
    from sqlalchemy import select

    chats = []
    seen = set()

    # First: load from DB (persistent)
    async with async_session() as db:
        rows = (await db.execute(select(TargetChat))).scalars().all()
        for r in rows:
            chats.append({
                "chat_id": r.chat_id,
                "chat_name": r.chat_name or str(r.chat_id),
                "alias": r.alias,
                "chat_type": r.chat_type,
                "linked_chat_id": r.linked_chat_id,
                "is_forum": False,
            })
            seen.add(r.chat_id)

    # Second: attempt recent update discovery
    bot = await get_bot()
    if bot:
        try:
            updates = await bot.get_updates(limit=100, timeout=5)
            for u in updates:
                chat = None
                if u.channel_post:
                    chat = u.channel_post.chat
                elif u.message:
                    chat = u.message.chat
                elif u.edited_channel_post:
                    chat = u.edited_channel_post.chat
                elif u.edited_message:
                    chat = u.edited_message.chat
                if chat and chat.id not in seen and chat.type in ("channel", "supergroup"):
                    seen.add(chat.id)
                    try:
                        full = await bot.get_chat(chat.id)
                        info = _chat_to_dict(full)
                        chats.append(info)
                        await _save_chat(info)
                    except TelegramError:
                        pass
        except TelegramError:
            pass

    return chats


async def verify_chat(chat_id: int) -> dict:
    bot = await get_bot()
    if not bot:
        return {"ok": False, "error": "Bot not configured"}

    try:
        chat = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
        is_admin = member.status in ("administrator", "creator")
        has_discussion = getattr(chat, "linked_chat_id", None)

        result = {
            "ok": True,
            "chat_id": chat_id,
            "chat_name": chat.title or chat.username or str(chat_id),
            "chat_type": chat.type,
            "is_admin": is_admin,
            "can_post": getattr(member, "can_post_messages", is_admin),
            "linked_chat_id": has_discussion,
        }

        # Save verified chat to DB
        await _save_chat(result)

        # Load alias from DB
        async with async_session() as db:
            tc = await db.get(TargetChat, chat_id)
            if tc and tc.alias:
                result["alias"] = tc.alias

        return result
    except TelegramError as e:
        return {"ok": False, "error": str(e)}


async def _save_chat(info: dict):
    from app.database.connection import async_session
    from app.database.models import TargetChat
    from sqlalchemy import select

    async with async_session() as db:
        existing = await db.get(TargetChat, info["chat_id"])
        if not existing:
            db.add(TargetChat(
                chat_id=info["chat_id"],
                chat_name=info.get("chat_name", ""),
                chat_type=info.get("chat_type", ""),
                linked_chat_id=info.get("linked_chat_id"),
                is_active=True,
            ))
        else:
            # Update name and type from Telegram (preserve user alias)
            existing.chat_name = info.get("chat_name", existing.chat_name)
            existing.chat_type = info.get("chat_type", existing.chat_type)
            if info.get("linked_chat_id") is not None:
                existing.linked_chat_id = info.get("linked_chat_id")
        await db.commit()


def _chat_to_dict(chat) -> dict:
    return {
        "chat_id": chat.id,
        "chat_name": chat.title or chat.username or str(chat.id),
        "chat_type": chat.type,
        "linked_chat_id": getattr(chat, "linked_chat_id", None),
        "is_forum": getattr(chat, "is_forum", False),
    }
