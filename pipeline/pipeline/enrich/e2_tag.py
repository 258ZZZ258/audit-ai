"""E2 条款级 LLM 打标(§19.2 / CP-007):给条款块打「适用实体类型 / 责任部门 / 涉及事项」。

与 E1(零 LLM 正则)对照:E2 经 LLM、**默认关**(`e2_enabled`);默认路径零 LLM(本模块不被构造/触达)。

核心纪律:
- **字典约束**——三类标签的取值空间是字典(`dict_entity_types` / `dict_departments` /
  `dict_biz_domains`)。prompt 把允许名单交给模型,但**服务端二次裁剪**:LLM 返回的任何不在名单
  内的值一律丢弃(never trust the LLM to stay in-dict)。
- **不臆测**——只在条文显式限定时才打;无显式限定留空,不据常识/类比补全。
- 富集副作用,**无状态机阻断权**:不改 pipeline_status;LLMError / 异常由装配层(`_safe_e2`)吞掉。
- 幂等/可重打:写前先 `clear` 该 dvid 的 E2 行(只清 E2 的 tag_type + entity_type 列,不碰 E1 的
  is_obligation / duration 行)。确定性 chunk_id 使重打覆盖安全。

行方案(写入 `clause_tags`):
- 适用实体类型(校验后列表)→ 一行 `tag_type="e2_entity_type"`,其 `entity_type` JSONB 列存该列表,
  `evidence` 存字典版本快照(`dict_version`)。
- 责任部门 → 每名一行 `tag_type="department"`,`tag_value=<名>`,`evidence=<dict_version>`。
- 涉及事项 → 每名一行 `tag_type="matter"`,`tag_value=<名>`,`evidence=<dict_version>`。

dict_version 记录:`dict_entity_types` / `dict_departments` 行自带 `dict_version`;
`dict_biz_domains` 无该列,故事项以 `_BIZ_DICT_VERSION_NONE` 占位。每类的版本写进对应行的
`evidence`,使「按字典版本重打」可行(升版后整批 clear + 重跑)。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select

from common.pg_models import Chunk, ClauseTag
from pipeline.llm_client import make_llm_client
from pipeline.stage_base import StageContext

# E2 写入 / 清理的 tag_type 集合(scope clear 到这三类 + entity_type 列,绝不碰 E1 的
# is_obligation / duration 行)。
_TAG_ENTITY = "e2_entity_type"
_TAG_DEPARTMENT = "department"
_TAG_MATTER = "matter"
_E2_TAG_TYPES = (_TAG_ENTITY, _TAG_DEPARTMENT, _TAG_MATTER)

# dict_biz_domains 无 dict_version 列(seed schema 既定),事项行版本以此占位。
_BIZ_DICT_VERSION_NONE = "n/a"

_SYSTEM_PROMPT = (
    "你是证券公司制度条款的合规打标助手。任务:仅依据给定的【允许清单】,为条款判定其"
    "「适用实体类型」「责任部门」「涉及事项」。"
    "硬性规则:"
    "(1) 取值必须**严格来自**对应的允许清单原文,不得改写、近义替换或自创;"
    "(2) **只在条文显式限定时才打**——条文明确点名某实体类型/部门/事项才填;无显式限定一律留空,"
    "**不臆测、不据常识或类比补全**;"
    "(3) 只输出 JSON 对象,形如 "
    '{"entity_type": [], "departments": [], "matters": []},三个键均为字符串数组,'
    "无命中则给空数组;不输出 JSON 之外的任何文字。"
)


@dataclass(frozen=True)
class E2Dicts:
    """E2 三类约束字典的「名→版本」映射(一次加载,逐块复用)。"""

    entity_types: dict[str, str | None]  # name -> dict_version
    departments: dict[str, str | None]
    matters: dict[str, str | None]  # biz_domains;无 dict_version → 占位


@dataclass(frozen=True)
class E2Result:
    dvid: str
    tagged: int  # 至少打了一类标签的块数
    total: int  # 受检非 parent 块数


def build_e2_prompt(
    chunk_text: str,
    entity_names: list[str],
    dept_names: list[str],
    matter_names: list[str],
) -> tuple[str, str]:
    """构造 (system, user):system 含字典约束 + 不臆测规则,user 含三份允许清单 + 待标条文。"""
    user = (
        "【允许清单 · 适用实体类型】\n"
        + ("、".join(entity_names) if entity_names else "(空)")
        + "\n\n【允许清单 · 责任部门】\n"
        + ("、".join(dept_names) if dept_names else "(空)")
        + "\n\n【允许清单 · 涉及事项】\n"
        + ("、".join(matter_names) if matter_names else "(空)")
        + "\n\n【待打标条文】\n"
        + (chunk_text or "")
        + "\n\n请按规则只输出 JSON:"
        '{"entity_type": [...], "departments": [...], "matters": [...]}。'
        "取值严格取自上述清单;无显式限定留空,不臆测。"
    )
    return _SYSTEM_PROMPT, user


def _enforce(returned: object, allowed: set[str]) -> list[str]:
    """服务端字典约束:从 LLM 返回值里只保留落在 allowed 内的字符串(去重、保序)。"""
    if not isinstance(returned, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in returned:
        if isinstance(v, str) and v in allowed and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def tag_chunk(client, chunk_text: str, dicts: E2Dicts) -> dict[str, list[str]]:
    """调 LLM 给单块打标,再**服务端裁字典**;返回 {entity_type, departments, matters}。

    LLM 返回里任何不在允许名单的值都被丢弃(绝不信任模型自守约束)。
    """
    entity_names = list(dicts.entity_types)
    dept_names = list(dicts.departments)
    matter_names = list(dicts.matters)
    system, user = build_e2_prompt(chunk_text, entity_names, dept_names, matter_names)
    raw = client.chat_json(system, user)
    if not isinstance(raw, dict):
        raw = {}
    return {
        "entity_type": _enforce(raw.get("entity_type"), set(entity_names)),
        "departments": _enforce(raw.get("departments"), set(dept_names)),
        "matters": _enforce(raw.get("matters"), set(matter_names)),
    }


def _load_dicts(ctx: StageContext) -> E2Dicts:
    """一次性加载三类约束字典(名→版本)。biz_domains 无 dict_version 列 → 占位。"""
    pg = ctx.db
    return E2Dicts(
        entity_types={d.name: d.dict_version for d in pg.get_entity_types()},
        departments={d.name: d.dict_version for d in pg.get_departments()},
        matters={d.name: _BIZ_DICT_VERSION_NONE for d in pg.get_biz_domains()},
    )


def clear(ctx: StageContext, dvid: str) -> int:
    """删该 dvid 全部 chunk 的 E2 行(entity_type / department / matter),返回删除行数。

    scope 严格限于 `_E2_TAG_TYPES`:不触 E1 的 is_obligation / duration 行(entity_type JSONB 列
    随 e2_entity_type 行一并删,无需单独处理)。与 E1 一致须在 s3 `replace_chunks` 删 chunk 之前调,
    避 `clause_tags.chunk_id` 外键。
    """
    with ctx.db.session() as s:
        ids = list(s.scalars(select(Chunk.chunk_id).where(Chunk.doc_version_id == dvid)))
        if not ids:
            return 0
        res = s.execute(
            delete(ClauseTag).where(
                ClauseTag.chunk_id.in_(ids),
                ClauseTag.tag_type.in_(_E2_TAG_TYPES),
            )
        )
        return res.rowcount or 0


def run_e2(ctx: StageContext, doc_version_id: str, *, client=None) -> E2Result:
    """对该 dvid 的条款块跑 E2 打标,写 `clause_tags`(先 clear 保幂等)。

    选块口径同 E1:非 parent chunk(= 可索引块)。`client` 为 None 时经
    `make_llm_client(ctx.config.llm.model)` 构造(测试注入 fake 即免真调用)。
    """
    if client is None:
        client = make_llm_client(ctx.config.llm.model)

    dicts = _load_dicts(ctx)
    clear(ctx, doc_version_id)

    with ctx.db.session() as s:
        chunks = [
            c
            for c in s.scalars(
                select(Chunk).where(Chunk.doc_version_id == doc_version_id)
            )
            if not c.is_parent  # = indexable_chunks 口径(parent 仅 PG,不打标)
        ]
        rows: list[ClauseTag] = []
        tagged = 0
        for c in chunks:
            res = tag_chunk(client, c.text or "", dicts)
            entity = res["entity_type"]
            depts = res["departments"]
            matters = res["matters"]
            if not (entity or depts or matters):
                continue  # 无显式限定 → 不写行(不臆测的落地:空命中即空行)
            tagged += 1
            if entity:
                ent_ver = _versions_for(entity, dicts.entity_types)
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_TAG_ENTITY,
                        tag_value="true",
                        evidence=ent_ver[:256],
                        entity_type=entity,
                    )
                )
            for name in depts:
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_TAG_DEPARTMENT,
                        tag_value=name[:64],
                        evidence=(dicts.departments.get(name) or "")[:256],
                    )
                )
            for name in matters:
                rows.append(
                    ClauseTag(
                        chunk_id=c.chunk_id,
                        tag_type=_TAG_MATTER,
                        tag_value=name[:64],
                        evidence=(dicts.matters.get(name) or "")[:256],
                    )
                )
        s.add_all(rows)
        return E2Result(dvid=doc_version_id, tagged=tagged, total=len(chunks))


def _versions_for(names: list[str], ver_map: dict[str, str | None]) -> str:
    """实体类型行的 evidence:命中名各自字典版本去重拼接(如 "v0-draft-2026-06")。"""
    vers: list[str] = []
    for n in names:
        v = ver_map.get(n)
        if v and v not in vers:
            vers.append(v)
    return ",".join(vers)
