"""Authentication utilities: password hashing and JWT token management."""

import hashlib
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------


def _password_fingerprint(hashed_password: str) -> str:
    """First 8 chars of SHA-256 of the stored bcrypt hash.

    Used to bind reset tokens to the current password — if the password
    changes (by using the token or any other means), the fingerprint
    won't match and the token is automatically invalidated.
    """
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:8]


def create_password_reset_token(user_id: int, hashed_password: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.password_reset_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "password_reset",
        "fingerprint": _password_fingerprint(hashed_password),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_password_reset_token(token: str) -> dict:
    """Decode a password reset token. Returns {"user_id": int, "fingerprint": str}.

    Raises JWTError on invalid/expired tokens or wrong type.
    """
    payload = decode_token(token)
    if payload.get("type") != "password_reset":
        raise JWTError("Invalid token type")
    return {"user_id": int(payload["sub"]), "fingerprint": payload["fingerprint"]}
