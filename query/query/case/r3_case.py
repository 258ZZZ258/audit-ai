"""§6.3 R3 相似案例编排 + 附挂到 R1。**全程零 LLM**(检索 + PG 回填 + 机械组卡)。

- ``answer_case``:case 分区检索 → 按 ``doc_version_id`` **去重一案一卡** → PG 回填
  → ``CASE_CARD`` 卡片;**空命中 / 无 cases 行 → 明示**(不报错、不臆造)。
- ``attach_cases``:R1 充分 evidence 答复尾挂相关案例卡(语义检索 ∪ 精确反查),
  **追加块、零命中不挂、既有 evidence/citation 块不变**(SPEC-R3 §0/§8 SC5)。

``pg`` 形参为 ``PgIO``(``get_case`` / ``get(DocVersion, dvid)`` / ``session``)。
"""

from __future__ import annotations

from dataclasses import replace

from common.pg_models import DocVersion
from query.case.bridge import cases_for_clauses, citation_key
from query.case.case_card import build_case_card
from query.contract import AnswerBlock, BlockType, QueryResult, RouteType
from query.retrieve.hybrid import drop_degraded

_NO_CASE = "未检索到与该问句相似的处罚案例。"


def _dedup_by_case(cands) -> list:
    """按 ``doc_version_id`` 一案一卡:保留更高分,按分降序(无 dvid 的候选跳过)。"""
    best: dict[str, object] = {}
    for c in cands:
        dvid = c.doc_version_id
        if dvid is None:
            continue
        if dvid not in best or c.score > best[dvid].score:
            best[dvid] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


def _cards_for_dvids(pg, dvids) -> list[AnswerBlock]:
    """回填 ``cases`` + ``doc_versions`` → ``CASE_CARD`` 块;无 ``cases`` 行的 dvid 跳过(不臆造)。"""
    blocks: list[AnswerBlock] = []
    for dvid in dvids:
        case_row = pg.get_case(dvid)
        if case_row is None:
            continue
        blocks.append(build_case_card(case_row, pg.get(DocVersion, dvid)))
    return blocks


def answer_case(query: str, retriever, pg, qcfg) -> QueryResult:
    """R3 相似案例:case 分区检索 → 去重一案一卡 → 回填卡片 → ``route_type=case`` 契约。"""
    distinct = _dedup_by_case(drop_degraded(retriever.retrieve_cases(query)))[: qcfg.topk]
    cards = _cards_for_dvids(pg, [c.doc_version_id for c in distinct])
    if not cards:
        return QueryResult(
            route_type=RouteType.CASE,
            answer_blocks=[AnswerBlock(BlockType.TEXT, _NO_CASE)],
            confidence=0.0,
        )
    return QueryResult(
        route_type=RouteType.CASE,
        answer_blocks=cards,
        confidence=0.5,  # ⚠ Q8 待标定:占位,不参与任何闸门
    )


def attach_cases(result: QueryResult, query: str, citations, retriever, pg, qcfg) -> QueryResult:
    """R1 充分答复尾挂相关案例卡(精确反查优先 ∪ 语义检索)。零命中 → 原样返回(不挂)。"""
    # 精确反查:R1 citations 外规条款 → cited_regulations 命中案例(默认路径空 → [])
    precise = cases_for_clauses(pg, [citation_key(c) for c in citations])
    # 语义:case 分区检索去重一案一卡
    sem_cands = _dedup_by_case(drop_degraded(retriever.retrieve_cases(query)))
    semantic = [c.doc_version_id for c in sem_cands]
    ordered: list[str] = []
    for dvid in (*precise, *semantic):  # 精确优先,合并去重保序
        if dvid and dvid not in ordered:
            ordered.append(dvid)
    cards = _cards_for_dvids(pg, ordered[: qcfg.attach_topk])
    if not cards:
        return result  # 零命中不挂
    return replace(result, answer_blocks=[*result.answer_blocks, *cards])
