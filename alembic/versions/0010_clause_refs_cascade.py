"""0010 clause_references FK → ON DELETE CASCADE(ref_resolver 填充配套,T1.3)

ref_resolver(§6.7,T1.3)开始填充 clause_references(FK → chunks / doc_versions)后,任何删 chunk
的路径(测试 teardown、批次回滚、reprocess replace_chunks)都会撞 FK。standoff 附属随 chunk/版本
删除自动清最干净 → 两个 FK 改 ON DELETE CASCADE。clause_tags(富集打标)既有手动删模式不动。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_clause_refs_cascade"
down_revision: str | None = "0009_p0_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FKS = (
    ("clause_references_chunk_id_fkey", "chunks", ["chunk_id"], ["chunk_id"]),
    (
        "clause_references_doc_version_id_fkey",
        "doc_versions",
        ["doc_version_id"],
        ["doc_version_id"],
    ),
)


def upgrade() -> None:
    for name, ref_table, local, remote in _FKS:
        op.drop_constraint(name, "clause_references", type_="foreignkey")
        op.create_foreign_key(
            name, "clause_references", ref_table, local, remote, ondelete="CASCADE"
        )


def downgrade() -> None:
    for name, ref_table, local, remote in _FKS:
        op.drop_constraint(name, "clause_references", type_="foreignkey")
        op.create_foreign_key(name, "clause_references", ref_table, local, remote)
