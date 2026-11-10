"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from strawberry.fastapi import GraphQLRouter

from patronlab import __version__
from patronlab.api.context import get_context
from patronlab.api.ratelimit import RateLimiter
from patronlab.api.schema import schema
from patronlab.config import Settings, get_settings
from patronlab.db.session import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
        await engine.dispose()

    app = FastAPI(
        title="PatronLab API", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.settings = settings
    app.state.ai_limiter = RateLimiter()
    app.state.ai_slots = asyncio.Semaphore(settings.ai_concurrency)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.include_router(
        GraphQLRouter(
            schema,
            context_getter=get_context,
            graphql_ide="graphiql" if settings.graphiql else None,
        ),
        prefix="/graphql",
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict[str, object]:
        try:
            async with app.state.session_factory() as session:
                await session.execute(text("select 1"))
            database_ok = True
        except Exception:  # noqa: BLE001 - reported as a flag, never as details
            database_ok = False
        return {"version": __version__, "databaseOk": database_ok}

    return app
