"""A2 · T4 锚点回放测试。

- 纯核(always-run,免栈/免模型):`_matches` 精确/模糊/无关、`_window_text` 取窗、`_strip_breadcrumb`。
- 集成(**soffice + PG,免模型**):ingest 一件内规 docx 到 META_REVIEW(s1 渲染+对齐 / s3 切块,不跑 s5)→
  `run_replay` → 断言 pass_rate=1.0(chunk 来自同一 rendition,必可回放)。
"""

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import (
    Chunk,
    ClauseTag,
    Document,
    DocVersion,
    ImportBatch,
    PipelineEvent,
    ReviewQueue,
)
from pipeline.cli import _build_stages
from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.orchestrator import Orchestrator
from pipeline.stage_base import StageContext
from pipeline.stages.s0_register import register_batch
from pipeline.verify.anchor_replay import (
    _matches,
    _strip_breadcrumb,
    _window_text,
    run_replay,
)


# ── 纯核(always-run)─────────────────────────────────────────────
def test_matches_exact_fuzzy_unrelated():
    win = "第一条为加强信息披露管理根据有关规定制定本办法"
    assert _matches("根据有关规定制定本办法", win, 92)  # 精确子串
    assert _matches("第一条为加强信息披露管理根据有关规定制定本办", win, 92)  # 缺尾字 → 模糊≥92
    assert not _matches("完全无关的另一段落内容甲乙丙丁戊己庚辛", win, 92)  # 不相关
    assert _matches("", win, 92)  # 空 body 不判失败


def test_window_text_slicing():
    pages = ["P0", "P1", "P2", "P3", "P4"]  # 0-based 索引 = 1-based 页号-1
    assert _window_text(pages, 2, 2, 0) == "P1"  # 页2 单页,w=0
    assert _window_text(pages, 2, 2, 1) == "P0P1P2"  # 页2 ±1
    assert _window_text(pages, 1, 3, 0) == "P0P1P2"  # 跨页 1..3
    assert _window_text(pages, 1, 1, 5) == "P0P1P2P3P4"  # 窗超界裁到边


def test_strip_breadcrumb():
    c = Chunk(text="第一章 > 第二条\n本条正文内容", breadcrumb="第一章 > 第二条")
    assert _strip_breadcrumb(c) == "\n本条正文内容"
    c2 = Chunk(text="无前缀正文", breadcrumb=None)
    assert _strip_breadcrumb(c2) == "无前缀正文"


# ── 集成(soffice + PG,免模型)──────────────────────────────────
@pytest.fixture
def pg():
    io = PgIO.from_config(load_config())
    try:
        with io.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达")
    return io


def test_replay_on_ingested_docx(pg, soffice, tmp_path, unique_docx):
    cfg = load_config()
    ctx = StageContext(config=cfg, object_store=ObjectStore.from_config(cfg), db=pg)
    d, m = unique_docx(tmp_path)  # 自造唯一件,避开走查留存数据的 SHA 去重
    bid = str(ULID())
    register_batch(ctx, bid, d, m)
    Orchestrator(pg, ctx, _build_stages()).run_until_idle()  # → META_REVIEW(s1+s2+s3+s4,无模型)
    with pg.session() as s:
        dvids = [x.doc_version_id for x in s.scalars(
            select(DocVersion).where(DocVersion.batch_id == bid))]
    try:
        assert dvids
        r = run_replay(ctx, dvids)
        assert r.total > 0  # 有非豁免 chunk
        assert r.passed and r.pass_rate == 1.0, r.fails  # 来自同 rendition,必全回放
    finally:
        with pg.session() as s:
            for d_ in dvids:
                s.execute(delete(ReviewQueue).where(ReviewQueue.doc_version_id == d_))
                s.execute(  # E1 clause_tags 是 chunk 的 FK 子,先删才不挡 chunk 删除
                    delete(ClauseTag).where(
                        ClauseTag.chunk_id.in_(
                            select(Chunk.chunk_id).where(Chunk.doc_version_id == d_)
                        )
                    )
                )
                s.execute(delete(Chunk).where(Chunk.doc_version_id == d_))
                s.execute(delete(PipelineEvent).where(PipelineEvent.doc_version_id == d_))
            lids = [x.logical_id for x in s.scalars(
                select(DocVersion).where(DocVersion.batch_id == bid))]
            s.execute(delete(DocVersion).where(DocVersion.batch_id == bid))
            if lids:
                s.execute(delete(Document).where(Document.logical_id.in_(lids)))
            s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))
