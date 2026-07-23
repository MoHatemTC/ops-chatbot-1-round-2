"""Merge notification and escalation heads.

Revision ID: aa4ac4f2b4ce
Revises: 3d8f8dd2c6d1, f11ae5c358b0
Create Date: 2026-07-19 21:04:34.895175
"""

from typing import Sequence, Union

import sqlmodel  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "aa4ac4f2b4ce"
down_revision: Union[str, Sequence[str], None] = ("3d8f8dd2c6d1", "f11ae5c358b0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
