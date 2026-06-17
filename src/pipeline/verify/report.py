"""``demo report <batch>`` 指标计算(V0.1 §report)。

四项核心指标 + retrieval_mode,**不含** ``t2_pass_rate`` / ``t4_pass_rate`` 键(SPEC 决策 1:M1 不留
半成品字段,M2 接入 T2/T4 再加)。指标由 pipeline_events(状态历史)+ chunks(锚点)算出:
- 解析成功率 = 到 QC_PENDING 的件 / 进入 PARSING 的件(事件判定,排除 S0 未入解析的隔离件)
- QC 一次通过率 = 直达 STRUCTURING 且历史无 QC_FAILED 的件 / 到 QC_PENDING 的件
- 各状态计数 = pipeline_status 分布
- 锚点填充率 = page_start 非空 chunk / 总 chunk
- retrieval_mode = Milvus 探测(hybrid / dense_only,见 SPEC 决策 2 不静默兜底)
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select

from common.pg_models import (
    Chunk,
    ClauseTag,
    Document,
    DocVersion,
    PipelineEvent,
    ReviewQueue,
)
from pipeline.stage_base import StageContext


def _rate(num: int, denom: int) -> float | None:
    """比率(4 位);分母为 0(无样本)→ None,避免 0% 误读。"""
    return round(num / denom, 4) if denom else None


def _core_rates(dvids: list[str], seen: dict[str, set[str]], chunks: list) -> dict:
    """核心三率(解析成功 / QC 一次通过 / 锚点填充),按给定 doc/chunk 子集算(供整批 + 按语料复用)。"""
    reached_parsing = sum(1 for d in dvids if "PARSING" in seen[d])
    reached_qc = sum(1 for d in dvids if "QC_PENDING" in seen[d])
    qc_first_pass = sum(
        1 for d in dvids if "STRUCTURING" in seen[d] and "QC_FAILED" not in seen[d]
    )
    anchored = sum(1 for c in chunks if c.page_start is not None)
    return {
        "parse_success_rate": _rate(reached_qc, reached_parsing),
        "qc_first_pass_rate": _rate(qc_first_pass, reached_qc),
        "anchor_fill_rate": _rate(anchored, len(chunks)),
    }


def build_report(ctx: StageContext, batch_id: str) -> dict:
    """汇总单批指标快照(**纯 PG 聚合,绝不加载模型**)。

    核心四率 + T2/T4(聚合 finalize 留痕)+ retrieval_mode(Milvus 探测),加 M3 四项:义务覆盖、
    队列处置、版本链、按语料(P-INT/P-EXT)拆。retrieval_mode 无 milvus/探测失败 → None。
    """
    db = ctx.db
    with db.session() as s:
        docs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id == batch_id)))
        dvids = [d.doc_version_id for d in docs]
        lids = [d.logical_id for d in docs]
        events = list(
            s.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.doc_version_id.in_(dvids or [""]))
                .order_by(PipelineEvent.id)  # 末写覆盖:取每 doc 最新 verify 留痕
            )
        )
        chunks = list(s.scalars(select(Chunk).where(Chunk.doc_version_id.in_(dvids or [""]))))
        corpus_by_lid = {
            d.logical_id: d.corpus_type
            for d in s.scalars(select(Document).where(Document.logical_id.in_(lids or [""])))
        }
        queues = list(
            s.scalars(select(ReviewQueue).where(ReviewQueue.doc_version_id.in_(dvids or [""])))
        )
        oblig_count = (
            s.scalar(
                select(func.count())
                .select_from(ClauseTag)
                .where(
                    ClauseTag.tag_type == "is_obligation",
                    ClauseTag.chunk_id.in_(
                        select(Chunk.chunk_id).where(Chunk.doc_version_id.in_(dvids or [""]))
                    ),
                )
            )
            or 0
        )

    corpus_of = {d.doc_version_id: (corpus_by_lid.get(d.logical_id) or "") for d in docs}
    seen: dict[str, set[str]] = defaultdict(set)  # doc → 到达过的 to_state 集合
    for e in events:
        seen[e.doc_version_id].add(e.to_state)

    core = _core_rates(dvids, seen, chunks)
    by_corpus = {  # 按语料(P-INT/P-EXT)拆核心三率
        corpus: _core_rates(
            [d for d in dvids if corpus_of.get(d) == corpus],
            seen,
            [c for c in chunks if corpus_of.get(c.doc_version_id) == corpus],
        )
        for corpus in sorted({c for c in corpus_of.values() if c})
    }

    nonparent = sum(1 for c in chunks if not c.is_parent)  # 义务覆盖分母 = 入投影块口径
    obligation = None  # e1 关 → N/A(不臆造覆盖率)
    if ctx.config.toggles.e1_enabled:
        obligation = {"obligation_chunks": oblig_count, "coverage": _rate(oblig_count, nonparent)}

    queue_disposition: dict[str, Counter] = {}
    for q in queues:
        queue_disposition.setdefault(q.queue_type, Counter())[q.status] += 1

    retrieval_mode = None
    if ctx.milvus is not None:
        try:
            retrieval_mode = ctx.milvus.probe_retrieval_mode()
        except Exception:  # 探测失败不应使 report 崩(指标仍可用)
            retrieval_mode = None

    # T2/T4 通过率(M2):finalize 留痕 detail["verify"],report 只聚合读取,不加载模型。
    t2_rate, t4_rate = _verify_rates(events)
    queue_disp = {k: dict(sorted(v.items())) for k, v in sorted(queue_disposition.items())}

    return {
        "batch_id": batch_id,
        "doc_count": len(docs),
        "chunk_count": len(chunks),
        "status_counts": dict(sorted(Counter(d.pipeline_status for d in docs).items())),
        "parse_success_rate": core["parse_success_rate"],
        "qc_first_pass_rate": core["qc_first_pass_rate"],
        "anchor_fill_rate": core["anchor_fill_rate"],
        "t2_pass_rate": t2_rate,
        "t4_pass_rate": t4_rate,
        "retrieval_mode": retrieval_mode,
        "obligation": obligation,  # M3:义务覆盖(e1 关→None)
        "queue_disposition": queue_disp,
        "version_chain": dict(sorted(Counter(d.version_status for d in docs).items())),
        "by_corpus": by_corpus,
    }


def _verify_rates(events: list) -> tuple[float | None, float | None]:
    """从 pipeline_events 的 verify 留痕聚合 T2/T4 通过率(events 已按 id 升序,末写覆盖)。"""
    latest: dict[str, dict] = {}
    for e in events:
        v = (e.detail or {}).get("verify")
        if v:
            latest[e.doc_version_id] = v
    t2 = [v["t2_hit"] for v in latest.values() if v.get("t2_hit") is not None]
    t4 = [v["t4_pass"] for v in latest.values() if v.get("t4_pass") is not None]
    t2_rate = (sum(1 for x in t2 if x) / len(t2)) if t2 else None
    t4_rate = (sum(1 for x in t4 if x) / len(t4)) if t4 else None
    return (round(t2_rate, 4) if t2_rate is not None else None,
            round(t4_rate, 4) if t4_rate is not None else None)
