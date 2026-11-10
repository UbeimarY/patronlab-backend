import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from patronlab import cli
from patronlab.config import Settings
from patronlab.db.models import Pattern, PatternVersion, User

pytestmark = pytest.mark.anyio


async def _patterns(settings: Settings) -> list[tuple[str, str, int]]:
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            rows = await session.execute(
                select(Pattern.name, PatternVersion.mode, PatternVersion.layer_count)
                .join(PatternVersion, PatternVersion.pattern_id == Pattern.id)
                .order_by(Pattern.name)
            )
            assert await session.scalar(select(func.count()).select_from(User)) == 1
            return [tuple(row) for row in rows]
    finally:
        await engine.dispose()


async def test_seed_demo_creates_both_patterns_once(settings: Settings, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    await cli.seed_demo(lambda: "demo-password")
    expected = [("Cojín de hojas", "pattern", 0), ("Plato colibrí (barniz)", "barniz", 4)]
    assert await _patterns(settings) == expected

    # Running it again keeps the account and adds nothing; no password is asked.
    def no_password() -> str:
        raise AssertionError("the existing account must not be touched")

    await cli.seed_demo(no_password)
    assert await _patterns(settings) == expected


async def test_seed_demo_adds_only_the_missing_barniz_pattern(
    settings: Settings, monkeypatch
) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    # An account seeded by the previous version: only the cushion.
    monkeypatch.setattr(cli, "STARTERS", cli.STARTERS[:1])
    await cli.seed_demo(lambda: "demo-password")
    monkeypatch.undo()
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    await cli.seed_demo(lambda: "unused")
    names = [name for name, _, _ in await _patterns(settings)]
    assert names == ["Cojín de hojas", "Plato colibrí (barniz)"]
