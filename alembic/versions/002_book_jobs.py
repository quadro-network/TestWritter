"""book_jobs

Revision ID: 002
Revises: 001
Create Date: 2026-11-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "book_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pdf_path", sa.String(length=1024), nullable=False),
        sa.Column("readable_path", sa.String(length=1024), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages_done", sa.Integer(), nullable=False),
        sa.Column("tests_generated", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("telegram_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_book_jobs_slug", "book_jobs", ["slug"])
    op.create_index("ix_book_jobs_telegram_user_id", "book_jobs", ["telegram_user_id"])


def downgrade() -> None:
    op.drop_index("ix_book_jobs_telegram_user_id", table_name="book_jobs")
    op.drop_index("ix_book_jobs_slug", table_name="book_jobs")
    op.drop_table("book_jobs")
