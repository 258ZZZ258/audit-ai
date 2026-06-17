"""pg_io 集成测试(连 compose 的真 PG;PG 不可达时自动 skip)。建临时数据,测完清理。"""

from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import (
    DictIssuer,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
)
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from pipeline.states import PipelineState as PS

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


@pytest.fixture
def doc_version(pg):
    """建 batch+document+doc_version(REGISTERED),产出 dvid;结束反 FK 序清理。"""
    bid = "test_" + str(ULID())[:10]
    lid = str(ULID())
    dvid = str(ULID())
    pg.add(ImportBatch(batch_id=bid, source_dir="x"))
    pg.add(Document(logical_id=lid, corpus_type="P-INT"))
    pg.add(
        DocVersion(
            doc_version_id=dvid,
            logical_id=lid,
            batch_id=bid,
            source_format="docx",
            source_hash="h",
            raw_object_key="k",
            pipeline_status=PS.REGISTERED.value,
        )
    )
    yield dvid
    with pg.session() as s:
        s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == dvid))
        s.execute(delete(DocVersion).where(DocVersion.doc_version_id == dvid))
        s.execute(delete(Document).where(Document.logical_id == lid))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def test_seed_dicts(pg):
    n_iss, n_dom = pg.seed_dicts(REPO / "seeds")
    assert n_iss >= 1 and n_dom >= 1
    assert pg.get(DictIssuer, "CSRC").name == "中国证券监督管理委员会"


def test_transition_writes_event(pg, doc_version):
    pg.transition(doc_version, PS.PARSING, actor="system")
    assert pg.get(DocVersion, doc_version).pipeline_status == PS.PARSING.value
    with pg.session() as s:
        evs = list(
            s.scalars(select(PipelineEvent).where(PipelineEvent.doc_version_id == doc_version))
        )
    assert any(
        e.from_state == PS.REGISTERED.value and e.to_state == PS.PARSING.value for e in evs
    )


def test_illegal_transition_guarded(pg, doc_version):
    with pytest.raises(ValueError):
        pg.transition(doc_version, PS.INDEXED)  # REGISTERED -> INDEXED 非法


def test_docs_in_states(pg, doc_version):
    found = [dv.doc_version_id for dv in pg.docs_in_states([PS.REGISTERED])]
    assert doc_version in found
