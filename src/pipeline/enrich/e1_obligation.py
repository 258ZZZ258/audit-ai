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

    两类义务词:
    - **非 bare-char 起始的 markers**(必须/不得/禁止/严禁/有义务…):整词子串,无歧义。
    - **`bare_chars`(应/须)**:这些单字绝大多数表义务(应≈98%、须填/须停),唯一高频陷阱在**前缀**——
      X应(相应/对应)、X须(无须/毋须=否定义务),见 `exclusions`。判定 = 出现某 bare 字、其前缀+该字
      不落 `exclusions` → 义务;evidence 优先取该字起始 marker(应当/须经…)否则该字本身。

    **前缀排除同样作用于 `应当`/`须经` 这类 marker**(修 `对应当`/`无须经`)。后缀歧义(应用/应急)
    在监管语料近乎不现,不设后缀排除(探针证据,避免造假阴)。Task/B1 在 golden set 上据误判迭代。
    """
    bare = cfg.bare_chars
    for m in cfg.markers:  # 非 bare-char 起始的 markers:整词子串即义务(无歧义)
        if (not bare or m[0] not in bare) and m in text:
            return True, m

    excl = set(cfg.exclusions)
    for i, ch in enumerate(text):  # bare 字:前缀+字 不落排除表 → 义务(句首无前缀→必不落)
        if ch in bare and (i == 0 or text[i - 1 : i + 1] not in excl):
            for m in cfg.markers:  # evidence 尽量取具体的 该字起始 marker
                if m[0] == ch and text.startswith(m, i):
                    return True, m
            return True, ch
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
