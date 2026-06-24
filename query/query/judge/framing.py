"""R5 三段式构成要件框定(§6.5②③ / §8.3)+ 不出裸结论代码后检(§6.5 / §0.1-1 红线)。

红线:``strip_bare_conclusion`` **always-on**——任何拟输出文本含 verdict / 试探性表述 → 替中性
"不作判定"。三段式**无 verdict 槽**:``answer_blocks`` 只承载 ② 构成要件框定 + ③ AI辅助/人工复核
标识,绝无"判定"字段。② 默认 **clause直呈(零-LLM)**;``judge_constituent_llm`` 开 → LLM 抽取
适用前提/对象/行为类型(经 ``strip_bare_conclusion`` 后检)。**安全文案有意避开 verdict 词**,使
"输出无裸结论"可被钝断言(query 含"违规"不回显进块)。
"""

from __future__ import annotations

from query.contract import AnswerBlock, BlockType

#: 裸结论判定词(复用 R1 ``generate.r1_evidence`` 口径)+ R5 试探性表述(§9.2)。钝兜底,宁过滤勿漏。
_VERDICT = ("违规", "违法", "合规", "合法")
_TENTATIVE = ("可能违反", "疑似违规", "涉嫌", "倾向于不合规", "构成违")
#: 替换文案 / 框定引导 / 复核标识 —— 均有意**避开 verdict 词**(不作判定的中性表述)。
_NEUTRAL = "相关依据见所引条款原文;具体认定须人工对照构成要件判断(本系统不作判定)。"
_FRAMING_LEAD = (
    "本问句涉及行为的判断依据见下列条款(详见引用),"
    "其适用边界需对照各条款的适用前提/对象/行为类型:"
)
_REVIEW_NOTICE = (
    "AI 辅助判断,建议人工复核:以上仅列依据条款与构成要件框定,"
    "不作认定结论,请人工对照各条款适用边界复核。"
)


def strip_bare_conclusion(text: str) -> str:
    """含 verdict / 试探性表述 → 替中性"不作判定"(守红线;形态外 always-on 兜底)。"""
    return _NEUTRAL if any(t in text for t in (*_VERDICT, *_TENTATIVE)) else text


def _clause_passthrough(clauses) -> str:
    """零-LLM 框定:结构化罗列命中条款适用边界(只引条款身份,不渲染条款正文,避裸结论)。"""
    lines = [_FRAMING_LEAD]
    for c in clauses:
        title = c.get("doc_title") or "(未知制度)"
        path = c.get("clause_path") or "(条款)"
        lines.append(f"- 《{title}》{path}:适用前提/对象/行为类型见该条款原文。")
    return "\n".join(lines)


def _llm_constituent(clauses, query, llm) -> str:
    """LLM 抽取构成要件(适用前提/对象/行为类型),**非判定**;输出经 strip 守红线。"""
    system = (
        "你是制度依据梳理助手。只梳理所引条款的『适用前提/适用对象/行为类型』,"
        "绝不判断是否违规或合规,绝不给出结论。"
    )
    refs = "\n".join(
        f"- 《{c.get('doc_title')}》{c.get('clause_path')}:{c.get('text', '')}" for c in clauses
    )
    user = f"问句:{query}\n条款:\n{refs}\n请只输出各条款的适用前提/对象/行为类型框定,不作认定。"
    out = llm.chat_json(system, user)
    return str(out.get("framing") or out.get("answer") or "")


def build_framing(clauses, query, llm, qcfg) -> list[AnswerBlock]:
    """三段式 ②③:构成要件框定 + AI辅助/人工复核标识。无 verdict 槽;LLM 路径经 strip 后检。"""
    if getattr(qcfg, "judge_constituent_llm", False):
        framing = strip_bare_conclusion(_llm_constituent(clauses, query, llm))
    else:
        framing = _clause_passthrough(clauses)
    return [
        AnswerBlock(BlockType.TEXT, framing, stream=False),
        AnswerBlock(BlockType.TEXT, _REVIEW_NOTICE, stream=False),
    ]
