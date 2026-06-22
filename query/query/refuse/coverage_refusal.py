"""§8.2 覆盖感知拒答 + §6.8 兜底拒答。两者 ``route_type=refuse``,但语义不同:

- **覆盖感知拒答**:in-domain 但未检索到依据 → 附"已穷尽事项分区 + 最接近 N 条",**可解释**
  (区别于无信息量的"依据不足")。判据为"是否在相关事项分区内穷尽检索过"(§8.1),非 top1 分数阈值。
- **兜底拒答**:超出审计制度域 → 礼貌说明能力边界(§6.8)。

红线:绝不裸答、绝不编造依据;"最接近 N 条"明示为**供人工核实**而非确认依据。
"""

from __future__ import annotations

from collections.abc import Sequence

from query.contract import AnswerBlock, BlockType, Citation, QueryResult, RouteType

_COVERAGE_TMPL = (
    "在【{scope}】现行制度中未检索到对该行为的明确禁止性规定,"
    "但不等于无规定(可能涉及其他事项分类或穿插条款)。"
)
_OUT_OF_DOMAIN = (
    "该问题超出审计制度查询的能力范围。本系统仅就内/外规制度条款提供依据查询,"
    "请就具体制度、条款或业务事项提问。"
)


def refuse_coverage(
    exhausted_scope: Sequence[str], closest: Sequence[Citation], *, max_closest: int = 3
) -> QueryResult:
    """§8.2:附已穷尽事项分区 + 最接近 N 条(供人工核实)。"""
    scope = "、".join(exhausted_scope) if exhausted_scope else "相关业务"
    picked = list(closest)[:max_closest]
    text = _COVERAGE_TMPL.format(scope=scope)
    if picked:
        text += f"以下 {len(picked)} 条最接近,供人工核实。"
    return QueryResult(
        route_type=RouteType.REFUSE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, text)],
        citations=picked,
        exhausted_scope=list(exhausted_scope),
        confidence=0.0,
    )


def refuse_out_of_domain() -> QueryResult:
    """§6.8:超出审计制度域,礼貌拒答 + 能力边界说明。"""
    return QueryResult(
        route_type=RouteType.REFUSE,
        answer_blocks=[AnswerBlock(BlockType.TEXT, _OUT_OF_DOMAIN)],
        confidence=0.0,
    )
