"""E1 义务预打标(零 LLM 正则 + config 词表):判 chunk 是否义务条款,写 `clause_tags`。

判定(`match_obligation`)= 命中任一 `markers`(整词)**或**(`bare_ying` 时)「应」单字且其前缀不落
`exclusions`(排除 相应/适应/对应… 中的「应」)。词表/阈值全从 `config/obligation.yaml`,零硬编码。

富集副作用,**无状态机阻断权**:不改 pipeline_status;异常由装配层(`_structuring`)吞掉、不阻断终态。
reprocess 幂等靠 `tag`/`clear` 配对:`clear` 须在 s3 `replace_chunks`(删 chunk)**之前**调,删旧
`is_obligation` 行避 `clause_tags.chunk_id` 外键;`tag` 在 chunks 重建后重打(确定性 chunk_id)。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select

from pipeline.config import ObligationConfig
from pipeline.index.pg_models import Chunk, ClauseTag
from pipeline.stage_base import StageContext

_TAG_TYPE = "is_obligation"


@dataclass(frozen=True)
class TagResult:
    dvid: str
    tagged: int  # 命中(写行)块数
    total: int  # 受检非 parent 块数


def match_obligation(text: str, cfg: ObligationConfig) -> tuple[bool, str | None]:
    """文本是否义务条款 +(命中词 | None)。

    整词 `markers` 优先(命中即返该词);未中且 `bare_ying` 时,「应」单字加边界:前缀+应 落 `exclusions`
    (相应/适应/对应…)则跳过,否则算义务、evidence="应"。Task 阶段在 golden set 上据误判迭代词表。
    """
    for m in cfg.markers:
        if m in text:
            return True, m
    if cfg.bare_ying:
        excl = set(cfg.exclusions)
        for i, ch in enumerate(text):
            if ch == "应":
                pair = text[i - 1 : i + 1] if i > 0 else "应"  # 句首无前缀→单字,必不落排除表
                if pair not in excl:
                    return True, "应"
    return False, None


def clear(ctx: StageContext, dvid: str) -> int:
    """删该 dvid 全部 chunk 的 `is_obligation` 行,返回删除行数。

    reprocess 重入:**须在 s3 `replace_chunks`(删 chunk)之前调**——旧 tag 引用即将删除的 chunk,
    先清 tag 才不撞 `clause_tags.chunk_id` 外键。
    """
    with ctx.db.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        if not ids:
            return 0
        res = s.execute(
            delete(ClauseTag).where(
                ClauseTag.chunk_id.in_(ids), ClauseTag.tag_type == _TAG_TYPE
            )
        )
        return res.rowcount or 0


def tag(ctx: StageContext, dvid: str) -> TagResult:
    """非 parent chunk 命中义务词 → 写 `clause_tags(is_obligation, evidence=命中词)`。仅写命中行。

    幂等由调用方先 `clear` 保证(本函数只插不删)。`e1_enabled` gate 在装配层,被调即写。
    """
    cfg = ctx.config.obligation
    with ctx.db.session() as s:
        chunks = [
            c
            for c in s.scalars(select(Chunk).where(Chunk.doc_version_id == dvid))
            if not c.is_parent  # = corpus_rows.indexable_chunks 口径(parent 仅 PG,不打标)
        ]
        rows = []
        for c in chunks:
            ok, ev = match_obligation(c.text or "", cfg)
            if ok:
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_TAG_TYPE,
                        tag_value="true",
                        evidence=(ev or "")[:256],
                    )
                )
        s.add_all(rows)
        return TagResult(dvid=dvid, tagged=len(rows), total=len(chunks))
