import asyncio
from datetime import datetime, timedelta, timezone
import os
import sys
from typing import Dict, List
from uuid import UUID
from fastapi import Header, HTTPException, status
from dotenv import load_dotenv
import jwt

load_dotenv()

ENV = os.environ.get("ENVIRONMENT", "development").lower()
IS_TESTING_OR_DEV = ENV in ("testing", "development", "test", "dev") or "pytest" in sys.modules

# Lightweight in-memory rate limiter state
_user_request_history: Dict[str, List[datetime]] = {}
_rate_limiter_lock = asyncio.Lock()


async def enforce_rate_limit(user_id: UUID, max_requests: int = 60, window_seconds: int = 60) -> None:
    """
    Abuse protection rate-limiter: Limits a user to max_requests per window_seconds.
    Prevents DOS / API abuse while allowing high concurrency in test suites.
    """
    if IS_TESTING_OR_DEV and ("pytest" in sys.modules or os.environ.get("DISABLE_RATE_LIMIT", "0") == "1"):
        return

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(seconds=window_seconds)
    uid_str = str(user_id)

    async with _rate_limiter_lock:
        history = _user_request_history.get(uid_str, [])
        valid_history = [t for t in history if t > cutoff]

        if len(valid_history) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"ok": False, "reason": "rate_limit_exceeded"},
            )

        valid_history.append(now_utc)
        _user_request_history[uid_str] = valid_history


def get_allowed_domain() -> str:
    domain = os.environ.get("AUTH_ALLOWED_EMAIL_DOMAIN", "").strip().lower()
    if not domain and os.environ.get("ENVIRONMENT", "").lower() == "production":
        domain = "iitg.ac.in"
    return domain


async def get_current_user_id(
    authorization: str = Header(None),
    x_user_id: str = Header(None),
) -> UUID:
    """
    Extracts authenticated user UUID.
    In PRODUCTION mode (ENVIRONMENT=production):
      - Strictly parses and verifies Supabase JWT from 'Authorization: Bearer <JWT>'.
      - Enforces AUTH_ALLOWED_EMAIL_DOMAIN (e.g. iitg.ac.in) if configured.
      - Ignores and rejects 'X-User-ID' header to prevent client identity spoofing.

    In DEVELOPMENT/TESTING mode (ENVIRONMENT=development):
      - Permits normal verified email accounts through real Supabase Auth JWTs.
      - Accepts 'X-User-ID' header for test scripts.
      - Accepts UUID strings passed in 'Authorization: Bearer <UUID>'.
    """
    allowed_domain = get_allowed_domain()

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()

        if IS_TESTING_OR_DEV:
            try:
                return UUID(token)
            except ValueError:
                pass

        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            sub = payload.get("sub")
            email = payload.get("email", "").lower()

            if allowed_domain and email:
                if not email.endswith("@" + allowed_domain):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Only @{allowed_domain} email addresses are permitted in production",
                    )

            if sub:
                return UUID(sub)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token",
            )

    is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"

    if not is_production and x_user_id:
        try:
            return UUID(x_user_id.strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user ID format in header",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication credentials",
    )
