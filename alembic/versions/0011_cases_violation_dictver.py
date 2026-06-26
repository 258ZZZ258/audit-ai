"""0011 cases +violation_category_dict_version(案例 L2 违规事由分类版本快照,T2.2)

案例 L2 违规事由分类(§9)在 dict_violation_types 约束空间内选项;add-only 加列记下分类所用
dict_version 快照,支持字典升版后按版本整批重分类(同 E2 把 dict_version 写 clause_tags.evidence
的纪律,案例侧落为 cases 的 typed 列)。nullable:L1-only / case_l2 关时为空。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_cases_violation_dictver"
down_revision: str | None = "0010_clause_refs_cascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cases", sa.Column("violation_category_dict_version", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("cases", "violation_category_dict_version")
