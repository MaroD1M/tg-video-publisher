from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database.connection import get_db, async_session
from app.database.models import User
from app.auth.utils import (
    hash_password,
    verify_password,
    create_jwt,
    verify_jwt,
    check_brute_force,
    record_login_failure,
    clear_login_failures,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Not authenticated")
    payload = await verify_jwt(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = await db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    return user


@router.post("/auth/login")
async def login(data: LoginRequest):
    if not await check_brute_force(data.username):
        raise HTTPException(429, "Too many attempts, please wait 15 minutes")

    async with async_session() as db:
        user = (await db.execute(
            select(User).where(User.username == data.username)
        )).scalar_one_or_none()

        if not user or not verify_password(data.password, user.password_hash):
            await record_login_failure(data.username)
            raise HTTPException(401, "Invalid credentials")

        await clear_login_failures(data.username)
        token = await create_jwt(user.id)
        return {"ok": True, "token": token, "username": user.username}


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "created_at": user.created_at.isoformat()}


@router.post("/auth/change-password")
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(400, "Old password is incorrect")
    user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"ok": True}


@router.get("/auth/has-users")
async def has_users(db: AsyncSession = Depends(get_db)):
    count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    return {"has_users": count > 0}


class ResetRequest(BaseModel):
    username: str


class ResetConfirm(BaseModel):
    username: str
    reset_token: str
    new_password: str


@router.post("/auth/request-reset")
async def request_reset(data: ResetRequest, db: AsyncSession = Depends(get_db)):
    """Generate a reset token and send it to admin via Telegram."""
    user = (await db.execute(
        select(User).where(User.username == data.username)
    )).scalar_one_or_none()

    if not user:
        # Don't reveal whether user exists
        return {"ok": True, "message": "如果该用户存在且已配置管理员通知，重置验证码已发送"}

    import secrets
    from app.modules.notifier import notify_admin
    from app.utils.helpers import set_setting, get_setting

    token = secrets.token_hex(16)
    expire_key = f"reset_token_{user.id}"
    hashed = hash_password(token)
    await set_setting(expire_key, f"{hashed}:{int(__import__('time').time())}")

    admin_id = await get_setting("admin_chat_id")
    if admin_id:
        await notify_admin(
            f"🔑 密码重置请求\n"
            f"用户: {user.username}\n"
            f"验证码: {token}\n"
            f"(有效期 10 分钟，将此验证码告知该用户)"
        )

    return {"ok": True, "message": "如果该用户存在且已配置管理员通知，重置验证码已发送"}


@router.post("/auth/reset-password")
async def confirm_reset(data: ResetConfirm, db: AsyncSession = Depends(get_db)):
    """Verify reset token and set new password."""
    user = (await db.execute(
        select(User).where(User.username == data.username)
    )).scalar_one_or_none()

    if not user:
        raise HTTPException(400, "用户不存在")

    import time
    from app.utils.helpers import get_setting

    expire_key = f"reset_token_{user.id}"
    stored = await get_setting(expire_key)
    if not stored:
        raise HTTPException(400, "未申请重置或验证码已过期")

    try:
        hashed_token, ts = stored.split(":")
        if time.time() - int(ts) > 600:
            raise HTTPException(400, "验证码已过期 (10 分钟)")
        if not verify_password(data.reset_token, hashed_token):
            raise HTTPException(400, "验证码错误")
    except ValueError:
        raise HTTPException(400, "验证码无效")

    from app.utils.helpers import set_setting
    user.password_hash = hash_password(data.new_password)
    await set_setting(expire_key, "")
    await db.commit()

    from app.modules.notifier import notify_admin
    await notify_admin(f"✅ 密码已重置: {user.username}")

    return {"ok": True, "message": "密码已重置，请使用新密码登录"}
