"""S3 结构化:载 IR → 装配条款树 + 六规则切块(L3)→ chunks 落 PG → META_REVIEW。

切块逻辑全在 ``chunking.chunker.build_chunks``(建树 + 六规则 + 确定性 chunk_id);本 stage 只做
ChunkSpec→PG 行映射与幂等写(``replace_chunks``)。父块(节级)与表格块一并入 PG——Milvus 排除留到
s5;``chunk_status`` 默认 staging(INDEXED 前对检索不可见)。状态机出边唯一:STRUCTURING → META_REVIEW
(C2 落地 s4 后,STRUCTURING 阶段变 s3+s4 复合,本 stage 不变)。
"""

from __future__ import annotations

from pipeline.chunking.chunker import ChunkSpec, build_chunks
from pipeline.index.pg_models import Chunk
from pipeline.stage_base import StageContext, StageResult
from pipeline.states import PipelineState


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    ir = ctx.object_store.load_ir(doc_version_id)
    specs = build_chunks(ir, ctx.config.chunk)
    ctx.db.replace_chunks(doc_version_id, [_to_row(s) for s in specs])
    return StageResult(next_state=PipelineState.META_REVIEW)


def _to_row(spec: ChunkSpec) -> Chunk:
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
        degraded=False,  # 降级件不走 s3(见 B6);chunk_status 用模型默认 staging
    )
