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


def _clause_evidence(clauses: Sequence) -> str:
    """所引条款 → 复核证据串:``《题名》条号:正文``,每条一行。

    **必带正文**(R5-REVIEW-NEEDS-CLAUSE-EVIDENCE):仅靠题名/条号无从核忠实性——复核模型须看到条文
    原文才能判表述是否被支持。正文缺失记 ``(正文缺失)``,由 fail-closed 兜底(无证据 → 判不支持)。
    """
    return "\n".join(
        f"《{c.get('doc_title')}》{c.get('clause_path')}:{c.get('text') or '(正文缺失)'}"
        for c in clauses
    )


def _supported(content: str, clauses: Sequence, llm) -> bool:
    """第二 LLM 校验:该表述是否被**所引条款原文**支持(faithfulness)。

    喂复核模型的是条文**原文**(非仅题名/条号)——见 ``_clause_evidence``。
    **fail closed(LLM05)**:LLM 输出不可信——仅当 ``supported`` 是**严格 bool ``True``**才判支持;
    缺失 / 非 bool(如字符串 ``"false"`` 真值为 True)/ 任何其它值 → **判不支持**(降级"待人工核实"),
    绝不让畸形响应放过踩红线的表述。
    """
    system = (
        "你是引用忠实性复核助手。判断给定表述是否被【所引条款原文】支持,"
        '只回 JSON {"supported": true 或 false}。'
    )
    user = (
        f"表述:{content}\n所引条款原文:\n{_clause_evidence(clauses)}\n"
        "该表述是否被上述条款原文支持?"
    )
    return llm.chat_json(system, user).get("supported") is True


def review_tentative(blocks: Sequence[AnswerBlock], clauses, llm, qcfg) -> list[AnswerBlock]:
    """§9.2 复核:toggle 关→passthrough;开→逐块按**所引条款原文**校验,不支持→降"待人工核实"。

    ``clauses``:所引条款证据,每条 ``{"doc_title", "clause_path", "text"}``(text=条文原文)。
    """
    if not getattr(qcfg, "judge_multimodel_review", False):
        return list(blocks)
    out: list[AnswerBlock] = []
    for b in blocks:
        if b.type is BlockType.TEXT and not _supported(b.content, clauses, llm):
            out.append(AnswerBlock(b.type, _PENDING, stream=b.stream))
        else:
            out.append(b)
    return out
