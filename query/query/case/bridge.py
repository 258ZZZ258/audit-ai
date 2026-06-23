"""§6.3 案例桥接精确反查(CP-007):``cases.cited_regulations`` ↔ 外规条款身份。

**consumed-when-present**:``cited_regulations`` 是 L2 LLM 字段(默认关 → 默认 ``[]``),本模块只
**消费**已有值;默认路径索引空 → 精确反查返回 ``[]``,上层**诚实降级语义-only**、**绝不臆造外规引用**
(SPEC-R3 §0/§8 SC4)。

匹配键 ``norm_ref``(SPEC-R3 §9-Q3):发文字号/文号 + 条款路径,经半角化 + 去空白 + 括号变体归一。
``cited_regulations`` 单条目契约 = **dict(``doc_no`` + ``clause_path``)**;非 dict / 缺键的条目跳过
(真实 JSONB shape 随 L2 对齐落地校准,§15-⑤)。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from common.pg_models import Case
from pipeline.chunking.normalize import strip_ws, to_halfwidth


def _norm(s: str | None) -> str:
    """半角化 + 去空白(复用 chunking 归一口径,同 case_extract._norm)。"""
    return strip_ws(to_halfwidth(s or ""))


def _norm_dn(s: str) -> str:
    """文号括号变体归一(〔【→[、〕】→],同 l1_rules / case_extract._norm_dn)。"""
    return s.replace("〔", "[").replace("【", "[").replace("〕", "]").replace("】", "]")


def norm_ref(doc_no: str | None, clause_path: str | None) -> str:
    """外规条款身份归一键:``<归一文号>|<归一条款路径>``。匹配契约的唯一口径。"""
    return f"{_norm_dn(_norm(doc_no))}|{_norm(clause_path)}"


def _entry_key(entry) -> str | None:
    """``cited_regulations`` 单条目 → ``norm_ref`` 键;非 dict / 缺 doc_no&clause_path → None。"""
    if not isinstance(entry, dict):
        return None
    doc_no = entry.get("doc_no") or entry.get("文号")
    clause = entry.get("clause_path") or entry.get("clause_path_norm") or entry.get("条款")
    if not (doc_no or clause):
        return None
    return norm_ref(doc_no, clause)


def index_from_cases(cases: Iterable) -> dict[str, list[str]]:
    """纯函数:cases 行可迭代 → ``norm_ref 键 → [doc_version_id]`` 反查索引(去重保序)。

    空 / None / 不可解析的 ``cited_regulations`` 条目跳过(默认路径全空 → 返回 ``{}``)。
    """
    index: dict[str, list[str]] = {}
    for case in cases:
        for entry in getattr(case, "cited_regulations", None) or []:
            key = _entry_key(entry)
            if key is None:
                continue
            bucket = index.setdefault(key, [])
            if case.doc_version_id not in bucket:
                bucket.append(case.doc_version_id)
    return index


def build_cited_index(pg) -> dict[str, list[str]]:
    """从 PG 扫 ``cited_regulations`` 非空行建反查索引。

    ⚠ demo 规模全表扫可接受;生产换 JSONB GIN / containment 查询(`cited_regulations @> ...`)。
    """
    with pg.session() as s:
        cases = list(s.scalars(select(Case).where(Case.cited_regulations.isnot(None))))
    return index_from_cases(cases)


def citation_key(citation) -> str:
    """R1 ``Citation``(外规条款)→ ``norm_ref`` 键(doc_no + clause_path)。"""
    return norm_ref(getattr(citation, "doc_no", None), getattr(citation, "clause_path", None))


def cases_for_clauses(pg, clause_keys: Iterable[str]) -> list[str]:
    """外规条款 ``norm_ref`` 键列表 → 命中的案例 ``doc_version_id``(去重保序)。

    无键 / 索引空(默认路径)/ 未命中 → ``[]``(精确反查无数据,上层降级语义-only)。
    """
    keys = [k for k in clause_keys if k]
    if not keys:
        return []
    index = build_cited_index(pg)
    out: list[str] = []
    for k in keys:
        for dvid in index.get(k, []):
            if dvid not in out:
                out.append(dvid)
    return out
