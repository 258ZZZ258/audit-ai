"""P-CASE 案例切分(§6.4 / §9):处罚决定书按要素分段 + 全文摘要块。

Phase 3 实现:当事人 / 违规事实 / 处罚依据 / 处罚决定 段首模式分段 → ``chunk_type=case_section``;
另出全文摘要块 ``chunk_type=case_summary``(LLM 摘要默认关、留接口);要素抽取入 ``cases`` 表。

切分启发式(对块序鲁棒,不依赖固定先后):逐块扫 ``doc.blocks`` 文本,命中某要素段首模式即
开一新段,正文延续到下一段首/文末。每段 → 1 个 ``ChunkSpec``;另产 1 个全文摘要块。
未命中任何要素 → 整文兜底为单个 ``case_section`` + 摘要块(决定书必可检索,绝不返回 [])。
"""

from __future__ import annotations

import re

from common.chunk_id import compute_chunk_id
from common.ir import Block, BlockType, IRDocument
from pipeline.chunking.chunker import ChunkSpec, count_tokens
from pipeline.config import ChunkConfig

# 四要素段首模式(归一后逐块匹配块首):命中即认定新段起点。顺序即输出优先级,但段实际
# 顺序随文档而定(扫描时遇到才开段)。robust:某要素缺失则该段不出,不影响其余段。
_SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 违规事实须先于「当事人」匹配:"经查,…存在以下问题:" 也以冒号收尾,顺序在前防误判为当事人。
    ("违规事实", re.compile(r"^\s*(经查|违法事实|违规事实|存在以下)")),
    ("处罚依据", re.compile(r"^\s*(依据|根据.*《|违反了)")),
    ("处罚决定", re.compile(r"^\s*(现决定|我会决定|我局决定|决定|责令|处以)")),
    # 当事人:显式前缀,或「机构/个人名 + 冒号」抬头(警示函/决定书首段常无"当事人:"前缀)。
    (
        "当事人",
        re.compile(
            r"^\s*(?:当事人|被处罚人|被检查)"
            r"|^.{2,48}(?:公司|中心|银行|集团|协会|事务所|、|先生|女士).{0,12}[:：]\s*$"
        ),
    ),
]

_SUMMARY_MAX_CHARS = 150  # 全文摘要正文截断长度(规则版;LLM ≤150 字摘要见下)


def _match_section(text: str) -> str | None:
    """块首命中某要素段首模式则返回段名,否则 None(按 _SECTION_PATTERNS 顺序,先命中先取)。"""
    for name, pat in _SECTION_PATTERNS:
        if pat.match(text):
            return name
    return None


def _page_span(blocks: list[Block]) -> tuple[int | None, int | None]:
    starts = [b.page for b in blocks if b.page is not None]
    if not starts:
        return None, None
    ends = [b.page_end or b.page for b in blocks if b.page is not None]
    return min(starts), max(ends)


def _segment_sections(blocks: list[Block]) -> list[tuple[str, list[Block]]]:
    """逐块扫描切要素段:命中段首模式即开新段,正文延续到下一段首/文末。

    返回 ``[(段名, 构成块), ...]``(按文档序)。段首前的引文(标题/抬头)归入第一个要素段;
    无任何要素命中则返回 []。
    """
    sections: list[tuple[str, list[Block]]] = []
    cur_name: str | None = None
    cur_blocks: list[Block] = []
    for b in blocks:
        name = _match_section(b.text)
        if name is not None:
            if cur_name is not None:
                sections.append((cur_name, cur_blocks))
            cur_name, cur_blocks = name, [b]
        elif cur_name is not None:  # 段内续行
            cur_blocks.append(b)
        # cur_name 仍为 None(尚未开段)的前导块直接丢弃(标题另由 breadcrumb 承载)
    if cur_name is not None:
        sections.append((cur_name, cur_blocks))
    return sections


def _section_body(blocks: list[Block]) -> str:
    return "\n".join(b.text for b in blocks if b.text.strip())


def _summary_text(doc: IRDocument, sections: list[tuple[str, list[Block]]]) -> str:
    """规则版全文摘要正文:标题 + 当事人 + 违规事实段首,截断 ~150 字。

    ⚠ 升级点:L2 LLM ≤150 字摘要默认关(本阶段不调 LLM);开时由摘要工厂生成,替换此处规则文本。
    """
    by_name = {name: blocks for name, blocks in sections}
    parts: list[str] = []
    if doc.title:
        parts.append(doc.title)
    for key in ("当事人", "违规事实"):
        if key in by_name:
            parts.append(_section_body(by_name[key]))
    text = " ".join(p for p in parts if p)
    return text[:_SUMMARY_MAX_CHARS]


def _mk_spec(
    doc: IRDocument,
    k: int,
    section_name: str,
    body: str,
    page_blocks: list[Block],
    chunk_type: str,
) -> ChunkSpec:
    """构造一个 case 块(k 为 1-based 全局序;clause_path_norm=case/{k},确定性 chunk_id)。"""
    cp_norm = f"case/{k}"
    breadcrumb = f"《{doc.title or ''}》 > {section_name}"
    text = f"{breadcrumb}\n{body}"
    ps, pe = _page_span(page_blocks)
    return ChunkSpec(
        chunk_id=compute_chunk_id(doc.doc_version_id, cp_norm, 0),
        doc_version_id=doc.doc_version_id,
        clause_path=f"案例/{section_name}",
        clause_path_norm=cp_norm,
        seq=0,
        text=text,
        breadcrumb=breadcrumb,
        page_start=ps,
        page_end=pe,
        token_count=count_tokens(text),
        is_parent=False,
        is_table=False,
        chunk_type=chunk_type,
        parent_chunk_id=None,
        internal_refs=None,
        embed_status="pending",
    )


def build_case_specs(doc: IRDocument, cfg: ChunkConfig) -> list[ChunkSpec]:  # noqa: ARG001
    """处罚决定书按要素分段 + 全文摘要块(§6.4)。

    每个命中的要素段 → 1 个 ``case_section``;另出 1 个 ``case_summary`` 全文摘要块。
    无任何要素命中 → 整文兜底为单个 ``case_section`` + 摘要块(非空文档绝不返回 [])。
    cfg 暂未用(案例切分不依赖 token 预算;预留以与 build_specs 路由签名一致)。
    """
    text_blocks = [b for b in doc.blocks if b.type is not BlockType.TABLE]
    sections = _segment_sections(text_blocks)

    out: list[ChunkSpec] = []
    k = 1
    if sections:
        for name, blocks in sections:
            out.append(_mk_spec(doc, k, name, _section_body(blocks), blocks, "case_section"))
            k += 1
    else:  # 兜底:无要素段首 → 整文一个 case_section(决定书必可检索)
        body = _section_body(text_blocks)
        out.append(_mk_spec(doc, k, "全文", body, text_blocks, "case_section"))
        k += 1

    # 全文摘要块(规则版;LLM 摘要为升级点,默认关)
    out.append(
        _mk_spec(doc, k, "摘要", _summary_text(doc, sections), text_blocks, "case_summary")
    )
    return out
