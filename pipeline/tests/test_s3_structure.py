"""s3_structure 集成测试(连真 PG + tmp ObjectStore;PG 不可达 skip)。

L3 切块细节由 test_chunker 覆盖;这里验 stage 装配:IR→PG 行映射、chunk_id 不被改、
staging、表格/父块入 PG、replace_chunks 幂等重跑。
"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.ir import Block, BlockType, IRDocument, SourceFormat, Table, TableCell
from common.pg_models import Chunk, Document, DocVersion, ImportBatch, PipelineEvent
from pipeline.chunking.chunker import build_chunks
from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.stage_base import StageContext
from pipeline.stages import s3_structure as s3
from pipeline.states import PipelineState as PS


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
def env(pg, tmp_path):
    ctx = StageContext(config=load_config(), object_store=ObjectStore(tmp_path / "obj"), db=pg)
    bids: list[str] = []
    yield ctx, bids
    with pg.session() as s:
        flt = DocVersion.batch_id.in_(bids or [""])
        dvids = list(s.scalars(select(DocVersion.doc_version_id).where(flt)))
        lids = list(s.scalars(select(DocVersion.logical_id).where(flt)))
        if dvids:
            s.execute(delete(Chunk).where(Chunk.doc_version_id.in_(dvids)))
            s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id.in_(dvids)))
            s.execute(delete(DocVersion).where(DocVersion.doc_version_id.in_(dvids)))
        if lids:
            s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        if bids:
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id.in_(bids)))


def _table() -> Table:
    return Table(
        n_rows=2, n_cols=2, header_rows=1,
        cells=[
            TableCell(text="层级", row=0, col=0), TableCell(text="权限", row=0, col=1),
            TableCell(text="经理", row=1, col=0), TableCell(text="一万以下", row=1, col=1),
        ],
    )


def _make_ir(dvid: str) -> IRDocument:
    p = BlockType.PARAGRAPH
    return IRDocument(
        doc_version_id=dvid, source_format=SourceFormat.DOCX,
        blocks=[
            Block(index=0, type=p, text="第一章 总则", page=1),
            Block(index=1, type=p, text="第一节 一般规定", page=1),
            Block(index=2, type=p, text="第一条 略。", page=1),
            Block(index=3, type=p, text="第二条 报销规定如下。", page=1, page_end=2),
            Block(index=4, type=p, text="甲方应当及时提交单据并经审批流程。", page=1),
            Block(index=5, type=p, text="乙方应当在三个工作日内完成复核。", page=2),
            Block(index=6, type=p, text="第三条 审批权限表见下。", page=2),
            Block(index=7, type=BlockType.TABLE, page=2, table=_table()),
        ],
    )


def _seed(ctx, ir: IRDocument) -> str:
    """落 batch/document/doc_version(STRUCTURING)+ put_ir,返回 batch_id。"""
    bid, lid, dvid = "s3_" + str(ULID()), str(ULID()), ir.doc_version_id
    ctx.db.add(ImportBatch(batch_id=bid, source_dir="x"))
    ctx.db.add(Document(logical_id=lid, corpus_type="P-INT"))  # FK 父先落(PgIO.add 各自提交)
    ctx.db.add(
        DocVersion(
            doc_version_id=dvid, logical_id=lid, batch_id=bid, source_format="docx",
            source_hash="h" + dvid[:8], raw_object_key="k", pipeline_status=PS.STRUCTURING.value,
        )
    )
    ctx.object_store.put_ir(ir)
    return bid


def _chunks(ctx, dvid) -> list[Chunk]:
    with ctx.db.session() as s:
        return list(
            s.scalars(select(Chunk).where(Chunk.doc_version_id == dvid).order_by(Chunk.seq))
        )


def test_s3_writes_chunks_to_meta_review(env):
    ctx, bids = env
    ir = _make_ir(str(ULID()))
    bids.append(_seed(ctx, ir))
    res = s3.run(ctx, ir.doc_version_id)
    assert res.next_state is PS.META_REVIEW
    rows = _chunks(ctx, ir.doc_version_id)
    assert rows
    assert all(c.chunk_status == "staging" for c in rows)  # INDEXED 前对检索不可见
    # chunk_id 与 chunker 直算一致(stage 不改 id)
    assert {c.chunk_id for c in rows} == {sp.chunk_id for sp in build_chunks(ir, ctx.config.chunk)}
    art = next(c for c in rows if c.clause_path_norm == "1/1/1")
    assert art.breadcrumb == "第一章 > 第一节 > 第一条"
    assert art.text.startswith(art.breadcrumb)  # 规则6 面包屑前缀


def test_s3_table_and_parent_blocks(env):
    ctx, bids = env
    ir = _make_ir(str(ULID()))
    bids.append(_seed(ctx, ir))
    s3.run(ctx, ir.doc_version_id)
    rows = _chunks(ctx, ir.doc_version_id)
    assert any(c.is_parent for c in rows), "节级父块应入 PG"
    tables = [c for c in rows if c.is_table]
    assert tables, "表格块应入 PG"
    assert tables[0].text.startswith(tables[0].breadcrumb)  # 表格仅面包屑前缀(无 LLM 摘要)


def test_s3_mapping_fidelity(env):
    # 逐字段验 ChunkSpec→Chunk 映射(含跨页 page_start/page_end、token_count)
    ctx, bids = env
    ir = _make_ir(str(ULID()))
    bids.append(_seed(ctx, ir))
    s3.run(ctx, ir.doc_version_id)
    specs = {sp.chunk_id: sp for sp in build_chunks(ir, ctx.config.chunk)}
    for c in _chunks(ctx, ir.doc_version_id):
        sp = specs[c.chunk_id]
        assert (c.clause_path, c.clause_path_norm, c.seq) == (
            sp.clause_path, sp.clause_path_norm, sp.seq,
        )
        assert (c.page_start, c.page_end, c.token_count) == (
            sp.page_start, sp.page_end, sp.token_count,
        )
        assert (c.is_parent, c.is_table, c.oversize) == (sp.is_parent, sp.is_table, sp.oversize)
        assert c.text == sp.text and c.breadcrumb == sp.breadcrumb


def test_s3_persists_oversize_flag(env):
    # tiny 上限 + 单段无语义边界长文本 → 字符硬切 → oversize=True,须落库(此前被丢弃)
    ctx, bids = env
    cfg = load_config()
    cfg.chunk.target_token_max = 10
    cfg.chunk.target_token_min = 1
    small = StageContext(config=cfg, object_store=ctx.object_store, db=ctx.db)
    dvid = str(ULID())
    ir = IRDocument(
        doc_version_id=dvid, source_format=SourceFormat.DOCX,
        blocks=[Block(index=0, type=BlockType.PARAGRAPH, text="第一条 " + "甲" * 80, page=1)],
    )
    bids.append(_seed(small, ir))
    s3.run(small, dvid)
    assert any(c.oversize for c in _chunks(small, dvid))  # oversize 落库


def test_s3_idempotent_rerun(env):
    ctx, bids = env
    ir = _make_ir(str(ULID()))
    bids.append(_seed(ctx, ir))
    s3.run(ctx, ir.doc_version_id)
    first = sorted(c.chunk_id for c in _chunks(ctx, ir.doc_version_id))
    s3.run(ctx, ir.doc_version_id)  # 重跑:replace_chunks 删旧插新,确定性 id 不变
    second = sorted(c.chunk_id for c in _chunks(ctx, ir.doc_version_id))
    assert first == second and len(first) == len(set(first))
