"""0007 dict_entity_types + dict_departments(E2 打标约束字典,§19.2/CP-007)

Revision ID: 0007_dict_entity_dept
Revises: 0006_cases
Create Date: 2026-06-18

add-only:新建两张人工维护字典表(带 dict_version,支持 E2 增量重打)。种子见 seeds/。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_dict_entity_dept"
down_revision: str | None = "0006_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dict_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("dict_version", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("code"),
    )


def upgrade() -> None:
    _dict_table("dict_entity_types")
    _dict_table("dict_departments")


def downgrade() -> None:
    op.drop_table("dict_departments")
    op.drop_table("dict_entity_types")
