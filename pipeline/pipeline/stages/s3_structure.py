"""S3 结构化:载 IR → 装配条款树 + 六规则切块(L3)→ chunks 落 PG → META_REVIEW。

切块逻辑全在 ``chunking.chunker.build_chunks``(建树 + 六规则 + 确定性 chunk_id);本 stage 只做
ChunkSpec→PG 行映射与幂等写(``replace_chunks``)。父块(节级)与表格块一并入 PG——Milvus 排除留到
s5;``chunk_status`` 默认 staging(INDEXED 前对检索不可见)。状态机出边唯一:STRUCTURING → META_REVIEW
(C2 落地 s4 后,STRUCTURING 阶段变 s3+s4 复合,本 stage 不变)。
"""

from __future__ import annotations

from common.pg_models import Chunk, Document, DocVersion
from pipeline.chunking.chunker import ChunkSpec
from pipeline.chunking.profile_router import build_specs
from pipeline.stage_base import StageContext, StageResult
from pipeline.states import PipelineState


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    ir = ctx.object_store.load_ir(doc_version_id)
    dv = ctx.db.get(DocVersion, doc_version_id)
    degraded = bool(dv and dv.degraded)  # 降级件(degrade 处置重入)→ chunk 标 degraded
    doc = ctx.db.get(Document, dv.logical_id) if dv else None
    corpus_type = (doc.corpus_type if doc else "") or "P-INT"  # 按 profile 选切块策略
    specs = build_specs(ir, corpus_type, ctx.config.chunk)
    ctx.db.replace_chunks(doc_version_id, [_to_row(s, degraded) for s in specs])
    return StageResult(next_state=PipelineState.META_REVIEW)


def _to_row(spec: ChunkSpec, degraded: bool) -> Chunk:
    return Chunk(
        chunk_id=spec.chunk_id,
        doc_version_id=spec.doc_version_id,
        clause_path=spec.clause_path,
        clause_path_norm=spec.clause_path_norm,
        seq=spec.seq,
        text=spec.text,
        breadcrumb=spec.breadcrumb,
        page_start=spec.page_start,
        page_end=spec.page_end,
        token_count=spec.token_count,
        is_parent=spec.is_parent,
        is_table=spec.is_table,
        chunk_type=spec.chunk_type,  # clause | table(与 is_parent/is_table 并存)
        parent_chunk_id=spec.parent_chunk_id,  # 子块指向节级父块(无节则 None)
        internal_refs=spec.internal_refs,  # 正文条款引用(前置信号);父/表块为 None
        embed_status=spec.embed_status,  # 建块即 pending(§8.1)
        oversize=spec.oversize,  # 单段超长字符硬切的质量信号
        degraded=degraded,  # 取自 dv.degraded;chunk_status 用模型默认 staging
    )
