import hashlib
import os
import time
import secrets
from jose import jwt, JWTError

from app.utils.helpers import get_setting, set_setting

_JWT_SECRET: str | None = None


async def get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is not None:
        return _JWT_SECRET
    secret = await get_setting("jwt_secret")
    if not secret:
        secret = secrets.token_urlsafe(32)
        await set_setting("jwt_secret", secret)
    _JWT_SECRET = secret
    return _JWT_SECRET


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return salt.hex() + ":" + key.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
        if new_key == key:
            return True
        # Fallback for passwords hashed with old iteration count (100K)
        old_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return old_key == key
    except Exception:
        return False


async def create_jwt(user_id: int) -> str:
    secret = await get_jwt_secret()
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "exp": now + 7 * 86400, "iat": now},
        secret,
        algorithm="HS256",
    )


async def verify_jwt(token: str) -> dict | None:
    secret = await get_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None


async def check_brute_force(username: str) -> bool:
    key = f"login_fail_{username}"
    count = await get_setting(key, "0")
    last = await get_setting(f"{key}_time", "0")
    try:
        attempts = int(count)
        last_time = float(last)
    except (ValueError, TypeError):
        await set_setting(key, "0")
        return True

    if attempts >= 5 and time.time() - last_time < 900:
        return False  # blocked
    if time.time() - last_time >= 900:
        await set_setting(key, "0")
    return True


async def record_login_failure(username: str):
    key = f"login_fail_{username}"
    count = await get_setting(key, "0")
    try:
        new_count = int(count) + 1
    except (ValueError, TypeError):
        new_count = 1
    await set_setting(key, str(new_count))
    await set_setting(f"{key}_time", str(time.time()))


async def clear_login_failures(username: str):
    await set_setting(f"login_fail_{username}", "0")


async def reset_admin_password(password: str):
    from app.database.connection import async_session
    from app.database.models import User
    from sqlalchemy import select

    async with async_session() as db:
        user = (await db.execute(select(User).order_by(User.id).limit(1))).scalar_one_or_none()
        if not user:
            user = User(username="admin", password_hash=hash_password(password))
            db.add(user)
        else:
            user.password_hash = hash_password(password)
        await db.commit()
