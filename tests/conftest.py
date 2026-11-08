from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import create_async_engine

from patronlab.app import create_app
from patronlab.config import Settings
from patronlab.db import models  # noqa: F401  (registers every table)
from patronlab.db.base import Base

TEST_JWT_SECRET = "test-secret-with-at-least-32-characters"
PASSWORD = "very-secure-password"


class _TestEnvironment(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: str


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def settings() -> AsyncIterator[Settings]:
    """Settings pointing at a test database with a fresh, empty schema."""
    settings = Settings(
        database_url=_TestEnvironment().test_database_url, jwt_secret=TEST_JWT_SECRET
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield settings


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


GraphQL = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def gql(api: httpx.AsyncClient) -> GraphQL:
    """Runs a GraphQL operation and returns the whole response body."""

    async def run(query: str, token: str | None = None, **variables: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = await api.post(
            "/graphql", json={"query": query, "variables": variables}, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    return run


REGISTER = """
mutation($input: RegisterInput!) {
  register(input: $input) { token user { id email fullName craft } }
}
"""


@pytest.fixture
def make_user(gql: GraphQL) -> Callable[[str], Awaitable[str]]:
    async def create(email: str) -> str:
        body = await gql(
            REGISTER,
            input={
                "email": email,
                "password": PASSWORD,
                "fullName": "Rosa Ortiz",
                "craft": "tejido",
            },
        )
        return str(body["data"]["register"]["token"])

    return create


def sample_document(shapes: int = 6) -> dict[str, Any]:
    kinds = ["rect", "ellipse", "triangle", "hexagon", "star", "leaf"]
    return {
        "width": 300,
        "height": 200,
        "background": "#f6efe3",
        "shapes": [
            {
                "id": f"s{i}",
                "kind": kinds[i % len(kinds)],
                "x": 40 + (i % 4) * 60,
                "y": 50 + (i // 4) * 70,
                "width": 40 + i * 3,
                "height": 35 + i * 2,
                "rotation": (i * 15) % 90,
                "fill": "#b5523b",
            }
            for i in range(shapes)
        ],
    }
