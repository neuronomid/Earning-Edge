"""add dashboard username and password hash to users

Revision ID: 0009_dashboard_auth
Revises: 0009_news_coverage
Create Date: 2026-05-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_dashboard_auth"
down_revision = "0009_news_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("dashboard_username", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("dashboard_password_hash", sa.Text(), nullable=True))
    op.create_index(
        "ix_users_dashboard_username",
        "users",
        ["dashboard_username"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_dashboard_username", table_name="users")
    op.drop_column("users", "dashboard_password_hash")
    op.drop_column("users", "dashboard_username")
