"""ask_logs.documents_used — how many Chat documents a question carried.

docs/adr/0005. A count only; there is deliberately still no column that could
hold document text.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ask_logs",
        sa.Column("documents_used", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ask_logs", "documents_used")
