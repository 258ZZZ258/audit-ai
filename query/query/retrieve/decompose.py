"""N3 问题分解(§3.3):显式复合问句 → 拆为 2–N 个子查询 → 并行检索再综合;单跳问句直通。

仅对**显式复合问句**(含多个并列子约束,如「同时管偏股+偏债是否违规」)触发:LLM 一次性拆为独立子查询,
`retrieve()` 对每子查询 fan-out 检索、候选并集后综合(plan-execute 拆分,LangChain/LangGraph 主流)。
**关键边界(§0.3)**:**不进入** plan→retrieve→reason→re-retrieve 的 agentic 循环——分解只做**一次性**
子查询拆分,不做迭代推理。单跳问句 → `[query]` 直通(无额外延迟)。**污染兜底(§7.1)**:子查询是检索
改写、**不产引用**;即便错误拆分,最终答案仍只引检索上下文中带 clause_id 者。LLM 失败/返空/单跳 →
`[query]`(fail-safe,绝不阻断检索)。
"""

from __future__ import annotations

from query.llm import LLMClient

DECOMPOSE_SYSTEM = (
    "你是审计制度查询助手的问题分解器。判断用户问句是否为**复合问句**(含多个并列子约束,如"
    "「同时管偏股+偏债」「A 和 B 是否都需要」)。若是,拆为 2–N 个独立子查询,每个聚焦一个子约束;"
    "若是单一问句,只返回一个。**只拆分改写,不要回答问题,不要编造制度名称或条款号。**"
    '只输出 JSON:{"subqueries": ["<子查询1>", "<子查询2>", ...]}。'
)


def build_decompose_user(query: str) -> str:
    return f"问句:{query}\n\n判断是否复合问句,拆为子查询。"


def parse_subqueries(resp: object) -> list[str]:
    """从 LLM JSON 取 ``subqueries`` 列表(过滤非串/空);非 dict/非 list → []。"""
    if not isinstance(resp, dict):
        return []
    subs = resp.get("subqueries")
    if not isinstance(subs, list):
        return []
    return [s.strip() for s in subs if isinstance(s, str) and s.strip()]


def decompose_subqueries(query: str, llm: LLMClient, *, max_sub: int = 4) -> list[str]:
    """复合问句 → 子查询列表;单跳/失败/返空 → ``[query]``(直通)。``>max_sub`` 截断(封顶 fan-out)。

    **一次性**拆分(§0.3 不迭代);仅 ``len>1``(复合)才 fan-out,否则原问直通。
    """
    try:
        subs = parse_subqueries(llm.chat_json(DECOMPOSE_SYSTEM, build_decompose_user(query)))
    except Exception:  # noqa: BLE001 — fail-safe:任何 LLM/网络异常 → 单查询,不阻断检索
        return [query]
    return subs[:max_sub] if len(subs) > 1 else [query]  # 仅复合(>1)fan-out;单跳直通
