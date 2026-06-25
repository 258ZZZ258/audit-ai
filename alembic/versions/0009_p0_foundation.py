"""0009 dict_violation_types + dict_aliases + doc_versions 业务域多值列(P0 Foundation T0.1)

Revision ID: 0009_violation_aliases_bizdomains
Revises: 0008_clause_references
Create Date: 2026-06-25

add-only:
- dict_violation_types(§9 案例 L2 违规事由约束字典;v0-draft 待评审,§16-6)
- dict_aliases(§6.7 R4 跨文档指代:别名 → 权威文号/标题)
- doc_versions +biz_domains(JSONB 多值)+biz_domain_source(来源标志:manifest|llm|confirmed)
  —— D4:LLM 为业务域事实主来源,写权威字段 + 标来源;原单值 biz_domain 保留不删。
种子见 seeds/dict_violation_types.csv / seeds/dict_aliases.csv。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_p0_foundation"
down_revision: str | None = "0008_clause_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_cols() -> tuple[sa.Column, ...]:
    """每次返回**全新**审计列对象(Column 不能跨表复用;2.0 已弃 .copy())。"""
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "dict_violation_types",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("dict_version", sa.String(length=32), nullable=True),
        *_audit_cols(),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "dict_aliases",
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("canonical_doc_number", sa.String(length=128), nullable=True),
        sa.Column("canonical_title", sa.String(length=512), nullable=True),
        sa.Column("dict_version", sa.String(length=32), nullable=True),
        *_audit_cols(),
        sa.PrimaryKeyConstraint("alias"),
    )
    op.add_column(
        "doc_versions",
        sa.Column("biz_domains", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "doc_versions",
        sa.Column("biz_domain_source", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("doc_versions", "biz_domain_source")
    op.drop_column("doc_versions", "biz_domains")
    op.drop_table("dict_aliases")
    op.drop_table("dict_violation_types")
