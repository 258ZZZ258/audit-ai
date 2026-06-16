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
    - **非「应」类**(必须/不得/禁止/严禁/不应/不准/有义务/负有/责令/须经):整词子串,无歧义。
    - **「应」类**:监管语料里「应」≈98% 为义务(`应当` 占绝大多数,`应+动词` 亦义务),唯一高频陷阱是
      **前缀「相/对/适…应」**(相应/对应…,见 `exclusions`)。故「应」判定 = 出现「应」且其前缀+应 不落
      `exclusions` → 义务;evidence 优先取更具体的 `应`-起始 marker(应当/应该/应予),否则 "应"。
      **前缀排除同样作用于 `应当` 这类 marker**(修 `对应当`/`相应当` 子串误命中)。`bare_ying` 关时
      仅认显式 `应`-起始 marker(仍带前缀排除)。后缀歧义(应用/应急…)在监管语料近乎不现,故不设后缀排除
      (探针证据;避免造假阴)。Task/B1 在 golden set 上据误判迭代。
    """
    for m in cfg.markers:  # 非「应」类:整词子串即义务
        if not m.startswith("应") and m in text:
            return True, m

    excl = set(cfg.exclusions)
    ying_markers = [m for m in cfg.markers if m.startswith("应")]

    def _prefix_ok(i: int) -> bool:  # 「应」在 i 处,前缀+应 不落排除表(句首无前缀→必不落)
        return i == 0 or text[i - 1 : i + 1] not in excl

    if cfg.bare_ying:
        for i, ch in enumerate(text):
            if ch == "应" and _prefix_ok(i):
                for m in ying_markers:  # evidence 尽量取具体 应X marker
                    if text.startswith(m, i):
                        return True, m
                return True, "应"
    else:  # 仅显式 应-起始 marker,仍带前缀排除
        for m in ying_markers:
            idx = text.find(m)
            while idx != -1:
                if _prefix_ok(idx):
                    return True, m
                idx = text.find(m, idx + 1)
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
