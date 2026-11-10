"""add mode and layer count to versions

Revision ID: 7c3f9a1d2e64
Revises: 4b21e248239c
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c3f9a1d2e64"
down_revision: str | Sequence[str] | None = "4b21e248239c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the summary columns and fills them from the documents already saved."""
    op.add_column(
        "pattern_versions",
        sa.Column("mode", sa.String(length=10), server_default="pattern", nullable=False),
    )
    op.add_column(
        "pattern_versions",
        sa.Column("layer_count", sa.Integer(), server_default="0", nullable=False),
    )
    # v1 documents have neither key: they stay "pattern" with 0 layers.
    op.execute(
        """
        UPDATE pattern_versions
        SET mode = COALESCE(document->>'mode', 'pattern'),
            layer_count = CASE
                WHEN jsonb_typeof(document->'layers') = 'array'
                THEN jsonb_array_length(document->'layers')
                ELSE 0
            END
        """
    )


def downgrade() -> None:
    """Drops the summary columns."""
    op.drop_column("pattern_versions", "layer_count")
    op.drop_column("pattern_versions", "mode")
