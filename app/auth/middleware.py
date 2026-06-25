from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.utils import verify_jwt

PUBLIC_PREFIXES = [
    "/api/health",
    "/api/setup/status",
    "/api/auth/login",
    "/api/auth/has-users",
    "/api/auth/request-reset",
    "/api/auth/reset-password",
    "/api/docs",
    "/api/openapi.json",
    "/ws/compress",
    "/api/version",
    "/api/version/check",
]
PUBLIC_EXACT = [
    "/", "/favicon.svg",
    "/login", "/setup",
    "/compress", "/publish-tasks", "/schedules", "/history",
    "/thumbnails", "/settings", "/bot-status", "/disk-cleanup",
]


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # ① System not configured → allow setup-relevant routes only
        from app.utils.helpers import is_configured
        configured = await is_configured()
        if not configured:
            # Allow public API prefixes AND the setup endpoint
            if path.startswith("/api/settings/setup"):
                return await call_next(request)
            for prefix in PUBLIC_PREFIXES:
                if path.startswith(prefix):
                    return await call_next(request)
            # Allow SPA routes for setup wizard
            if path in PUBLIC_EXACT or path.startswith("/assets/") or path.endswith(".svg"):
                return await call_next(request)
            return JSONResponse({"detail": "Not authenticated"}, 401)

        # ② Public API prefixes → allow (setup endpoint moved to conditional above)
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # ②b Thumbnail images are public via GET (image serving only)
        if path.startswith("/api/thumbnails/") and request.method == "GET" and "/image" in path:
            return await call_next(request)

        # ③ Public SPA routes + static assets → allow (data is protected via API)
        if path in PUBLIC_EXACT or path.rstrip("/") in PUBLIC_EXACT or path.startswith("/assets/"):
            return await call_next(request)

        # ④ Protected APIs → require auth
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return JSONResponse({"detail": "Not authenticated"}, 401)

        token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()
        if not token:
            return JSONResponse({"detail": "Not authenticated"}, 401)

        payload = await verify_jwt(token)
        if not payload:
            return JSONResponse({"detail": "Invalid or expired token"}, 401)

        sub = payload.get("sub")
        if not sub:
            return JSONResponse({"detail": "Invalid token payload"}, 401)
        request.state.user_id = int(sub)
        return await call_next(request)
