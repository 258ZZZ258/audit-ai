"""R5 §9.2 多模型复核接口(生成后校验步,CP-007):toggle 默认关。

落位 = **生成后校验**(非全量双跑):``judge_multimodel_review`` 开时,由第二 LLM 校验各文本块的
试探性表述是否被所引条款支持;不支持→降"待人工核实"(绝不踩"无依据结论"红线)。**默认关**时
直接 passthrough——always-on 保障由 ``framing.strip_bare_conclusion`` 形态后检承担。
模块级零 pipeline 导入(llm 经形参注入)。
"""

from __future__ import annotations

from collections.abc import Sequence

from query.contract import AnswerBlock, BlockType

_PENDING = "部分表述未获所引条款明确支持,已降级为『待人工核实』(§9.2 复核)。"


def _supported(content: str, citations: Sequence, llm) -> bool:
    """第二 LLM 校验:该表述是否被所引条款支持(faithfulness)。缺省按支持(不误降)。"""
    system = (
        "你是引用忠实性复核助手。判断给定表述是否被所引条款支持,"
        '只回 JSON {"supported": true 或 false}。'
    )
    refs = ";".join(
        f"《{getattr(c, 'doc_title', None)}》{getattr(c, 'clause_path', None)}" for c in citations
    )
    user = f"表述:{content}\n所引条款:{refs}\n该表述是否被所引条款支持?"
    return bool(llm.chat_json(system, user).get("supported", True))


def review_tentative(blocks: Sequence[AnswerBlock], citations, llm, qcfg) -> list[AnswerBlock]:
    """§9.2 复核:toggle 关→passthrough;开→逐块校验,不支持→降"待人工核实"。"""
    if not getattr(qcfg, "judge_multimodel_review", False):
        return list(blocks)
    out: list[AnswerBlock] = []
    for b in blocks:
        if b.type is BlockType.TEXT and not _supported(b.content, citations, llm):
            out.append(AnswerBlock(b.type, _PENDING, stream=b.stream))
        else:
            out.append(b)
    return out
