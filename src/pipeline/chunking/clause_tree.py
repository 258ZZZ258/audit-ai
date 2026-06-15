"""条款树:七类节点(章/节/条/款/项/目 + 虚拟根)识别、建树、clause_path(_norm)、internal_refs。

- 标题识别先 ``to_halfwidth`` + ``strip_ws``,以容忍 "第 一 条" 这类逐字加空格排版。
- 无章直条(短通知)→ 条直接挂到**虚拟根**。
- 插入条(第X条之一)经 normalize 归一到 ``N-K``。
- clause_path_norm 仅取有编号的结构祖先,join 成 ``"章/节/条"``,是 chunk_id 的输入之一。
- internal_refs:廉价前置信号,捕获正文里的 第X[章节条款项](含之N),归一化。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

from pipeline.chunking.normalize import normalize_clause_no, strip_ws, to_halfwidth
from pipeline.ir import Block

_NUM = r"[〇零一二三四五六七八九十百千两\d]+"
# 条号(可含插入条西文/小数写法:21bis、21.1b);最终交 normalize_clause_no 归一与校验
_ART_NUM = rf"(?:{_NUM}(?:bis|ter|quater|quinquies)?|\d+\.\d+[a-zA-Z]?)"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
#: 紧跟「第X条」之后的枚举/引用标点 → 是跨法引用列举(如「…第一百九十六条、依照《证券法》…」)
#: 而非条标题。真条标题后必跟正文字或行尾(去空白后),不会是这些标点。
_REF_PUNCT = frozenset("、，,;；")


class NodeType(StrEnum):
    ROOT = "root"  # 虚拟根
    CHAPTER = "章"
    SECTION = "节"
    ARTICLE = "条"
    CLAUSE = "款"
    ITEM = "项"
    SUBITEM = "目"


_LEVEL = {
    NodeType.ROOT: 0,
    NodeType.CHAPTER: 1,
    NodeType.SECTION: 2,
    NodeType.ARTICLE: 3,
    NodeType.CLAUSE: 4,
    NodeType.ITEM: 5,
    NodeType.SUBITEM: 6,
}


class Heading(NamedTuple):
    type: NodeType
    number: str
    raw_label: str


class InternalRef(NamedTuple):
    level: str  # 章/节/条/款/项
    number: str  # normalized
    raw: str


#: 目录条目的点引导符(如「第一章 总则 …… 5」);≥4 连续点/省略号 → 目录行,非真标题。
_TOC_LEADER = re.compile(r"[.．·…]{4,}")


def classify_heading(text: str) -> Heading | None:
    """识别一行是否为某类节点标题;否则 None(正文段)。"""
    half = to_halfwidth(text)
    s = strip_ws(half)
    if not s:
        return None
    if _TOC_LEADER.search(half):  # 目录条目(点引导符)→ 非结构标题(避免目录章节与正文重复)
        return None
    for nt, suffix in (
        (NodeType.CHAPTER, "章"),
        (NodeType.SECTION, "节"),
        (NodeType.CLAUSE, "款"),
    ):
        m = re.match(rf"^第({_NUM}){suffix}", s)
        if m:
            return Heading(nt, normalize_clause_no(m.group(1)), m.group(0))
    # 条(插入条:中文之N / 西文 bis / 小数式 21.1b)
    m = re.match(rf"^第({_ART_NUM})条(?:之({_NUM}))?", s)
    if m and s[m.end() : m.end() + 1] not in _REF_PUNCT:  # 紧跟、，; → 跨法引用列举,非条标题
        raw = m.group(1) + ("之" + m.group(2) if m.group(2) else "")
        try:
            return Heading(NodeType.ARTICLE, normalize_clause_no(raw), m.group(0))
        except ValueError:
            pass  # 第…条 但号非法 → 落到项/目(通常不命中)
    # 小数编号条(交易所规则体例:"2.17 内容" / "3.1.2 内容",章[.节].条)。号后**强制空白**
    # (用未去空白的 half)避开 "2.17%" / "1.5亿元";号后 `(?!条)` 排除 "10.1.3 条或者…" 这种
    # 「第N.M.K条」引用碎片(第+前段在上一块,本块以「N.M.K 条…」起,非真条标题)。
    # 号取**全小数**(如 "10.1.3"):保全章/节/条序,使 _key 元组比较跨节正确排序(节点未识别也不误判)。
    m = re.match(r"^\s*(\d+(?:\.\d+){1,2})\s+(?!条)\S", half)
    if m:
        return Heading(NodeType.ARTICLE, m.group(1), m.group(1))
    # 项:(一) / （一） / 一、
    m = re.match(rf"^[（(]({_NUM})[）)]", s) or re.match(rf"^({_NUM})、", s)
    if m:
        return Heading(NodeType.ITEM, normalize_clause_no(m.group(1)), m.group(0))
    # 目:①②③…
    m = re.match(rf"^([{_CIRCLED}])", s)
    if m:
        return Heading(NodeType.SUBITEM, str(_CIRCLED.index(m.group(1)) + 1), m.group(0))
    return None


def find_internal_refs(text: str) -> list[InternalRef]:
    """捕获正文中的 第X[章节条款项](含之N),归一化。"""
    s = strip_ws(to_halfwidth(text))
    refs: list[InternalRef] = []
    # 第 + 号(含 bis/小数式)+ 级别字 + 可选「之N」(插入条:第X条之一)
    for m in re.finditer(rf"第({_ART_NUM})([章节条款项])(?:之({_NUM}))?", s):
        base, level, insert = m.group(1), m.group(2), m.group(3)
        raw = base + ("之" + insert if insert else "")
        try:
            refs.append(InternalRef(level, normalize_clause_no(raw), m.group(0)))
        except ValueError:
            continue
    return refs


@dataclass
class ClauseNode:
    type: NodeType
    number: str | None  # normalized;ROOT 为 None
    raw_label: str  # 如 "第二十一条之一";ROOT 为 ""
    title: str  # 标题行原文(去首尾空白)
    block_index: int | None  # IR block 序;ROOT 为 None
    children: list[ClauseNode] = field(default_factory=list)
    body_block_indices: list[int] = field(default_factory=list)
    parent: ClauseNode | None = field(default=None, repr=False, compare=False)

    def _chain(self) -> list[ClauseNode]:
        chain: list[ClauseNode] = []
        n: ClauseNode | None = self
        while n is not None and n.type is not NodeType.ROOT:
            chain.append(n)
            n = n.parent
        return list(reversed(chain))

    def clause_path(self) -> str:
        return " > ".join(n.raw_label for n in self._chain())

    def clause_path_norm(self) -> str:
        return "/".join(n.number for n in self._chain() if n.number is not None)

    def collect_block_indices(self) -> list[int]:
        """本节点(及全部后代)覆盖的 IR block 序,升序。供 L3 取条文全文。"""
        idxs: list[int] = []
        if self.block_index is not None:
            idxs.append(self.block_index)
        idxs.extend(self.body_block_indices)
        for c in self.children:
            idxs.extend(c.collect_block_indices())
        return sorted(idxs)


def build_tree(blocks: list[Block]) -> ClauseNode:
    """按文档序建条款树。标题入栈分层,正文挂到当前最深节点;无章直条挂虚拟根。"""
    root = ClauseNode(NodeType.ROOT, None, "", "", None)
    stack: list[ClauseNode] = [root]
    for b in blocks:
        h = classify_heading(b.text)
        if h is None:
            stack[-1].body_block_indices.append(b.index)
            continue
        node = ClauseNode(h.type, h.number, h.raw_label, b.text.strip(), b.index)
        while len(stack) > 1 and _LEVEL[stack[-1].type] >= _LEVEL[node.type]:
            stack.pop()
        parent = stack[-1]
        node.parent = parent
        parent.children.append(node)
        stack.append(node)
    return root


def iter_articles(root: ClauseNode) -> list[ClauseNode]:
    """深度优先收集全部 ARTICLE 节点(文档序)。"""
    out: list[ClauseNode] = []

    def walk(n: ClauseNode) -> None:
        if n.type is NodeType.ARTICLE:
            out.append(n)
        for c in n.children:
            walk(c)

    walk(root)
    return out
