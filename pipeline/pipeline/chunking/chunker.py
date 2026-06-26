"""切块六规则 + 确定性 chunk_id。

六规则:
1. 原子 = 条:每个 ARTICLE 是基础切块单元。
2. 超长按款拆 + 条头续接:条文 token 超 target_max → 按款(段落)分组;**单段超长**再在
   项标记（N）/句末；。 语义边界内切(无边界长句字符硬切,标 oversize);贪心打包 ≤max
   (尾组 < target_min 并回前组,仅同条内),g>0 组前缀条头。
3. 超短独立:短条自成一块,不与邻块合并。
4. 父块 = 节级仅 PG:每个 SECTION 出一个 is_parent 块(≤parent_block_token_max),仅入 PG、不进 Milvus。
5. 表格独立块按行组拆 + 重复表头:表格块自成块;超长按行组拆,每组重复表头;is_table。
6. 面包屑前缀 + 页码跨度:每块文本前缀 clause_path;page_start/page_end 取构成块的页跨度。

chunk_id = sha1(doc_version_id|clause_path_norm|seq)[:24] —— 逐字确定性,V5 幂等根基。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from common.chunk_id import compute_chunk_id
from common.ir import Block, BlockType, IRDocument, Table
from pipeline.chunking.clause_tree import (
    ClauseNode,
    NodeType,
    build_tree,
    find_internal_refs,
    iter_articles,
)
from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.config import ChunkConfig


@dataclass
class ChunkSpec:
    chunk_id: str
    doc_version_id: str
    clause_path: str
    clause_path_norm: str
    seq: int
    text: str  # 面包屑前缀 + 正文
    breadcrumb: str
    page_start: int | None
    page_end: int | None
    token_count: int
    is_parent: bool = False
    is_table: bool = False
    oversize: bool = False  # 单段超长无语义边界,被字符硬切(质量信号)
    # chunk_type: clause | table(§8.3;与 is_parent/is_table 并存,不替代)
    chunk_type: str = "clause"
    parent_chunk_id: str | None = None  # 子块指向其节级父块 chunk_id(无节则 None)
    internal_refs: list[dict] | None = None  # 正文条款引用(前置信号);父/表块为 None
    embed_status: str = "pending"  # pending | done | failed(建块即 pending)


def count_tokens(text: str) -> int:
    """token 近似:非空白字符数(CJK≈1/字)。⚠ 启发式。"""
    return len(strip_ws(to_halfwidth(text)))


def build_chunks(doc: IRDocument, cfg: ChunkConfig) -> list[ChunkSpec]:
    """从 IR 建条款树并产出全部 chunk(节级父块 + 各条文本块/表格块)。"""
    blocks = {b.index: b for b in doc.blocks}
    root = build_tree(doc.blocks)
    out: list[ChunkSpec] = []
    for sec in _iter_by_type(root, NodeType.SECTION):
        out.append(_parent_chunk(doc.doc_version_id, sec, blocks, cfg))
    for art in iter_articles(root):
        parent_id = _section_parent_id(doc.doc_version_id, art)
        out.extend(_article_chunks(doc.doc_version_id, art, blocks, cfg, parent_id))
    return out


# ── 内部 ──────────────────────────────────────────────────────
def _section_parent_id(dvid: str, art: ClauseNode) -> str | None:
    """条所属节级父块的 chunk_id(父块用 sec.clause_path_norm()+seq 0);无节(虚拟根直条)→ None。"""
    n: ClauseNode | None = art.parent
    while n is not None:
        if n.type is NodeType.SECTION:
            return compute_chunk_id(dvid, n.clause_path_norm(), 0)
        n = n.parent
    return None


def _iter_by_type(root: ClauseNode, ntype: NodeType) -> list[ClauseNode]:
    out: list[ClauseNode] = []

    def walk(n: ClauseNode) -> None:
        if n.type is ntype:
            out.append(n)
        for c in n.children:
            walk(c)

    walk(root)
    return out


def _page_span(blocks: list[Block]) -> tuple[int | None, int | None]:
    starts = [b.page for b in blocks if b.page is not None]
    if not starts:
        return None, None
    ends = [b.page_end or b.page for b in blocks if b.page is not None]
    return min(starts), max(ends)


def _group_by_budget(
    items: list, count_fn: Callable[[object], int], budget: int
) -> list[list]:
    groups: list[list] = []
    cur: list = []
    cur_tok = 0
    for it in items:
        t = count_fn(it)
        if cur and cur_tok + t > budget:
            groups.append(cur)
            cur, cur_tok = [], 0
        cur.append(it)
        cur_tok += t
    if cur:
        groups.append(cur)
    return groups


def _coalesce_tail(groups: list[list], count_fn: Callable[[object], int], min_tokens: int) -> None:
    """尾组若 < min_tokens 则并回前组(仅同条内,允许略超 max),就地修改。

    只动尾部;中间小组(小款后接超大款)受款边界限制仍可能 < min,符合既定取舍。
    """
    while len(groups) > 1 and sum(count_fn(it) for it in groups[-1]) < min_tokens:
        groups[-2].extend(groups.pop())


_ITEM_MARK = r"(?=[（(][〇零一二三四五六七八九十百千两\d]+[）)])"  # 项标记（N）之前
_SENT_END = r"(?<=[；。;])"  # 句末；。 之后


def _split_oversize(text: str, max_tokens: int) -> list[tuple[str, bool]]:
    """超 max 单段:项标记/句末边界切子单元 → 贪心打包 ≤max;无边界长句字符硬切(标 oversize)。"""
    subunits: list[str] = []
    for part in re.split(_ITEM_MARK, text):
        subunits.extend(s for s in re.split(_SENT_END, part) if s.strip())
    if not subunits:
        subunits = [text]
    out: list[tuple[str, bool]] = []
    cur = ""
    for u in subunits:
        if count_tokens(u) > max_tokens:  # 无边界长句 → 字符硬切
            if cur:
                out.append((cur, False))
                cur = ""
            out.extend((u[i : i + max_tokens], True) for i in range(0, len(u), max_tokens))
            continue
        if cur and count_tokens(cur) + count_tokens(u) > max_tokens:
            out.append((cur, False))
            cur = ""
        cur += u
    if cur:
        out.append((cur, False))
    return out


def _decompose(
    text_pairs: list[tuple[str, Block]], max_tokens: int
) -> list[tuple[str, Block, bool]]:
    """段落级单元;单段超长者再拆为子单元(继承所属 block 用于页码)。"""
    units: list[tuple[str, Block, bool]] = []
    for text, block in text_pairs:
        if count_tokens(text) > max_tokens:
            units.extend((seg, block, hard) for seg, hard in _split_oversize(text, max_tokens))
        else:
            units.append((text, block, False))
    return units


def _mk_chunk(
    dvid: str,
    cp_norm: str,
    seq: int,
    breadcrumb: str,
    body: str,
    page_blocks: list[Block],
    *,
    is_parent: bool = False,
    is_table: bool = False,
    oversize: bool = False,
    content_tokens: int | None = None,
    parent_chunk_id: str | None = None,
) -> ChunkSpec:
    text = f"{breadcrumb}\n{body}" if breadcrumb else body
    ps, pe = _page_span(page_blocks)
    chunk_type = "table" if is_table else "clause"  # 父块亦 clause(is_parent 另记)
    # internal_refs 仅条文(clause)子块跑;父块/表块留空(前者是大块供证、后者无条款引用)
    refs = (
        [{"level": r.level, "number": r.number, "surface": r.raw} for r in find_internal_refs(body)]
        if not is_parent and not is_table
        else None
    )
    # token_count 量内容(默认 body,不含面包屑;拆分路径可显式传不含条头续接的内容数)
    return ChunkSpec(
        chunk_id=compute_chunk_id(dvid, cp_norm, seq),
        doc_version_id=dvid,
        clause_path=breadcrumb,
        clause_path_norm=cp_norm,
        seq=seq,
        text=text,
        breadcrumb=breadcrumb,
        page_start=ps,
        page_end=pe,
        token_count=content_tokens if content_tokens is not None else count_tokens(body),
        is_parent=is_parent,
        is_table=is_table,
        oversize=oversize,
        chunk_type=chunk_type,
        parent_chunk_id=parent_chunk_id,
        internal_refs=refs,
        embed_status="pending",
    )


def _cap_tokens(text: str, budget: int) -> str:
    return text if count_tokens(text) <= budget else text[:budget]


def _parent_chunk(
    dvid: str, sec: ClauseNode, blocks: dict[int, Block], cfg: ChunkConfig
) -> ChunkSpec:
    sec_blocks = [
        blocks[i] for i in sec.collect_block_indices() if blocks[i].type is not BlockType.TABLE
    ]
    joined = "\n".join(b.text for b in sec_blocks if b.text.strip())
    body = _cap_tokens(joined, cfg.parent_block_token_max)
    return _mk_chunk(
        dvid, sec.clause_path_norm(), 0, sec.clause_path(), body, sec_blocks, is_parent=True
    )


def _article_chunks(
    dvid: str,
    art: ClauseNode,
    blocks: dict[int, Block],
    cfg: ChunkConfig,
    parent_chunk_id: str | None = None,
) -> list[ChunkSpec]:
    art_blocks = [blocks[i] for i in art.collect_block_indices()]
    text_pairs = [
        (b.text, b) for b in art_blocks if b.type is not BlockType.TABLE and b.text.strip()
    ]
    table_blocks = [b for b in art_blocks if b.type is BlockType.TABLE]
    breadcrumb = art.clause_path()
    cp_norm = art.clause_path_norm()
    heading = art.title
    out: list[ChunkSpec] = []
    seq = 0

    body_text = "\n".join(t for t, _ in text_pairs)
    if text_pairs:
        if count_tokens(body_text) <= cfg.target_token_max:
            pblocks = [b for _, b in text_pairs]
            out.append(_mk_chunk(
                dvid, cp_norm, seq, breadcrumb, body_text, pblocks,
                parent_chunk_id=parent_chunk_id,
            ))
            seq += 1
        else:
            units = _decompose(text_pairs, cfg.target_token_max)  # 含单段超长拆分
            groups = _group_by_budget(units, lambda u: count_tokens(u[0]), cfg.target_token_max)
            _coalesce_tail(groups, lambda u: count_tokens(u[0]), cfg.target_token_min)
            for g, grp in enumerate(groups):
                content = "\n".join(u[0] for u in grp)
                body = content if g == 0 else f"{heading}\n{content}"  # 条头续接
                out.append(_mk_chunk(
                    dvid, cp_norm, seq, breadcrumb, body, [u[1] for u in grp],
                    oversize=any(u[2] for u in grp),
                    content_tokens=count_tokens(content),
                    parent_chunk_id=parent_chunk_id,
                ))
                seq += 1

    for tb in table_blocks:
        for seg in _table_segments(tb.table, cfg):
            out.append(_mk_chunk(
                dvid, cp_norm, seq, breadcrumb, seg, [tb], is_table=True,
                parent_chunk_id=parent_chunk_id,
            ))
            seq += 1
    return out


def _table_segments(table: Table, cfg: ChunkConfig) -> Iterator[str]:
    # markdown 序列化(合并单元格展开 + 首尾管道 + 表头分隔行)由 IR Table 统一提供,
    # 切块只负责按 token 预算拆数据行、每组重复表头块(与 to_markdown 同源,格式一致)。
    header, data = table.markdown_header_and_data()
    header_txt = "\n".join(header)
    if not data:
        yield header_txt
        return
    budget = max(1, cfg.target_token_max - count_tokens(header_txt))
    for grp in _group_by_budget(data, count_tokens, budget):
        yield "\n".join([*header, *grp])  # 每组重复 markdown 表头块
