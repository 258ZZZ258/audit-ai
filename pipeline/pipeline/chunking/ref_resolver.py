"""T1.3 ref_resolver R1–R3:文档内指代纯规则 standoff 解析(§6.7)。

S3 条款树建成后运行的纯查表(零 LLM):扫一个 chunk 的正文,产出字面引用四类之三——
R1 文档自指(本办法/本条/本章)、R2 相对条款(前条;前款款级不解析)、R3 绝对条款(第十五条)。
R4 跨文档(《X》第N条)留 T2.4。``chunks.text`` 含面包屑前缀(内含本条条号),故扫描从
``body_offset`` 起、且跳过 body 起始的条头自指(归一条号 == 当前条号)。``method`` 恒 rule。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select

from common.pg_models import Chunk, ClauseReference
from pipeline.chunking.normalize import normalize_clause_no
from pipeline.stage_base import StageContext

_CN = "〇零一二三四五六七八九十百千两"
_R3 = re.compile(rf"第([{_CN}\d]+)条(?:之([{_CN}\d]+))?")  # 绝对条款(+插入条「之N」)
_R1_DOC = re.compile(r"本(?:办法|规定|细则|指引|制度|通知|条例|规则)")  # 文档自指
_R1_TIAO = re.compile(r"本条")
_R1_ZHANG = re.compile(r"本章")
_R2_TIAO = re.compile(r"前条")
_R2_KUAN = re.compile(rf"前(?:[{_CN}]+)?款|上述各款")  # 款级:chunk 无款边界 → 不解析


@dataclass(frozen=True)
class ParsedRef:
    span_start: int
    span_end: int
    surface_text: str
    ref_type: str  # R1 | R2 | R3
    target_doc_version_id: str | None
    target_clause_path_norm: str | None
    resolution_status: str  # resolved | unresolved


def _tail(norm: str | None) -> str | None:
    """clause_path_norm 末段 = 条号(章/节无号祖先已剥离;款/项不入 path)。"""
    return norm.split("/")[-1] if norm else None


def resolve_refs(
    text: str,
    body_offset: int,
    clause_path_norm: str | None,
    doc_clause_norms: frozenset[str],
    doc_order: list[str],
    dvid: str,
) -> list[ParsedRef]:
    """解析单 chunk 的文档内指代;返回按 span 升序的 ParsedRef 列表(R1–R3)。"""
    refs: list[ParsedRef] = []
    self_tail = _tail(clause_path_norm)

    def _mk(m: re.Match, rtype: str, tcpn: str | None, status: str) -> ParsedRef:
        return ParsedRef(m.start(), m.end(), m.group(0), rtype, dvid, tcpn, status)

    def _in_body(m: re.Match) -> bool:
        return m.start() >= body_offset  # 跳过面包屑前缀里的条号

    # R3 绝对条款(条头自指跳过)
    for m in _R3.finditer(text):
        if not _in_body(m):
            continue
        base, ins = m.group(1), m.group(2)
        try:
            cn = normalize_clause_no(f"{base}之{ins}" if ins else base)
        except ValueError:
            continue
        if cn == self_tail:  # body 起始条头 = 当前条(非引用)
            continue
        match = next((n for n in sorted(doc_clause_norms) if _tail(n) == cn), None)
        refs.append(_mk(m, "R3", match, "resolved" if match else "unresolved"))

    # R1 文档自指 / 本条 / 本章
    for m in filter(_in_body, _R1_DOC.finditer(text)):
        refs.append(_mk(m, "R1", None, "resolved"))
    for m in filter(_in_body, _R1_TIAO.finditer(text)):
        st = "resolved" if clause_path_norm else "unresolved"
        refs.append(_mk(m, "R1", clause_path_norm, st))
    cpn = clause_path_norm
    zhang = cpn.split("/")[0] if cpn and "/" in cpn else None  # 本章 = path 首段(有章时)
    for m in filter(_in_body, _R1_ZHANG.finditer(text)):
        refs.append(_mk(m, "R1", zhang, "resolved" if zhang else "unresolved"))

    # R2 前条(文档序前一条;首条无前条 → unresolved)
    for m in filter(_in_body, _R2_TIAO.finditer(text)):
        prev = None
        if clause_path_norm in doc_order:
            i = doc_order.index(clause_path_norm)
            prev = doc_order[i - 1] if i > 0 else None
        refs.append(_mk(m, "R2", prev, "resolved" if prev else "unresolved"))

    # R2 前款/上述各款:chunk 级无款边界 → 保守 unresolved 计数(§6.7 首款 UNRESOLVED 扩展)
    for m in filter(_in_body, _R2_KUAN.finditer(text)):
        refs.append(_mk(m, "R2", None, "unresolved"))

    return sorted(refs, key=lambda r: r.span_start)


# ── 集成:写 clause_references(standoff;method=rule)──────────────────────────
@dataclass(frozen=True)
class ResolverResult:
    dvid: str
    refs: int  # 写入引用行数
    chunks: int  # 受检条文 chunk 数


def clear_refs(ctx: StageContext, dvid: str) -> int:
    """删该 dvid 的 clause_references(幂等重打;须在 s3 删 chunk 前调,避 chunk_id 外键)。"""
    with ctx.db.session() as s:
        res = s.execute(delete(ClauseReference).where(ClauseReference.doc_version_id == dvid))
        return res.rowcount or 0


def run_resolver(ctx: StageContext, dvid: str) -> ResolverResult:
    """对该 dvid 的条文 chunk 跑 R1–R3 解析,写 clause_references(先 clear 保幂等)。

    选块:非 parent 非 table(= 条文块)。``body_offset`` = 面包屑长度 + 1(跳过前缀里的条号)。
    """
    clear_refs(ctx, dvid)
    with ctx.db.session() as s:
        chunks = list(s.scalars(select(Chunk).where(Chunk.doc_version_id == dvid)))
    # 仅条文块(chunk_type=clause):排除父块 + P-CASE/P-QA 的 case_section/case_summary/qa 块——
    # 后者的「第X条」是引用外规(走 case_ref_align/R4),非文档内自指,不应写同文档 clause_reference。
    clause_chunks = [c for c in chunks if c.chunk_type == "clause" and not c.is_parent]
    norms = frozenset(c.clause_path_norm for c in clause_chunks if c.clause_path_norm)
    ordered = sorted(clause_chunks, key=lambda c: c.seq)
    order = list(dict.fromkeys(c.clause_path_norm for c in ordered if c.clause_path_norm))

    rows: list[ClauseReference] = []
    for c in clause_chunks:
        offset = (len(c.breadcrumb) + 1) if c.breadcrumb else 0  # text = breadcrumb + "\n" + body
        for r in resolve_refs(c.text or "", offset, c.clause_path_norm, norms, order, dvid):
            rows.append(
                ClauseReference(
                    chunk_id=c.chunk_id,
                    doc_version_id=dvid,
                    span_start=r.span_start,
                    span_end=r.span_end,
                    surface_text=r.surface_text[:256],
                    ref_type=r.ref_type,
                    target_doc_version_id=r.target_doc_version_id,
                    target_clause_path_norm=r.target_clause_path_norm,
                    resolution_status=r.resolution_status,
                    method="rule",
                )
            )
    with ctx.db.session() as s:
        s.add_all(rows)
    return ResolverResult(dvid=dvid, refs=len(rows), chunks=len(clause_chunks))
