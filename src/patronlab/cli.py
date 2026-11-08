"""Maintenance commands.

  uv run python -m patronlab.cli seed-demo
Creates the demo artisan with a starter pattern, for the class presentation.
The password is read from PATRONLAB_DEMO_PASSWORD or asked interactively.
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from patronlab.config import get_settings
from patronlab.db.models import Pattern, PatternVersion, User
from patronlab.db.session import create_engine
from patronlab.samples import leaf_cushion
from patronlab.security import hash_password

DEMO_EMAIL = "artesana@demo.co"


async def seed_demo(password: str) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            if await session.scalar(select(User).where(User.email == DEMO_EMAIL)):
                print(f"{DEMO_EMAIL} already exists", file=sys.stderr)
                return
            user = User(
                email=DEMO_EMAIL,
                full_name="Rosa Ortiz",
                craft="Bordado y fieltro",
                password_hash=await hash_password(password),
            )
            session.add(user)
            await session.flush()
            pattern = Pattern(owner_id=user.id, name="Cojín de hojas", material="felt")
            session.add(pattern)
            await session.flush()
            document = leaf_cushion()
            session.add(
                PatternVersion(
                    pattern_id=pattern.id,
                    number=1,
                    document=document,
                    note="Versión inicial",
                    shape_count=len(document["shapes"]),
                )
            )
            await session.commit()
            print(f"Created {DEMO_EMAIL} with a starter pattern")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="patronlab.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed-demo", help="Create the demo artisan and a starter pattern")
    parser.parse_args()
    password = os.environ.get("PATRONLAB_DEMO_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        parser.error("The password must have at least 8 characters")
    asyncio.run(seed_demo(password))


if __name__ == "__main__":
    main()
