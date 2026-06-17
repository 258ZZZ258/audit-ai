"""S2 质检测试:gate/indicators 纯函数 + s2 stage 集成(连 PG)。"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.ir import Block, BlockType, IRDocument, SourceFormat
from common.pg_models import Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.config import QcThresholds, load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.qc.gate import evaluate
from pipeline.qc.indicators import _ge, _le
from pipeline.stage_base import StageContext
from pipeline.stages import s2_qc as s2
from pipeline.states import PipelineState as PS


def _ir(lines, dvid="DVQC", page_count=1) -> IRDocument:
    blocks = [
        Block(index=i, type=BlockType.PARAGRAPH, text=t, page=p) for i, (t, p) in enumerate(lines)
    ]
    return IRDocument(
        doc_version_id=dvid, source_format=SourceFormat.DOCX, blocks=blocks, page_count=page_count
    )


def _normal():
    return [
        ("第一章 总则", 1),
        ("第一条 为规范本单位管理工作根据有关规定制定本办法内容充实", 1),
        ("第二条 本办法适用于各部门及全体人员的日常管理活动", 1),
        ("第三条 本办法自发布之日起施行由办公室负责解释说明", 1),
    ]


def _gap():
    return [
        ("第一章 总则", 1),
        ("第七条 甲类事项的处理要求", 1),
        ("第九条 乙类事项的处理要求", 1),  # 缺第八条
        ("第十条 丙类事项的处理要求", 1),
    ]


def _null():
    return [("第一条 甲类内容充实完整", 1), ("第二条 乙类内容但缺页码", None)]


# ── 纯函数:gate / indicators ────────────────────────────────────────────────
def test_normal_passes():
    r = evaluate(_ir(_normal()), load_config().qc)
    assert not r.failed and not r.marginal


def test_clause_gap_fails_on_indicator_2():
    r = evaluate(_ir(_gap()), load_config().qc)
    assert r.failed
    assert 2 in {i.index for i in r.failures()}
    ind2 = next(i for i in r.indicators if i.index == 2)
    assert 8 in ind2.evidence["missing"]


def test_page_null_fails_on_indicator_4():
    r = evaluate(_ir(_null()), load_config().qc)
    assert r.failed and 4 in {i.index for i in r.failures()}


def _inserted():
    return [
        ("第一章 总则", 1),
        ("第三条 甲类事项的处理要求内容充实完整规范", 1),
        ("第四条 乙类事项的处理要求内容充实完整规范", 1),
        ("第四条之一 新增插入条的处理要求内容充实完整规范", 1),  # 合法插入条 → 归一 "4-1"
        ("第五条 丙类事项的处理要求内容充实完整规范", 1),
    ]


def test_inserted_clause_not_flagged_by_hierarchy():
    # 发现1 回归:第四条之一((4,1))不应被层级合法性误判为非递增(其 base 与第四条相等)
    r = evaluate(_ir(_inserted()), load_config().qc)
    ind3 = next(i for i in r.indicators if i.index == 3)
    assert ind3.evidence["violations"] == [] and ind3.passed
    assert not r.failed  # 含插入条的件整体通过 QC


def test_hierarchy_catches_duplicate_clause():
    # 确保修复未关掉检查:真重复条号(两个第四条 → (4,0)<=(4,0))仍被层级合法性抓住
    dup = [
        ("第一章 总则", 1),
        ("第三条 甲类内容充实完整规范明确", 1),
        ("第四条 乙类内容充实完整规范明确", 1),
        ("第四条 丙类内容重复条号充实完整规范", 1),  # 重复第四条
        ("第五条 丁类内容充实完整规范明确", 1),
    ]
    r = evaluate(_ir(dup), load_config().qc)
    assert 3 in {i.index for i in r.failures()}


def test_toc_chapter_lines_do_not_fail_hierarchy_legality():
    # 目录区(显式「目录」锚 + 末尾页码项)由 build_tree 区域预扫剥离,不与正文章节重复
    # 成节点 → 不触发层级合法性误判。
    lines = [
        ("目录", 1),
        ("第一章总则 1", 1),
        ("第二章附则 3", 1),
        ("第一章总则", 2),
        ("第一条 为规范本单位管理工作根据有关规定制定本办法内容充实", 2),
        ("第二条 本办法适用于各部门及全体人员的日常管理活动", 2),
        ("第二章附则", 3),
        ("第三条 本办法自发布之日起施行由办公室负责解释说明", 3),
    ]
    r = evaluate(_ir(lines), load_config().qc)
    ind3 = next(i for i in r.indicators if i.index == 3)
    assert ind3.evidence["violations"] == []
    assert ind3.passed


def test_marginal_band_with_tight_threshold():
    th = QcThresholds(
        clause_coverage_min=0.99, clause_continuity_max_gap=0, hierarchy_illegal_max=0,
        page_anchor_complete_min=1.0, table_empty_max=0.05, text_garbled_max=0.01,
        extraction_sufficiency_min=0.7, edge_band_epsilon=0.02,
    )
    r = evaluate(_ir(_normal()), th)
    assert not r.failed and r.marginal  # coverage 1.0 ∈ [0.99, 1.01]


def test_ge_le_helpers():
    assert _ge(0.96, 0.95, 0.02) == (True, True)  # 勉强通过 → marginal
    assert _ge(1.0, 0.95, 0.02) == (True, False)  # 远超 → 非 marginal
    assert _ge(0.90, 0.95, 0.02)[0] is False  # 未过
    assert _le(0.04, 0.05, 0.02) == (True, True)
    assert _le(0.0, 0.05, 0.02) == (True, False)


# ── s2 stage 集成 ────────────────────────────────────────────────────────────
@pytest.fixture
def pg():
    io_ = PgIO.from_config(load_config())
    try:
        with io_.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
    return io_


@pytest.fixture
def s2env(pg, tmp_path):
    ctx = StageContext(config=load_config(), object_store=ObjectStore(tmp_path / "obj"), db=pg)
    batches: list[str] = []
    yield ctx, batches
    with pg.session() as s:
        dvs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id.in_(batches or [""]))))
        dvids = [d.doc_version_id for d in dvs]
        lids = {d.logical_id for d in dvs}
        if dvids:
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(dvids)))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if batches:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(batches)))


def _setup(ctx, lines, batches) -> str:
    bid, lid, dvid = "t_" + str(ULID()), str(ULID()), str(ULID())
    batches.append(bid)
    ctx.db.add(ImportBatch(batch_id=bid, source_dir="x"))
    ctx.db.add(Document(logical_id=lid, corpus_type="P-INT"))
    ctx.db.add(
        DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:10], raw_object_key="k", pipeline_status="QC_PENDING",
        )
    )
    ctx.object_store.put_ir(_ir(lines, dvid))
    return dvid


def test_s2_normal_to_structuring(s2env):
    ctx, batches = s2env
    res = s2.run(ctx, _setup(ctx, _normal(), batches))
    assert res.next_state is PS.STRUCTURING


def test_s2_gap_to_qc_failed_with_evidence(s2env):
    ctx, batches = s2env
    res = s2.run(ctx, _setup(ctx, _gap(), batches))
    assert res.next_state is PS.QC_FAILED
    assert res.error_code == "E301"
    assert res.queue is not None and res.queue.queue_type == "qc_fix"
    assert any(f["index"] == 2 for f in res.evidence["failed"])


def test_s2_marginal_persisted(s2env):
    ctx, batches = s2env
    tight = ctx.config.qc.model_copy(update={"clause_coverage_min": 0.99})
    ctx2 = StageContext(
        config=ctx.config.model_copy(update={"qc": tight}),
        object_store=ctx.object_store, db=ctx.db,
    )
    dvid = _setup(ctx2, _normal(), batches)
    res = s2.run(ctx2, dvid)
    assert res.next_state is PS.STRUCTURING
    assert ctx2.db.get(DocVersion, dvid).qc_marginal is True
