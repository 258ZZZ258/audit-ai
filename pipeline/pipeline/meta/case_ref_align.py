"""T1.2 案例引用外规对齐(§9):「《X办法》第N条」→ 文号/标题命中 + clause_path_norm。

纯逻辑(无 LLM、无 PG):``lookup`` 注入(生产 = PG 查询,见 T2.1;测试 = 假实现)。
- 三级匹配:文号精确 → 标题精确 →(别名表 dict_aliases 留 §6.7/T2.4,本模块不接)。
- 条号经 ``normalize.normalize_clause_no`` 归一,与目标 doc 的 chunk ``clause_path_norm`` **末段**
  (= 条号)比对——案例反查精度到条;命中回填完整 path,超界/无 doc/无法归一 → ``resolved=False``。
- 任一未解析 → 聚合 ``ref_unresolved=True`` **标记**,**不阻塞案例入库**(§9);低优人工补录队列的
  消费待 ``quality_tickets`` 建表(§18.3,deferred)——**本阶段仅置标记,不入队**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pipeline.chunking.normalize import normalize_clause_no, strip_ws, to_halfwidth


@dataclass(frozen=True)
class RegDoc:
    """对齐命中的目标外规:文档身份 + 其全部 chunk 的 clause_path_norm 集合(供超界校验)。"""

    doc_version_id: str
    doc_number: str | None
    clause_norms: frozenset[str]


class RegLookup(Protocol):
    """外规查询接口:按文号 / 标题命中(生产 PG 实现 doc_versions + chunks 聚合)。"""

    def find(self, doc_number: str | None, title: str | None) -> RegDoc | None: ...


def _clause_no(raw: str) -> str | None:
    """从「第十五条」「第十五条第二款」「第二十一条之一」抽条号核心交 normalize_clause_no。"""
    s = strip_ws(to_halfwidth(raw)).removeprefix("第")
    s = re.sub(r"条之", "之", s, count=1)  # 插入条「X条之N」→「X之N」(归一前合形)
    core = s.split("条", 1)[0]  # 取首个「条」前(去掉「第Y款/项」等后缀)
    return core or None


def _tail(norm: str) -> str:
    """clause_path_norm 末段 = 条号(章/节无号祖先剥离后;款/项不入 path)。"""
    return norm.split("/")[-1]


def align_cited(cited: list[dict], lookup: RegLookup) -> tuple[list[dict], bool]:
    """对齐引用列表;返回 (对齐结果[], ref_unresolved)。

    cited 项:``{title?, doc_number?, clause?}``(clause = 条号原文,可含「第…条/款」)。
    结果项:``{doc_no, title, clause_path_norm, resolved}``——键名 ``doc_no``(非 DB 列名
    ``doc_number``)对齐 query 反查消费者契约(``query/case/bridge.py`` /
    ``query/judge/r5_judgment.py`` 读 ``doc_no`` + ``clause_path_norm`` 建反查 / 解析 chunk_id)。
    """
    out: list[dict] = []
    unresolved = False
    for c in cited:
        title = c.get("title")
        doc_number = c.get("doc_number")
        clause = c.get("clause")
        doc = lookup.find(doc_number, title)
        if doc is None:  # 文号/标题均未命中 → 整条未解析(别名重试留 T2.4)
            out.append(_row(doc_number, title, None, False))
            unresolved = True
            continue
        if not clause:  # 只引文档未引条 → 文档级命中
            out.append(_row(doc.doc_number, title, None, True))
            continue
        core = _clause_no(clause)
        try:
            cn = normalize_clause_no(core) if core else None
        except ValueError:
            cn = None
        if cn is None:  # 条号无法归一 → 未解析
            out.append(_row(doc.doc_number, title, None, False))
            unresolved = True
            continue
        match = next((n for n in sorted(doc.clause_norms) if _tail(n) == cn), None)
        if match:  # 条号在目标 doc 内 → 命中,回填完整 path
            out.append(_row(doc.doc_number, title, match, True))
        else:  # 条号超界(目标 doc 无此条)→ 未解析
            out.append(_row(doc.doc_number, title, None, False))
            unresolved = True
    return out, unresolved


def _row(doc_number: str | None, title: str | None, cpn: str | None, resolved: bool) -> dict:
    # 键名 doc_no:对齐 query 反查消费者契约(bridge / r5_judgment 读 doc_no + clause_path_norm)。
    return {
        "doc_no": doc_number,
        "title": title,
        "clause_path_norm": cpn,
        "resolved": resolved,
    }
