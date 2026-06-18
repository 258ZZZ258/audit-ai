"""按 ``corpus_type`` 选切块策略(profile 路由)。

- P-INT / P-EXT(制度) → 条款树六规则切块(``chunker.build_chunks``);
- P-QA(监管问答) → 问答对切分(§6.3);
- P-CASE(案例) → 要素分段 + 全文摘要块(§6.4 / §9)。

所有策略产出**同构** ``list[ChunkSpec]``,下游(s3 落库 / s5 索引 / 检索)不感知 profile。
未知 corpus_type 退回制度条款树(与历史行为一致,不破坏现有 P-INT/P-EXT 件)。
"""

from __future__ import annotations

from common.ir import IRDocument
from pipeline.chunking.chunker import ChunkSpec, build_chunks
from pipeline.config import ChunkConfig


def build_specs(doc: IRDocument, corpus_type: str, cfg: ChunkConfig) -> list[ChunkSpec]:
    """按 corpus_type 分流到对应切块策略;返回同构 ChunkSpec 列表。"""
    if corpus_type == "P-QA":
        from pipeline.chunking.qa_chunker import build_qa_specs

        return build_qa_specs(doc, cfg)
    if corpus_type == "P-CASE":
        from pipeline.chunking.case_chunker import build_case_specs

        return build_case_specs(doc, cfg)
    return build_chunks(doc, cfg)  # P-INT / P-EXT / 未知 → 制度条款树
