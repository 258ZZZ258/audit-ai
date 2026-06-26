"""案例 L2 LLM 富集(§9,默认关 ``case_l2_enabled``):案例库与比对的最高价值维度。

两类 L2 字段(L1 占位 → LLM 抽取):
- **引用外规条款(T2.1,全管线最高价值)**:LLM 抽决定书"依据《X》第N条"援引的外规 →
  ``case_ref_align.align_cited`` 三级匹配(文号/标题/〔别名留 T2.4〕)归一到 ``clause_path_norm`` →
  写 ``cases.cited_regulations``(JSONB);任一未命中 → ``ref_unresolved=True``(进低优队列,
  **不阻塞案例入库**,§9)。
- **违规事由分类(T2.2)**:LLM 在 ``dict_violation_types`` 约束空间内选单一最贴切项 →
  **服务端二次裁剪**(LLM 越界值丢弃)→ ``cases.violation_category`` + 记 ``dict_version``;
  字典空 / 未命中 → None(consumed-when-present)。

纪律(镜像 E2,见 ``enrich/e2_tag.py``):
- 字典约束服务端裁剪(never trust the LLM to stay in-dict);不臆测(只抽/只分文中显式支持的);
- 富集**无状态机阻断权**:``apply`` 吞掉一切异常(LLMError / 对齐失败),不改 pipeline_status、
  不阻塞案例入库;
- 默认关 → 默认路径零 LLM(``case_l2_enabled=false`` 时本模块不被触达)。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from common.pg_models import Chunk, DocVersion
from pipeline.llm_client import make_llm_client
from pipeline.meta.case_ref_align import RegDoc, RegLookup, align_cited

logger = logging.getLogger(__name__)

_SYSTEM_CITED = (
    "你是证券公司案例(行政处罚 / 监管措施决定书)的引用外规抽取助手。任务:从决定书全文中,"
    "抽取其作为处罚 / 认定依据所援引的外部法规及条款。硬性规则:"
    "(1) 只抽决定书**明确作为依据援引**的外规,逐条列出;无引用则给空数组;"
    "(2) **不臆测**——只抽文中显式出现的法规名称 / 文号 / 条号,不据常识补全未写明的条款;"
    "(3) 每条为 "
    '{"title": 法规标题(书名号内原文,无则 null), "doc_number": 文号(如〔2020〕5号,无则 null), '
    '"clause": 条号原文(如第十五条 / 第十五条第二款,无则 null)},title 与 doc_number 至少一个非空;'
    "(4) 只输出 JSON 对象 "
    '{"cited": [...]},不输出 JSON 之外的任何文字。'
)

_SYSTEM_VIOLATION = (
    "你是证券公司案例的违规事由分类助手。任务:仅依据给定的【允许清单】,为该处罚决定书判定其"
    "「违规事由分类」(单一最贴切项)。硬性规则:"
    "(1) 取值必须**严格来自**允许清单原文,不得改写、近义替换或自创;"
    "(2) 只在决定书事实 / 认定明确支持时才给;无法明确归类一律留空,**不臆测**;"
    "(3) 只输出 JSON 对象 "
    '{"violation_category": "<清单中的一项,或 null>"},不输出 JSON 之外的任何文字。'
)


def build_cited_prompt(case_text: str) -> tuple[str, str]:
    """构造 (system, user):抽援引外规条款,只输出 ``{"cited": [...]}``。"""
    user = (
        "【处罚决定书全文】\n"
        + (case_text or "")
        + "\n\n请抽取作为处罚依据援引的外规条款,按规则只输出 JSON:"
        '{"cited": [{"title": ..., "doc_number": ..., "clause": ...}]}。无引用给空数组,不臆测。'
    )
    return _SYSTEM_CITED, user


def build_violation_prompt(case_text: str, allowed_names: list[str]) -> tuple[str, str]:
    """构造 (system, user):在【允许清单】内分违规事由,只输出 ``{"violation_category": ...}``。"""
    user = (
        "【允许清单 · 违规事由分类】\n"
        + ("、".join(allowed_names) if allowed_names else "(空)")
        + "\n\n【处罚决定书全文】\n"
        + (case_text or "")
        + "\n\n请按规则只输出 JSON:{\"violation_category\": \"...\"}。"
        "取值严格取自上述清单;无法明确归类留空,不臆测。"
    )
    return _SYSTEM_VIOLATION, user


def _coerce_item(item: object) -> dict | None:
    """规整单条引用为 ``{title, doc_number, clause}``;无对齐锚点(title/doc_number 皆空)→ 丢。"""
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    doc_number = item.get("doc_number")
    doc_number = doc_number.strip() if isinstance(doc_number, str) and doc_number.strip() else None
    if title is None and doc_number is None:
        return None  # 无文号也无标题 → 无对齐锚点,丢
    clause = item.get("clause")
    clause = clause.strip() if isinstance(clause, str) and clause.strip() else None
    return {"title": title, "doc_number": doc_number, "clause": clause}


def extract_cited(client, case_text: str) -> list[dict]:
    """调 LLM 抽援引外规;规整 + 丢无锚点项,返回 ``[{title, doc_number, clause}]``。"""
    system, user = build_cited_prompt(case_text)
    raw = client.chat_json(system, user)
    items = raw.get("cited") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        coerced = _coerce_item(it)
        if coerced is not None:
            out.append(coerced)
    return out


def classify_violation(
    client, case_text: str, allowed: dict[str, str | None]
) -> tuple[str | None, str | None]:
    """调 LLM 在字典内分违规事由;**服务端裁字典**(越界丢)。返回 (分类, dict_version)。

    ``allowed`` = ``{违规事由名: dict_version}``。字典空 → 不调 LLM 直接 None;
    越界 / 未命中 → None(consumed-when-present)。
    """
    if not allowed:
        return None, None  # 字典空 → 不调 LLM
    system, user = build_violation_prompt(case_text, list(allowed))
    raw = client.chat_json(system, user)
    val = raw.get("violation_category") if isinstance(raw, dict) else None
    if isinstance(val, str) and val in allowed:
        return val, allowed[val]
    return None, None  # 越界 / 未命中 / 非串 → None


class PgRegLookup:
    """生产外规查询(``case_ref_align.RegLookup`` 实现):PG 按文号 / 标题命中 effective 外规,
    聚合其全部 chunk 的 ``clause_path_norm`` 供超界校验。
    """

    def __init__(self, db) -> None:
        self._db = db

    def find(self, doc_number: str | None, title: str | None) -> RegDoc | None:
        with self._db.session() as s:
            dv = None
            if doc_number:
                dv = s.scalars(
                    select(DocVersion).where(
                        DocVersion.doc_number == doc_number,
                        DocVersion.version_status == "effective",
                    )
                ).first()
            if dv is None and title:  # 文号未命中 → 标题精确兜底
                dv = s.scalars(
                    select(DocVersion).where(
                        DocVersion.title == title,
                        DocVersion.version_status == "effective",
                    )
                ).first()
            if dv is None:
                return None
            norms = frozenset(
                n
                for n in s.scalars(
                    select(Chunk.clause_path_norm).where(
                        Chunk.doc_version_id == dv.doc_version_id,
                        Chunk.clause_path_norm.is_not(None),
                    )
                )
            )
            return RegDoc(
                doc_version_id=dv.doc_version_id, doc_number=dv.doc_number, clause_norms=norms
            )


def l2_fields(
    case_text: str,
    *,
    client,
    lookup: RegLookup,
    allowed_violations: dict[str, str | None],
) -> dict:
    """纯装配(注入 client / lookup / allowed):抽取 → 对齐 → 分类,返回要 merge 进 case 的字段。

    异常不在此吞(由 ``apply`` 包非阻断),便于单测直接断言形态。
    """
    cited = extract_cited(client, case_text)
    aligned, unresolved = align_cited(cited, lookup)
    category, dict_version = classify_violation(client, case_text, allowed_violations)
    return {
        "cited_regulations": aligned,
        "ref_unresolved": unresolved,
        "violation_category": category,
        "violation_category_dict_version": dict_version,
    }


def apply(ctx, case_text: str, fields: dict, *, client=None) -> None:
    """连 ctx 跑案例 L2,把结果 merge 进 ``fields``(in-place)。**非阻断**:任何异常(LLMError /
    对齐失败)吞掉记日志,保留 L1 占位(None/[]/False),不阻塞案例入库(§9)。

    ``client`` 为 None 时经 ``make_llm_client(ctx.config.llm.model)`` 构造
    (测试注入 fake 即免真调用)。
    """
    try:
        if client is None:
            client = make_llm_client(ctx.config.llm.model)
        allowed = {v.name: v.dict_version for v in ctx.db.get_violation_types()}
        fields.update(
            l2_fields(
                case_text,
                client=client,
                lookup=PgRegLookup(ctx.db),
                allowed_violations=allowed,
            )
        )
    except Exception as e:  # noqa: BLE001 案例 L2 失败不阻塞案例入库(§9,同富集纪律)
        logger.warning("案例 L2 富集失败(不阻断):%s", e)
