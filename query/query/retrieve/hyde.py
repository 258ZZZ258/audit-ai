"""N1 HyDE 查询改写(§3.1):口语问句 → 1–2 句假设性法言条款 → 与原问一同送入 **dense** 检索。

HyDE(Hypothetical Document Embeddings,Gao et al., 2022/2023):口语描述与法言条款词面断层、直接
检索召回低;先让 LLM 写一段「假设性法言条款」,embed 其(与原问拼接)作 dense,缩小术语断层。
**只改 dense**——sparse 法言扩展归 §5.4 dict 桥接,HyDE 不碰 sparse(避免编造法言污染精确匹配)。
**污染兜底(§7.1)**:即便 HyDE 编出貌似合理的错误法言,最终答案仍只能引用检索上下文中带
clause_id 的内容——HyDE **不产出引用**,错误法言不污染答案。LLM 失败/返空 → None → 回落原问 dense。
"""

from __future__ import annotations

from query.llm import LLMClient

HYDE_SYSTEM = (
    "你是审计制度检索助手。针对用户的口语化问句,写出 1–2 句**假设性的法言法语条款表述**"
    "(模拟可能命中的制度条款原文风格),用于提升向量检索召回。"
    "**只写假设性条款表述,不要回答问题、不要编造发文字号或条款编号、不要加解释。**"
    '只输出 JSON:{"passage": "<1–2 句假设性法言条款>"}。'
)


def build_hyde_user(query: str) -> str:
    return f"口语问句:{query}\n\n写出假设性法言条款表述。"


def parse_passage(resp: object) -> str | None:
    """从 LLM JSON 取 ``passage``;非 dict/非串/空 → None。"""
    if not isinstance(resp, dict):
        return None
    passage = resp.get("passage")
    return passage.strip() if isinstance(passage, str) and passage.strip() else None


def hyde_dense_text(query: str, llm: LLMClient) -> str | None:
    """口语问句 → 假设性法言,与原问拼接为 dense 检索文本。LLM 抛/返空 → None(回落原问 dense)。"""
    try:
        passage = parse_passage(llm.chat_json(HYDE_SYSTEM, build_hyde_user(query)))
    except Exception:  # noqa: BLE001 — fail-safe:任何 LLM/网络异常 → None → 回落原问 dense,不阻断
        return None
    return f"{query}\n{passage}" if passage else None  # §3.1 假设性法言与原始问句一同送入 dense
