"""0005 v1.6 fidelity columns (CP-007 + 版本生命周期 + §8.3 chunks)

Revision ID: 0005_v16_fidelity
Revises: e100748d4864
Create Date: 2026-06-18

add-only(只增不改):
- doc_versions: sub_type, effective_date
- chunks: chunk_type, parent_chunk_id(+index), internal_refs, embed_status, entity_type
- clause_tags: deontic_type, norm_duration_days, surface_duration, is_business_day,
  norm_status, entity_type
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_v16_fidelity"
down_revision: str | None = "e100748d4864"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("doc_versions", sa.Column("sub_type", sa.String(length=32), nullable=True))
    op.add_column("doc_versions", sa.Column("effective_date", sa.Date(), nullable=True))

    op.add_column("chunks", sa.Column("chunk_type", sa.String(length=16), nullable=True))
    op.add_column("chunks", sa.Column("parent_chunk_id", sa.String(length=24), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("internal_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("chunks", sa.Column("embed_status", sa.String(length=16), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("entity_type", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        op.f("ix_chunks_parent_chunk_id"), "chunks", ["parent_chunk_id"], unique=False
    )

    op.add_column("clause_tags", sa.Column("deontic_type", sa.String(length=16), nullable=True))
    op.add_column("clause_tags", sa.Column("norm_duration_days", sa.Integer(), nullable=True))
    op.add_column("clause_tags", sa.Column("surface_duration", sa.String(length=64), nullable=True))
    op.add_column("clause_tags", sa.Column("is_business_day", sa.Boolean(), nullable=True))
    op.add_column("clause_tags", sa.Column("norm_status", sa.String(length=16), nullable=True))
    op.add_column(
        "clause_tags",
        sa.Column("entity_type", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clause_tags", "entity_type")
    op.drop_column("clause_tags", "norm_status")
    op.drop_column("clause_tags", "is_business_day")
    op.drop_column("clause_tags", "surface_duration")
    op.drop_column("clause_tags", "norm_duration_days")
    op.drop_column("clause_tags", "deontic_type")

    op.drop_index(op.f("ix_chunks_parent_chunk_id"), table_name="chunks")
    op.drop_column("chunks", "entity_type")
    op.drop_column("chunks", "embed_status")
    op.drop_column("chunks", "internal_refs")
    op.drop_column("chunks", "parent_chunk_id")
    op.drop_column("chunks", "chunk_type")

    op.drop_column("doc_versions", "effective_date")
    op.drop_column("doc_versions", "sub_type")
