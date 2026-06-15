"""T2 批次检索冒烟(V7,V0.1 §21.2):每文档一条合成查询,断言命中且携带 status 过滤位。

合成查询 = **标题 + 首条款前 N 字**(N=config `t2_synthetic_query_head_chars`)→ 编码 →
`search(topk=hit_at)`。断言:① 该 doc 命中(**hit@N**,否则 `E801`)② search 实际携带
`status == "effective"` 过滤位(否则 `E802`,证明 staging/superseded 不可见)。
失败入报告、**不回退批次**(评测组件无阻断权,V0.1 §21.2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.index.pg_models import DocVersion
from pipeline.stage_base import StageContext

E_SMOKE_NO_HIT = "E801"
E_SMOKE_FILTER_MISSING = "E802"
_STATUS_FILTER = 'status == "effective"'


@dataclass
class SmokeResult:
    passed: bool
    pass_rate: float | None  # 通过文档数 / 总数;空 → None
    # 每条:{dvid, hit, rank, has_status_filter, error_code}
    per_doc: list[dict] = field(default_factory=list)


def _synthetic_query(ctx: StageContext, dvid: str, head_chars: int) -> str:
    """标题 + 首条款(首个非 parent chunk body)前 N 字。"""
    dv = ctx.db.get(DocVersion, dvid)
    title = (dv.title if dv else "") or ""
    head = ""
    chunks = [c for c in ctx.db.get_chunks(dvid) if not c.is_parent]
    if chunks:
        c = chunks[0]  # get_chunks 按 seq 升序
        t = c.text or ""
        body = t[len(c.breadcrumb):] if c.breadcrumb and t.startswith(c.breadcrumb) else t
        head = body.strip()[:head_chars]
    return (title + " " + head).strip()


def run_smoke(ctx: StageContext, doc_version_ids: list[str]) -> SmokeResult:
    head_chars = ctx.config.verify.t2_synthetic_query_head_chars
    topk = ctx.config.verify.t2_hit_at
    per_doc: list[dict] = []
    for dvid in doc_version_ids:
        emb = ctx.embedding.embed([_synthetic_query(ctx, dvid, head_chars)])[0]
        res = ctx.milvus.search(emb.dense, emb.sparse, topk=topk)  # 默认 status=effective 过滤
        ids = [h["doc_version_id"] for h in res.hits]
        hit = dvid in ids
        has_filter = bool(res.expr and _STATUS_FILTER in res.expr)
        ec = (
            E_SMOKE_FILTER_MISSING if not has_filter else (E_SMOKE_NO_HIT if not hit else None)
        )
        per_doc.append(
            {
                "dvid": dvid, "hit": hit,
                "rank": (ids.index(dvid) + 1 if hit else None),
                "has_status_filter": has_filter, "error_code": ec,
            }
        )
    ok = sum(1 for d in per_doc if d["error_code"] is None)
    return SmokeResult(
        passed=(ok == len(per_doc) and bool(per_doc)),
        pass_rate=(ok / len(per_doc) if per_doc else None),
        per_doc=per_doc,
    )
