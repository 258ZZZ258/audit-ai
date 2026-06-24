"""R4 多文档列举编排(§6.4):枚举检索 → Milvus 标量预过滤 → E1 义务后过滤 → 按文档聚合列表。

**防注入(红线)**:``build_milvus_expr`` 字段名只来自白名单 ``_ALLOWED_EXPR_FIELDS``,值经
``json.dumps`` 转义(纵深);raw user 串在 ``dimensions.extract_enum_spec`` 即被词典过滤,绝不到此。
模块级**零 pipeline 导入**(Retriever/PgIO 经形参注入;degraded 过滤就地不引 hybrid),故纯函数
``build_milvus_expr`` 可零栈测试。**全程零 LLM**;条款逐字来自命中、四级锚点 PG 回查(无编造)。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from common.pg_models import ClauseTag
from query.contract import AnswerBlock, BlockType, QueryResult, RouteType
from query.generate.anchors import fetch_anchors
from query.listing.dimensions import EnumSpec, extract_enum_spec
from query.refuse.coverage_refusal import refuse_coverage

#: Milvus 标量过滤**唯一允许**的字段名(白名单;绝不接受用户串作字段名)。
_ALLOWED_EXPR_FIELDS = frozenset({"chunk_type", "biz_domain", "entity_type"})

_LIST_COLS = ["制度名称", "文号", "命中条款", "页码", "状态"]
#: 边界声明(§6.4 + §15-③):枚举有效性受 E2 外规覆盖范围所限,不向甲方承诺穷举。
_BOUNDARY_NOTE = "本列表基于已索引语料,不保证穷举外规(§15-③ E2 覆盖边界)。"
#: E1 义务后过滤降级明示(consumed-when-present:义务标签未覆盖时不丢光、改不过滤)。
_E1_DEGRADE_NOTE = "E1 义务标签未覆盖该批语料,未按义务过滤。"
#: 覆盖拒答的 exhausted_scope 兜底(必非空,可解释;与 graph.resolve_scope 一致)。
_FALLBACK_SCOPE = ["现行制度(未识别具体业务事项)"]


def _array_any(field: str, values: list[str]) -> str:
    """``array_contains_any(<白名单字段>, [<json 转义值>])``。field 为白名单常量,值经 json 转义。"""
    assert field in _ALLOWED_EXPR_FIELDS  # 字段名只能来自白名单常量(开发期不变式)
    return f"array_contains_any({field}, {json.dumps(values, ensure_ascii=False)})"


def build_milvus_expr(spec: EnumSpec) -> str | None:
    """``EnumSpec`` → Milvus 标量过滤 expr(白名单字段 + json 转义值)。全空 → None(不附加)。"""
    clauses: list[str] = []
    if spec.chunk_type_pref:
        clauses.append('chunk_type == "clause"')
    if spec.biz_domains:
        clauses.append(_array_any("biz_domain", list(spec.biz_domains)))
    if spec.entity_types:
        clauses.append(_array_any("entity_type", list(spec.entity_types)))
    return " and ".join(clauses) if clauses else None


def fetch_obligation_chunk_ids(pg, chunk_ids: list[str]) -> set[str]:
    """E1 义务后过滤源:返回含 ``is_obligation`` clause_tag 的 chunk_id 集合(presence=义务)。

    **consumed-when-present**:返回空集(该批未打 E1 标)由调用方判降级,不在此处臆断。
    """
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return set()
    with pg.session() as s:
        rows = s.scalars(
            select(ClauseTag.chunk_id).where(
                ClauseTag.chunk_id.in_(ids), ClauseTag.tag_type == "is_obligation"
            )
        )
        return set(rows)


def _aggregate_rows(cands, anchors) -> list[list]:
    """按 ``doc_version`` 聚合(同文档多条款合一行),文档最高分降序。

    每行=制度名/文号/命中条款/页码/状态。
    """
    by_doc: dict = {}
    for c in cands:
        cit = anchors.get(c.chunk_id)
        if cit is None:
            continue
        g = by_doc.setdefault(c.doc_version_id, {"best": c.score, "items": []})
        g["items"].append(cit)
        g["best"] = max(g["best"], c.score)
    rows = []
    for _dvid, g in sorted(by_doc.items(), key=lambda kv: kv[1]["best"], reverse=True):
        cits = g["items"]
        clauses = list(dict.fromkeys(c.clause_path for c in cits if c.clause_path))
        pages = [c.page_start for c in cits if c.page_start is not None]
        rows.append([
            cits[0].doc_title or "(未知制度)",
            cits[0].doc_no or "",
            "、".join(clauses) or "(全文)",
            min(pages) if pages else "",
            cits[0].status or "",
        ])
    return rows


def answer_enumerate(query, retriever, pg, *, biz_terms=(), entity_terms=()) -> QueryResult:
    """§6.4 列举:枚举检索 → 标量预过滤 → E1 义务后过滤 → 按 doc 聚合 TABLE + 四级 citations。

    空结果 → 覆盖感知拒答(可解释);非空附**不保证穷举外规**边界声明。全程零 LLM。
    """
    spec = extract_enum_spec(query, biz_terms=biz_terms, entity_terms=entity_terms)
    expr = build_milvus_expr(spec)
    # degraded 块仅全文检索、不参与条款级引用(契约)→ 就地剔除(不引 hybrid,保模块零 pipeline)
    cands = [c for c in retriever.retrieve_enumerate(query, extra_expr=expr) if not c.degraded]

    note = _BOUNDARY_NOTE
    if spec.obligation_only and cands:
        oblig = fetch_obligation_chunk_ids(pg, [c.chunk_id for c in cands])
        if oblig:
            cands = [c for c in cands if c.chunk_id in oblig]
        else:
            note = f"{_E1_DEGRADE_NOTE}{_BOUNDARY_NOTE}"  # consumed-when-present 降级,不丢光

    scope = list(dict.fromkeys(spec.biz_domains)) or list(_FALLBACK_SCOPE)
    if not cands:
        return refuse_coverage(scope, [])

    anchors = fetch_anchors(pg, [c.chunk_id for c in cands])
    rows = _aggregate_rows(cands, anchors)
    citations = [anchors[c.chunk_id] for c in cands if c.chunk_id in anchors]
    # 候选回查 PG 全缺锚点(写序不一致兜底)→ 覆盖拒答,不出无锚点的空 enumerate(红线:锚点 PG 权威)
    if not rows:
        return refuse_coverage(scope, [])
    content = {"columns": _LIST_COLS, "rows": rows, "note": note}
    return QueryResult(
        route_type=RouteType.ENUMERATE,
        answer_blocks=[
            AnswerBlock(BlockType.TABLE, json.dumps(content, ensure_ascii=False), stream=False)
        ],
        citations=citations,
        confidence=0.5,  # ⚠ 占位,不参与任何闸门
    )
