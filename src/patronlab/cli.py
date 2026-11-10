"""Maintenance commands.

  uv run python -m patronlab.cli seed-demo
Creates the demo artisan with two starter patterns (a felt cushion and a
Barniz de Pasto plate), for the class presentation. If the artisan already
exists, the account is left as it is and only missing starter patterns are
added. The password is read from PATRONLAB_DEMO_PASSWORD or asked
interactively (only needed when the account is created).
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from patronlab.config import get_settings
from patronlab.db.models import Pattern, PatternVersion, User
from patronlab.db.session import create_engine
from patronlab.document import PatternDocument
from patronlab.samples import hummingbird_plate, leaf_cushion
from patronlab.security import hash_password

DEMO_EMAIL = "artesana@demo.co"
# (name, material, document factory)
STARTERS: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
    ("Cojín de hojas", "felt", leaf_cushion),
    ("Plato colibrí (barniz)", "mopa-mopa", hummingbird_plate),
]


async def _add_pattern(
    session: AsyncSession, user: User, name: str, material: str, raw: dict[str, Any]
) -> None:
    document = PatternDocument.model_validate(raw)
    pattern = Pattern(owner_id=user.id, name=name, material=material, current_version=1)
    session.add(pattern)
    await session.flush()
    session.add(
        PatternVersion(
            pattern_id=pattern.id,
            number=1,
            document=document.dump(),
            note="Versión inicial",
            shape_count=len(document.shapes),
            mode=document.mode,
            layer_count=len(document.layers),
        )
    )


async def seed_demo(password: Callable[[], str]) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
            if user is None:
                user = User(
                    email=DEMO_EMAIL,
                    full_name="Rosa Ortiz",
                    craft="Bordado, fieltro y barniz de Pasto",
                    password_hash=await hash_password(password()),
                )
                session.add(user)
                await session.flush()
                print(f"Created {DEMO_EMAIL}")
            else:
                print(f"{DEMO_EMAIL} already exists: keeping the account", file=sys.stderr)
            existing = set(
                await session.scalars(select(Pattern.name).where(Pattern.owner_id == user.id))
            )
            for name, material, factory in STARTERS:
                if name in existing:
                    print(f"  '{name}' already there", file=sys.stderr)
                    continue
                await _add_pattern(session, user, name, material, factory())
                print(f"  added '{name}'")
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="patronlab.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "seed-demo", help="Create the demo artisan and add any missing starter pattern"
    )
    parser.parse_args()

    def password() -> str:
        value = os.environ.get("PATRONLAB_DEMO_PASSWORD") or getpass.getpass("Password: ")
        if len(value) < 8:
            parser.error("The password must have at least 8 characters")
        return value

    asyncio.run(seed_demo(password))


if __name__ == "__main__":
    main()
