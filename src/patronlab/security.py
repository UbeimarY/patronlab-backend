"""Password hashing (Argon2id) and access tokens (JWT)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

ISSUER = "patronlab"
AUDIENCE = "patronlab-app"

_hasher = PasswordHash.recommended()
# Verifying against a dummy hash keeps "unknown email" as slow as "wrong password".
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time")


async def hash_password(password: str) -> str:
    # Argon2 is deliberately slow: run it off the event loop.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> bool:
    return await asyncio.to_thread(_hasher.verify, password, password_hash or _DUMMY_HASH)


def issue_token(
    secret: str, user_id: uuid.UUID, role: str, lifetime: timedelta
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + lifetime
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, secret, algorithm="HS256"), expires_at


def read_token(secret: str, token: str) -> dict[str, Any]:
    """Raises jwt.InvalidTokenError when the token is forged, expired or malformed."""
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "sub", "role"]},
    )
