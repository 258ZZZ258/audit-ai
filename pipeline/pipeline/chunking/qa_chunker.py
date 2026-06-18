"""P-QA 监管问答切分(§6.3):一问一答 = 1 chunk。

Phase 2 实现:``^问[:：]`` / ``^答[:：]`` / 编号问答体识别;问句加权进面包屑;``chunk_type=qa``;
无条款树 / 无父子块(QA 自完备)。

边界识别函数 ``detect_qa_pairs`` 同时被切块与质检(指标 ``qa_pair_completeness``)复用——同一份
「问标记数 / 完整问答对数」口径,保证切块产出与质检度量一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from common.chunk_id import compute_chunk_id
from common.ir import Block, BlockType, IRDocument
from pipeline.chunking.chunker import ChunkSpec, count_tokens
from pipeline.chunking.normalize import to_halfwidth
from pipeline.config import ChunkConfig

# 问句标记:显式「问:」/「问:」,或编号问答体「1、」「2.」「3．」(阿拉伯编号 + 顿号/点)。
_Q_EXPLICIT = re.compile(r"^\s*问\s*[:：]\s*(.*)$", re.DOTALL)
_Q_NUMBERED = re.compile(r"^\s*\d+\s*[、.．]\s*(.*)$", re.DOTALL)
# 答句标记:显式「答:」/「答:」。
_A_MARK = re.compile(r"^\s*答\s*[:：]\s*(.*)$", re.DOTALL)


@dataclass
class QaPair:
    """一个问答对:问句文本 + 答句文本(可跨多块)+ 构成块(供页码跨度)。"""

    question: str
    answer: str
    blocks: list[Block]


@dataclass
class QaScan:
    """问答边界扫描结果:完整问答对 + 检测到的「问」标记总数(质检指标分母)。"""

    pairs: list[QaPair]
    question_markers: int


def _match_question(text: str) -> str | None:
    """命中问句标记则返回去前缀的问句正文,否则 None(显式「问:」优先于编号体)。"""
    norm = to_halfwidth(text)
    m = _Q_EXPLICIT.match(norm)
    if m:
        return m.group(1).strip()
    m = _Q_NUMBERED.match(norm)
    if m:
        return m.group(1).strip()
    return None


def _match_answer(text: str) -> str | None:
    """命中答句标记则返回去前缀的答句正文,否则 None。"""
    m = _A_MARK.match(to_halfwidth(text))
    return m.group(1).strip() if m else None


def detect_qa_pairs(doc: IRDocument) -> QaScan:
    """按文档序扫描问答边界:每个「问」标记起,答句正文延续到下一问/编号前为止。

    完整问答对 = 有「问」且其后出现「答:」;只有问、无答者不计入 pairs(但计入 question_markers)。
    """
    blocks = [b for b in doc.blocks if b.type is not BlockType.TABLE]
    pairs: list[QaPair] = []
    question_markers = 0

    i = 0
    n = len(blocks)
    while i < n:
        q = _match_question(blocks[i].text)
        if q is None:
            i += 1
            continue
        question_markers += 1
        q_block = blocks[i]
        # 收集本问答对的答句块:从下一块起,到下一个问/编号标记前为止。
        answer_parts: list[str] = []
        answer_blocks: list[Block] = []
        has_answer = False
        j = i + 1
        while j < n and _match_question(blocks[j].text) is None:
            a = _match_answer(blocks[j].text)
            if a is not None:
                has_answer = True
                if a:
                    answer_parts.append(a)
            elif has_answer:  # 答句正文续行(答标记已出现后的普通块)
                answer_parts.append(blocks[j].text.strip())
            answer_blocks.append(blocks[j])
            j += 1
        if has_answer:
            pairs.append(
                QaPair(
                    question=q,
                    answer="\n".join(p for p in answer_parts if p),
                    blocks=[q_block, *answer_blocks],
                )
            )
        i = j
    return QaScan(pairs=pairs, question_markers=question_markers)


def _page_span(blocks: list[Block]) -> tuple[int | None, int | None]:
    starts = [b.page for b in blocks if b.page is not None]
    if not starts:
        return None, None
    ends = [b.page_end or b.page for b in blocks if b.page is not None]
    return min(starts), max(ends)


def build_qa_specs(doc: IRDocument, cfg: ChunkConfig) -> list[ChunkSpec]:
    """一问一答 = 1 chunk(无条款树 / 无父子块,QA 自完备)。

    pair n(1-based):clause_path=问答/{n}、clause_path_norm=qa/{n}、seq=0;问句加权进面包屑;
    text = 面包屑 + 问答正文;chunk_type=qa。无问答边界 → 返回 []。
    """
    scan = detect_qa_pairs(doc)
    out: list[ChunkSpec] = []
    for n, pair in enumerate(scan.pairs, start=1):
        cp_norm = f"qa/{n}"
        breadcrumb = pair.question  # 问句加权进面包屑(QA 检索以问句匹配为主)
        text = f"{breadcrumb}\n问:{pair.question}\n答:{pair.answer}"
        ps, pe = _page_span(pair.blocks)
        out.append(
            ChunkSpec(
                chunk_id=compute_chunk_id(doc.doc_version_id, cp_norm, 0),
                doc_version_id=doc.doc_version_id,
                clause_path=f"问答/{n}",
                clause_path_norm=cp_norm,
                seq=0,
                text=text,
                breadcrumb=breadcrumb,
                page_start=ps,
                page_end=pe,
                token_count=count_tokens(text),
                is_parent=False,
                is_table=False,
                chunk_type="qa",
                parent_chunk_id=None,
                internal_refs=None,
                embed_status="pending",
            )
        )
    return out
