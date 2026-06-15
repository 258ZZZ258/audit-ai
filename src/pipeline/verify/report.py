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

from sqlalchemy import select

from pipeline.index.pg_models import Chunk, DocVersion, PipelineEvent
from pipeline.stage_base import StageContext


def _rate(num: int, denom: int) -> float | None:
    """比率(4 位);分母为 0(无样本)→ None,避免 0% 误读。"""
    return round(num / denom, 4) if denom else None


def build_report(ctx: StageContext, batch_id: str) -> dict:
    """汇总单批指标快照(纯读)。retrieval_mode 经 Milvus 探测;无 milvus/探测失败 → None。"""
    db = ctx.db
    with db.session() as s:
        docs = list(s.scalars(select(DocVersion).where(DocVersion.batch_id == batch_id)))
        dvids = [d.doc_version_id for d in docs]
        events = list(
            s.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.doc_version_id.in_(dvids or [""]))
                .order_by(PipelineEvent.id)  # 末写覆盖:取每 doc 最新 verify 留痕
            )
        )
        chunks = list(
            s.scalars(select(Chunk).where(Chunk.doc_version_id.in_(dvids or [""])))
        )

    seen: dict[str, set[str]] = defaultdict(set)  # doc → 到达过的 to_state 集合
    for e in events:
        seen[e.doc_version_id].add(e.to_state)
    reached_parsing = sum(1 for d in dvids if "PARSING" in seen[d])
    reached_qc = sum(1 for d in dvids if "QC_PENDING" in seen[d])
    qc_first_pass = sum(
        1 for d in dvids if "STRUCTURING" in seen[d] and "QC_FAILED" not in seen[d]
    )
    anchored = sum(1 for c in chunks if c.page_start is not None)

    retrieval_mode = None
    if ctx.milvus is not None:
        try:
            retrieval_mode = ctx.milvus.probe_retrieval_mode()
        except Exception:  # 探测失败不应使 report 崩(指标仍可用)
            retrieval_mode = None

    # T2/T4 通过率(M2):由 finalize 在 INDEXED 时算好、留痕到 pipeline_events.detail["verify"]
    # (§9);report 只**聚合读取**,不在此加载模型/重跑(避免 report 触发模型加载)。无留痕 → None。
    t2_rate, t4_rate = _verify_rates(events)

    return {
        "batch_id": batch_id,
        "doc_count": len(docs),
        "chunk_count": len(chunks),
        "status_counts": dict(sorted(Counter(d.pipeline_status for d in docs).items())),
        "parse_success_rate": _rate(reached_qc, reached_parsing),
        "qc_first_pass_rate": _rate(qc_first_pass, reached_qc),
        "anchor_fill_rate": _rate(anchored, len(chunks)),
        "t2_pass_rate": t2_rate,
        "t4_pass_rate": t4_rate,
        "retrieval_mode": retrieval_mode,
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
