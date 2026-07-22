"""Add escalation ticket table.

Revision ID: 3d8f8dd2c6d1
Revises: b25d38b0cd7c
Create Date: 2026-07-16 23:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3d8f8dd2c6d1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b25d38b0cd7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "escalation_ticket",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("problem", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("what_was_tried", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("context", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("suggested_next_step", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_goal", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("key_facts", sa.JSON(), nullable=False),
        sa.Column("assistant_actions", sa.JSON(), nullable=False),
        sa.Column("open_questions", sa.JSON(), nullable=False),
        sa.Column("privacy_note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_escalation_ticket_session_id"), "escalation_ticket", ["session_id"], unique=False)
    op.create_index(op.f("ix_escalation_ticket_user_id"), "escalation_ticket", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_escalation_ticket_user_id"), table_name="escalation_ticket")
    op.drop_index(op.f("ix_escalation_ticket_session_id"), table_name="escalation_ticket")
    op.drop_table("escalation_ticket")
