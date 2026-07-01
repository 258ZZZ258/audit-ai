"""0012 query sessions(制度查询会话持久化,SPEC-API §7)

Revision ID: 0012_query_sessions
Revises: 0011_cases_violation_dictver
Create Date: 2026-07-01

add-only:新建 query_conversations / query_messages 两表(功能1 会话历史)。
query 自有域,单向只读红线**不碰 corpus 权威表**;功能2 会话另建独立表。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_query_sessions"
down_revision: str | None = "0011_cases_violation_dictver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_conversations",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column(
            "agent_type",
            sa.String(length=32),
            server_default="institution_query",
            nullable=False,
        ),
        sa.Column("asker_role", sa.String(length=32), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_hit_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "query_messages",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("conversation_id", sa.String(length=26), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("route_type", sa.String(length=16), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("hit_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("ai_label", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["query_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_query_messages_conversation_id"),
        "query_messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_query_messages_conversation_id"), table_name="query_messages")
    op.drop_table("query_messages")
    op.drop_table("query_conversations")
