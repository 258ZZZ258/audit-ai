"""R5-T4(集成):R5 判定型端到端连真栈——三段式真数据 + 无裸结论 + 桥接入口(手插 cited)。

gate:PIPELINE_EMBEDDING_MODEL + PG + Milvus + soffice(``case_stack`` fixture)。未满足即 skip。
红线:三段式无 verdict 槽、四级锚点 PG 权威、**输出无违规/合规裸结论**;桥接 consumed-when-present
(默认空→hybrid-only,手插 ``cited_regulations`` 验反查外规条款,同 R3/R4 手插-复位)。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from common.pg_models import Case, Chunk, DocVersion
from query.config import load_query_config
from query.contract import RouteType
from query.judge.r5_judgment import answer_judgment, resolve_cited_clauses
from query.llm.stub import StubLLMClient
from query.retrieve.hybrid import Retriever

_VERDICT_WORDS = ("违规", "违法", "合规", "合法", "可能违反", "疑似违规", "涉嫌", "倾向于不合规")
_BEHAVIOR_Q = "合同未经法务审查签订是否违规"


@pytest.fixture(autouse=True)
def _ensure_milvus_connected(case_stack):
    """重连 Milvus(幂等):pymilvus 全局别名被 test_r2 模块级 teardown 断开,后跑须重连。"""
    case_stack.mio.connect()


def _answer(case_stack, query):
    retr = Retriever(case_stack.ctx.embedding, case_stack.mio, load_query_config())
    return answer_judgment(query, retr, case_stack.pg, StubLLMClient(), load_query_config())


def test_judgmental_three_segment_no_verdict(case_stack):
    res = _answer(case_stack, _BEHAVIOR_Q)
    assert res.route_type is RouteType.JUDGMENTAL
    assert res.review_required is True               # 人工复核框(§6.5③)
    assert len(res.answer_blocks) >= 2               # 三段式 ② 框定 + ③ 标识
    assert res.citations, "三段式 ① 依据条款须有四级锚点"
    cit = res.citations[0]
    assert cit.clause_path and cit.status == "effective"   # 四级锚点 PG 权威
    for b in res.answer_blocks:                       # 红线:绝不出违规/合规裸结论
        assert not any(w in b.content for w in _VERDICT_WORDS), b.content


def test_bridge_resolves_cited_regulations(case_stack):
    pg, internal_dvid, case_dvid = case_stack.pg, case_stack.internal_dvid, case_stack.case_dvid
    with pg.session() as s:
        dv = s.get(DocVersion, internal_dvid)
        chunk = s.scalars(
            select(Chunk).where(
                Chunk.doc_version_id == internal_dvid,
                Chunk.is_parent.is_(False),
                Chunk.clause_path_norm.isnot(None),
            )
        ).first()
        doc_no, clause, chunk_id = dv.doc_number, chunk.clause_path_norm, chunk.chunk_id
    # 默认 cited_regulations 空 → 桥接反查 [](consumed-when-present)
    assert resolve_cited_clauses(pg, [case_dvid]) == []
    # 手插 → 反查命中内规条款 chunk(仿 R3 手插-复位)
    with pg.session() as s:
        s.get(Case, case_dvid).cited_regulations = [{"doc_no": doc_no, "clause_path": clause}]
    try:
        assert chunk_id in resolve_cited_clauses(pg, [case_dvid])
        assert resolve_cited_clauses(pg, []) == []   # 无 dvid → []
    finally:
        with pg.session() as s:
            s.get(Case, case_dvid).cited_regulations = []
