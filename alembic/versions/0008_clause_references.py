"""0008 clause_references(条款指代/引用 standoff 解析表,§6.7)

Revision ID: 0008_clause_references
Revises: 0007_dict_entity_dept
Create Date: 2026-06-22

add-only:新建 ``clause_references`` 表(ref_resolver 解析产物的落点)。
**本次仅建表结构,填充逻辑 ref_resolver 未实现**(§6.7,先不做)。原 ``chunks.internal_refs[]``
按 §6.7「保留不删、停止新写」。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_clause_references"
down_revision: str | None = "0007_dict_entity_dept"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clause_references",
        sa.Column("ref_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chunk_id", sa.String(length=24), nullable=False),
        sa.Column("doc_version_id", sa.String(length=26), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("surface_text", sa.String(length=256), nullable=False),
        sa.Column("ref_type", sa.String(length=8), nullable=False),
        sa.Column("target_doc_version_id", sa.String(length=26), nullable=True),
        sa.Column("target_clause_path_norm", sa.String(length=512), nullable=True),
        sa.Column("resolution_status", sa.String(length=16), nullable=False),
        sa.Column("method", sa.String(length=16), server_default="rule", nullable=False),
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
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.chunk_id"]),
        sa.ForeignKeyConstraint(["doc_version_id"], ["doc_versions.doc_version_id"]),
        sa.PrimaryKeyConstraint("ref_id"),
    )
    op.create_index(
        op.f("ix_clause_references_chunk_id"), "clause_references", ["chunk_id"], unique=False
    )
    op.create_index(
        op.f("ix_clause_references_doc_version_id"),
        "clause_references",
        ["doc_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clause_references_target_doc_version_id"),
        "clause_references",
        ["target_doc_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clause_references_resolution_status"),
        "clause_references",
        ["resolution_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_clause_references_resolution_status"), table_name="clause_references")
    op.drop_index(
        op.f("ix_clause_references_target_doc_version_id"), table_name="clause_references"
    )
    op.drop_index(op.f("ix_clause_references_doc_version_id"), table_name="clause_references")
    op.drop_index(op.f("ix_clause_references_chunk_id"), table_name="clause_references")
    op.drop_table("clause_references")
