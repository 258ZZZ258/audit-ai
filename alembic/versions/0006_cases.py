"""0006 cases(P-CASE 案例要素抽取表,§9)

Revision ID: 0006_cases
Revises: 0005_v16_fidelity
Create Date: 2026-06-18

add-only:新建 ``cases`` 表(一案一行,FK → doc_versions)。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_cases"
down_revision: str | None = "0005_v16_fidelity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("doc_version_id", sa.String(length=26), nullable=False),
        sa.Column("penalty_org", sa.String(length=256), nullable=True),
        sa.Column("doc_number", sa.String(length=128), nullable=True),
        sa.Column("penalty_date", sa.Date(), nullable=True),
        sa.Column("respondent", sa.String(length=256), nullable=True),
        sa.Column("respondent_type", sa.String(length=16), nullable=True),
        sa.Column("violation_category", sa.String(length=64), nullable=True),
        sa.Column("cited_regulations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("penalty_type", sa.String(length=64), nullable=True),
        sa.Column("amount_wan", sa.Float(), nullable=True),
        sa.Column(
            "ref_unresolved", sa.Boolean(), server_default="false", nullable=False
        ),
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
        sa.ForeignKeyConstraint(["doc_version_id"], ["doc_versions.doc_version_id"]),
        sa.PrimaryKeyConstraint("doc_version_id"),
    )


def downgrade() -> None:
    op.drop_table("cases")
