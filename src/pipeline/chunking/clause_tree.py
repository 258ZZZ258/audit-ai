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

_NUM_CHARS = "〇零一二三四五六七八九十百千两\\d"
_NUM = rf"[{_NUM_CHARS}]+"
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


#: 目录识别(**区域级**,见 ``_toc_block_indices``)。不在 ``classify_heading`` 逐行判——目录是
#: 结构区域而非单行属性,故用三类结构信号、对 章/节/条/小数/无编号目录项一视同仁:
#: - 点引导符:行内 ≥4 连续点/省略号(如「第一章 总则 …… 5」),正文绝不出现 → 单行即定;
#: - 末尾页码:文本 + 空白 + 1–4 位页码(如「第一章 总则 1」),需成簇或有锚才确认;
#: - 显式锚:独占一行的「目录/目次/Contents」。
_TOC_LEADER = re.compile(r"[.．·…]{4,}")
_TOC_TRAILING_PAGE = re.compile(r"\S\s+\d{1,4}\s*$")
_TOC_HEADER = frozenset({"目录", "目次", "contents", "tableofcontents"})
#: 无锚、无点引导时,末尾页码行需连续 ≥此数成簇才判目录(孤立一行恰以数字结尾的真标题不误伤)。
_TOC_MIN_RUN = 3


def classify_heading(text: str) -> Heading | None:
    """识别**单行**是否为某类节点标题;否则 None(正文段)。**纯单行、不管上下文**:
    目录剥离由 ``build_tree`` 的区域级预扫(``_toc_block_indices``)负责,本函数不再自判目录。
    """
    half = to_halfwidth(text)
    s = strip_ws(half)
    if not s:
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


def _toc_block_indices(blocks: list[Block]) -> set[int]:
    """**区域级**目录识别:返回属于目录区的 block 序号(scheme A:``build_tree`` 留作 body、不当标题)。

    抓目录的**结构不变量**,而非逐行枚举哪些标题类型会出现——故对 章/节/条/小数/无编号目录项
    一视同仁(旧版逐行正则只认 章/节,会漏 条 与小数体例目录项):
    - **显式锚**:出现「目录/目次/Contents」行 → 其后**紧邻**的候选行(阈值降为 1)整体计入;
    - **点引导**:行内 ≥4 连续点 → 单行即定(正文绝不出现);
    - **末尾页码簇**:连续 ≥``_TOC_MIN_RUN`` 行「文本+空白+1–4 位页码」→ 整段计入
      (孤立一行恰以数字结尾的真标题 run=1,不被剥)。
    """
    halves = [to_halfwidth(b.text) for b in blocks]
    leader = [bool(_TOC_LEADER.search(h)) for h in halves]
    cand = [leader[i] or bool(_TOC_TRAILING_PAGE.search(h)) for i, h in enumerate(halves)]
    header = [strip_ws(h).lower() in _TOC_HEADER for h in halves]

    toc: set[int] = set()
    n = len(blocks)
    i = 0
    while i < n:
        if header[i]:  # 显式锚:消费其后紧邻候选行(阈值降为 1)
            j = i + 1
            while j < n and cand[j]:
                j += 1
            if j > i + 1:  # 锚后确有候选项,才连锚行一并计入(否则「目录」可能只是正文用词)
                toc.update(blocks[k].index for k in range(i, j))
                i = j
                continue
            i += 1
            continue
        if cand[i]:  # 候选行成簇:连续 ≥_TOC_MIN_RUN,或簇内含点引导(单行即可信)才确认
            j = i
            while j < n and cand[j]:
                j += 1
            if (j - i) >= _TOC_MIN_RUN or any(leader[k] for k in range(i, j)):
                toc.update(blocks[k].index for k in range(i, j))
            i = j
            continue
        i += 1
    return toc


def build_tree(blocks: list[Block]) -> ClauseNode:
    """按文档序建条款树。标题入栈分层,正文挂到当前最深节点;无章直条挂虚拟根。

    目录区(``_toc_block_indices`` 区域级识别)的块不当标题、留作当前节点 body(scheme A):
    避免目录章节与正文重复成节点;目录文本随根 body 不入 chunk(chunker 只切 节/条节点)。
    """
    root = ClauseNode(NodeType.ROOT, None, "", "", None)
    stack: list[ClauseNode] = [root]
    toc = _toc_block_indices(blocks)
    for b in blocks:
        h = None if b.index in toc else classify_heading(b.text)
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
