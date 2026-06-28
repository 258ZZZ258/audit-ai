"""N0 多轮上下文归并(§3.4):把多轮指代/省略问句归并为**自足问句**送下游检索。

LLM 为主(已决①):gateway 配置时由真 LLM 改写(graph 注入归并客户端);stub/无 key → **规则版
确定性归并**(离线、可测);LLM 失败/返空 → **fail-safe 回落规则版/原句**(绝不阻断)。**只改写
问句,不作答、不生成 clause_id/发文字号**(§7.1 红线:N0 不产出引用,即便 LLM 编出错误法言也由
引用 ID 注入兜住)。R7 澄清闭环靠**跨请求**重入本节点(§6.7/§0.3 不进 agentic 循环)。
"""

from __future__ import annotations

from query.llm import LLMClient
from query.understand.router import _MIN_LEN

# 指代/省略标记(§3.4「它/该制度/上面那条」):**子串**命中即顺承(继承上轮主题)。
# 与 router._PRONOUN_ONLY(**整句相等**的歧义判据 → 触发 R7 澄清)是相关但不同的概念——
# 此处问「是否含需上下文补全的指代」,故用子串 + 更全的指代词;长度阈值 _MIN_LEN 复用 router。
_COREF = ("它", "该", "这个", "那个", "这条", "那条", "上面那个", "上面那条")

MERGE_SYSTEM = (
    "你是审计制度查询助手的查询改写器。根据多轮对话历史,把用户当前问句改写为**自足问句**:"
    "消解指代(它/该制度/上面那条),补全省略的制度名/业务域(接上一轮主题)。"
    "**只改写问句,不要回答问题,不要编造制度名称、发文字号或条款号。**"
    "若当前问句已自足或无从补全,则原样返回。"
    '只输出 JSON:{"merged_query": "<改写后的自足问句>"}。'
)


def _is_turn(turn: object, role: str) -> bool:
    return isinstance(turn, dict) and turn.get("role") == role


def _content(turn: dict) -> str | None:
    c = turn.get("content")
    return c.strip() if isinstance(c, str) and c.strip() else None


def _last_user(history: list) -> str | None:
    """最近一条有效 user 轮的 content;坏/缺字段轮忽略(consumed-when-present)。"""
    for turn in reversed(history):
        if _is_turn(turn, "user") and (c := _content(turn)):
            return c
    return None


def _last_is_clarify(history: list) -> bool:
    """末个有效轮 = assistant 且 route_type==clarify(R7 澄清:当前 query 即澄清答)。"""
    for turn in reversed(history):
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant"):
            return turn.get("role") == "assistant" and turn.get("route_type") == "clarify"
    return False


def _rule_merge(query: str, history: list) -> str | None:
    """规则版确定性归并。无可参照 / 自足问句 → None(调用方回落原句)。"""
    last_user = _last_user(history)
    if last_user is None:
        return None
    q = query.strip()
    if _last_is_clarify(history):
        return f"{last_user} {q}"                       # R7 澄清闭环:原问 + 澄清答
    if len(q) < _MIN_LEN or any(m in q for m in _COREF):
        return f"{last_user} {q}"                       # 代词/省略顺承:继承上轮主题
    return None                                         # 自足问句 → 不归并


def build_merge_user(query: str, history: list) -> str:
    """拼对话历史 + 当前问句的 user prompt(坏/缺轮跳过)。"""
    lines = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role, c = turn.get("role"), _content(turn)
        if role in ("user", "assistant") and c:
            lines.append(f"{'用户' if role == 'user' else '助手'}:{c}")
    convo = "\n".join(lines)
    return f"对话历史:\n{convo}\n\n当前问句:{query}\n\n改写为自足问句。"


def parse_merged(resp: object) -> str | None:
    """从 LLM JSON 取 ``merged_query``;非 dict/非串/空 → None。"""
    if not isinstance(resp, dict):
        return None
    merged = resp.get("merged_query")
    return merged.strip() if isinstance(merged, str) and merged.strip() else None


def merge_context(query: str, history: list, *, llm: LLMClient | None = None) -> str:
    """多轮归并为自足问句。

    空 history → 原句(no-op,单轮 byte 等价)。``llm`` 给定(gateway 归并客户端)→ 真 LLM 改写,
    失败/返空 → fail-safe 回落规则版。``llm`` 为 None(stub/关)→ 规则版。绝不阻断、绝不臆造引用。
    """
    if not history:
        return query                                    # 单轮 no-op → byte 等价
    if llm is not None:
        try:
            merged = parse_merged(llm.chat_json(MERGE_SYSTEM, build_merge_user(query, history)))
            if merged:
                return merged                           # LLM 为主
        except Exception:  # noqa: BLE001 — fail-safe:任何 LLM/网络异常回落规则版,不阻断查询
            pass
    return _rule_merge(query, history) or query         # 规则版兜 / 无可归并 → 原句
