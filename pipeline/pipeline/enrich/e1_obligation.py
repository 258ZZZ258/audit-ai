"""E1 义务预打标(零 LLM 正则 + config 词表):判 chunk 是否义务条款,写 `clause_tags`。

判定(`match_obligation`)= 命中任一 `markers`(整词)**或**(`bare_ying` 时)「应」单字且其前缀不落
`exclusions`(排除 相应/适应/对应… 中的「应」)。词表/阈值全从 `config/obligation.yaml`,零硬编码。

CP-007 §19.1 扩展(本轮新增,纯规则、零 LLM):命中义务后另填 `clause_tags` 类型列——
- **deontic_type**:据命中情态词分类(应当/必须/应/须→obligation;不得/禁止/严禁/不应/不准→prohibition;
  责令→command;`classify_deontic` 纯函数)。写在 `is_obligation` 行上。
- **期限归一化**:`normalize_duration` 用正则在 chunk 文本里捞期限表达,归一到日
  (`norm_duration_days`),原文留 `surface_duration`(standoff,**不改 chunk 文本**)。命中则**另写一行**
  `tag_type="duration"`
  (独立于 is_obligation:期限可无义务、义务可无期限,行数互不污染,各自可查)。解析成功
  `norm_status="parsed"`,复合/不可解析(如「次年首个工作日」)`norm_status="unparsed"`、
  `norm_duration_days=None`、保留 surface。

富集副作用,**无状态机阻断权**:不改 pipeline_status;异常由装配层(`_structuring`)吞掉、不阻断终态。
reprocess 幂等靠 `tag`/`clear` 配对:`clear` 须在 s3 `replace_chunks`(删 chunk)**之前**调,删旧
`is_obligation`/`duration` 行避 `clause_tags.chunk_id` 外键;`tag` 在 chunks 重建后重打
(确定性 chunk_id)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select

from common.pg_models import Chunk, ClauseTag
from pipeline.chunking.normalize import cn_to_int
from pipeline.config import ObligationConfig
from pipeline.stage_base import StageContext

_TAG_TYPE = "is_obligation"
_DURATION_TAG_TYPE = "duration"

# ── deontic_type 分类(命中情态词 → 类别)。键按子串前缀匹配(命中词以某键起始即归该类)。 ──
# 词表与 obligation.yaml 的 markers/bare_chars 对齐;未列词(如 有义务/负有)兜底 obligation。
_DEONTIC_OBLIGATION = ("应当", "应该", "应予", "应", "必须", "须经", "须", "有义务", "负有")
_DEONTIC_PROHIBITION = ("不得", "禁止", "严禁", "不应", "不准")
_DEONTIC_COMMAND = ("责令",)

# 期限单位 → 日。⚠ 口径待甲方确认(§16-8 待确认口径):此处采用 v1.6 §19.1 文档默认折算
# (月=30、季=90、半年=180、年=365),为规则化归一的近似值,非精确历法日数。集中此常量,禁散落硬编码。
_DURATION_UNIT_DAYS = {
    "工作日": 1,  # 工作日按 1 计、另置 is_business_day=True(不折算成自然日)
    "日": 1,
    "天": 1,
    "月": 30,
    "季": 90,
    "年": 365,
}
# 固定期限词(自带数量语义、不接数字定语,如「半年」)→ 直接给日数,独立于「数+单位」正则。
_DURATION_FIXED = {
    "半年": 180,
}
_FIXED_RE = re.compile("|".join(re.escape(k) for k in _DURATION_FIXED))

# 数字段:中文数字(含十/百/千、零/〇、两)或 Arabic。供期限正则捕获「数 + 单位」。
_CN_NUM = "〇零一二两三四五六七八九十百千"
_NUM_RE = rf"(?:\d+|[{_CN_NUM}]+)"
# 复合单位先于裸单字:工作日 / 自然日(归到「日」)在前,日|天|月|季|年 在后。
_UNIT_RE = r"工作日|自然日|日|天|月|季|年"
_DURATION_RE = re.compile(rf"({_NUM_RE})\s*个?\s*({_UNIT_RE})")


@dataclass(frozen=True)
class TagResult:
    dvid: str
    tagged: int  # 命中(写行)块数
    total: int  # 受检非 parent 块数


@dataclass(frozen=True)
class DurationResult:
    """期限归一结果(纯 standoff,不回写 chunk 文本)。"""

    surface: str  # 原文期限表达,如 "九十日" / "5个工作日"
    norm_status: str  # "parsed" | "unparsed"
    norm_duration_days: int | None  # 归一到日;unparsed → None
    is_business_day: bool | None  # 工作日 True / 自然日(及折算单位)False;unparsed → None


def classify_deontic(marker: str | None) -> str | None:
    """命中情态词 → deontic_type(obligation|prohibition|command),纯函数。

    禁止类含否定前缀(不得/不应/不准),须先判,以免「不应」被「应」前缀吞掉。
    """
    if not marker:
        return None
    if marker.startswith(_DEONTIC_PROHIBITION):
        return "prohibition"
    if marker.startswith(_DEONTIC_COMMAND):
        return "command"
    if marker.startswith(_DEONTIC_OBLIGATION):
        return "obligation"
    return "obligation"  # 兜底:命中义务词但未列(有义务/负有)→ 义务


def normalize_duration(text: str) -> DurationResult | None:
    """文本中捞首个期限表达并归一到日;无期限返 None。纯函数,免栈免模型。

    口径(⚠ §16-8 待确认):工作日→is_business_day=True、norm=数字;自然日/裸日/天→False、norm=数字;
    月/季/年/半年→×30/×90/×365/180、False。中文数字与 Arabic 均支持。**复合/不可解析**期限
    (如「次年首个工作日」无「数+单位」结构)→ norm_status="unparsed"、
    norm_duration_days=None,留 surface。
    """
    # 先探「复合期限」线索(如 次年首个工作日):有期限语义但无「数+单位」可归一 → unparsed。
    compound = _detect_compound_unparsable(text)

    num_m = _DURATION_RE.search(text)
    fixed_m = _FIXED_RE.search(text)
    # 固定期限词(半年)无数字定语,「数+单位」正则捞不到 → 单独命中;两者皆中取文中靠前者。
    if fixed_m and (num_m is None or fixed_m.start() < num_m.start()):
        return DurationResult(
            surface=fixed_m.group(0), norm_status="parsed",
            norm_duration_days=_DURATION_FIXED[fixed_m.group(0)], is_business_day=False,
        )

    m = num_m
    if not m:
        if compound:
            return DurationResult(
                surface=compound, norm_status="unparsed",
                norm_duration_days=None, is_business_day=None,
            )
        return None

    surface = m.group(0)
    num_s, unit = m.group(1), m.group(2)
    try:
        n = cn_to_int(num_s)
    except ValueError:  # 数字段无法解析(理论上正则已限,稳健兜底)→ unparsed,留 surface
        return DurationResult(
            surface=surface, norm_status="unparsed",
            norm_duration_days=None, is_business_day=None,
        )

    if unit == "工作日":
        return DurationResult(surface, "parsed", n, True)
    if unit == "自然日":
        return DurationResult(surface, "parsed", n, False)
    factor = _DURATION_UNIT_DAYS.get(unit)
    if factor is None:  # 不该到此(正则单位集已限),稳健兜底
        return DurationResult(surface, "unparsed", None, None)
    return DurationResult(surface, "parsed", n * factor, False)


# 复合/相对期限提示词:出现且无可归一「数+单位」时,标 unparsed 留痕(口径待确认,不强行折算)。
_COMPOUND_HINTS = ("次年", "首个工作日", "次月", "当年", "下一个", "翌日")


def _detect_compound_unparsable(text: str) -> str | None:
    """探无法归一的相对/复合期限表达(返回命中提示片段,供 surface 留痕)。"""
    for h in _COMPOUND_HINTS:
        if h in text:
            return h
    return None


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
    """删该 dvid 全部 chunk 的 E1 行(`is_obligation` + `duration`),返回删除行数。

    reprocess 重入:**须在 s3 `replace_chunks`(删 chunk)之前调**——旧 tag 引用即将删除的 chunk,
    先清 tag 才不撞 `clause_tags.chunk_id` 外键。
    """
    with ctx.db.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        if not ids:
            return 0
        res = s.execute(
            delete(ClauseTag).where(
                ClauseTag.chunk_id.in_(ids),
                ClauseTag.tag_type.in_([_TAG_TYPE, _DURATION_TAG_TYPE]),
            )
        )
        return res.rowcount or 0


def tag(ctx: StageContext, dvid: str) -> TagResult:
    """非 parent chunk 命中义务词 → 写 `clause_tags`。仅写命中行。

    行语义(本轮 §19.1 扩展):
    - 命中义务 → 一行 `tag_type="is_obligation"`,`evidence`=命中词,新增 `deontic_type`=分类结果。
    - 文本含可识别期限 → **另一行** `tag_type="duration"`(独立于义务,期限/义务互不耦合):
      `tag_value`=norm_status,`evidence`=surface,填 `surface_duration`/`norm_duration_days`/
      `is_business_day`/`norm_status` 类型列。

    `tagged` 仅计**义务**块数(保持既有口径:golden / 集成测试据此断言,不受 duration 行影响)。
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
        tagged = 0
        for c in chunks:
            text = c.text or ""
            ok, ev = match_obligation(text, cfg)
            if ok:
                tagged += 1
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_TAG_TYPE,
                        tag_value="true",
                        evidence=(ev or "")[:256],
                        deontic_type=classify_deontic(ev),
                    )
                )
            dur = normalize_duration(text)
            if dur is not None:
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_DURATION_TAG_TYPE,
                        tag_value=dur.norm_status,
                        evidence=dur.surface[:256],
                        surface_duration=dur.surface[:64],
                        norm_duration_days=dur.norm_duration_days,
                        is_business_day=dur.is_business_day,
                        norm_status=dur.norm_status,
                    )
                )
        s.add_all(rows)
        return TagResult(dvid=dvid, tagged=tagged, total=len(chunks))
