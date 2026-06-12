from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config.settings import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ──────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """bcrypt-hash a plaintext password. Store the result, never the plain."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison — safe against timing attacks."""
    return _pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str) -> str:
    """
    Create a signed JWT.
    Payload: sub=user_id, email, iat, exp.
    exp = now + ACCESS_TOKEN_EXPIRE_MINUTES from settings.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify JWT signature + expiry.
    Raises JWTError on invalid/expired token — caller converts to 401.
    Returns full payload dict.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
