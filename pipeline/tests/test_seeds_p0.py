"""T0.1 Foundation:违规/别名字典表 + doc_versions 业务域多值列 + seed 加载。

纯用例断言模型/列存在(add-only);集成用例连真 PG(不可达 skip)验 seed 两张新字典。
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from common.pg_models import DictAlias, DictViolationType, DocVersion
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO

REPO = Path(__file__).resolve().parents[2]  # pipeline/tests/ → <repo>(seeds/ 在 repo 根)


@pytest.fixture
def pg():
    io = PgIO.from_config(load_config())
    try:
        with io.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
    return io


# ── 纯:模型/列存在(add-only;D4 业务域多值 + 来源标志)──────────────────
def test_models_and_columns_exist():
    assert DictViolationType.__tablename__ == "dict_violation_types"
    assert DictAlias.__tablename__ == "dict_aliases"
    cols = set(DocVersion.__table__.columns.keys())
    # 原单值 biz_domain 保留;新增多值 biz_domains + 来源标志(manifest|llm|confirmed)
    assert {"biz_domain", "biz_domains", "biz_domain_source"} <= cols


def test_dict_alias_schema_pin():
    # Codex P0-DICT-ALIAS-SCHEMA:alias 自然键 PK(同 dict_* 族 + 幂等 seed 必需);
    # 拆 canonical_doc_number/canonical_title 服务 R4 三级匹配。PK 形态 add-only 后难改 → 钉死。
    assert [c.name for c in DictAlias.__table__.primary_key.columns] == ["alias"]
    assert {"canonical_doc_number", "canonical_title", "dict_version"} <= set(
        DictAlias.__table__.columns.keys()
    )


# ── 集成:seed 加载两张新字典(违规类别 v0-draft + 别名)──────────────────
def test_seed_loads_violation_and_aliases(pg):
    counts = pg.seed_dicts(REPO / "seeds")
    assert counts["violation_types"] >= 1
    assert counts["aliases"] >= 1
    assert any(v.dict_version == "v0-draft-2026-06" for v in pg.get_violation_types())
    assert len(pg.get_aliases()) >= 1
