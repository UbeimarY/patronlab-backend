"""Per-request context: database session, settings and the signed-in artisan."""

import asyncio
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.fastapi import BaseContext

from patronlab.api.errors import unauthenticated
from patronlab.api.ratelimit import RateLimiter
from patronlab.config import Settings
from patronlab.db.models import User
from patronlab.db.session import get_session
from patronlab.security import read_token


class Context(BaseContext):
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        token: str | None,
        ai_limiter: RateLimiter | None = None,
        ai_slots: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.settings = settings
        self.ai_limiter = ai_limiter or RateLimiter()
        self.ai_slots = ai_slots or asyncio.Semaphore(settings.ai_concurrency)
        self._token = token
        self._user: User | None = None

    async def user(self) -> User:
        """The signed-in artisan, or UNAUTHENTICATED. Loaded once per request."""
        if self._user is None:
            if not self._token:
                raise unauthenticated()
            try:
                claims = read_token(self.settings.jwt_secret, self._token)
                user_id = uuid.UUID(claims["sub"])
            except (jwt.InvalidTokenError, ValueError) as error:
                raise unauthenticated() from error
            user = await self.session.get(User, user_id)
            if user is None:
                raise unauthenticated()
            self._user = user
        return self._user

    async def optional_user(self) -> User | None:
        return await self.user() if self._token else None


async def get_context(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> Context:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return Context(
        session,
        request.app.state.settings,
        token if scheme.lower() == "bearer" and token else None,
        request.app.state.ai_limiter,
        request.app.state.ai_slots,
    )
