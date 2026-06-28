"""ref_resolver R1–R4:条款指代纯规则 standoff 解析(§6.7,T2.4)。

S3 条款树建成后运行的纯查表(零 LLM):扫一个 chunk 的正文,产出字面引用四类——
R1 文档自指(本办法/本条/本章)、R2 相对条款(前条;前款款级不解析)、R3 绝对条款(第十五条)、
R4 跨文档(《X办法》第N条 → ``PgXRefLookup`` 三级查 dict_aliases,四态)。``chunks.text`` 含面包屑
前缀(内含本条条号),故扫描从 ``body_offset`` 起、且跳过 body 起始的条头自指(归一条号 == 当前
条号)。R4《X》第N条 的「第N条」与 R3 重叠时归 R4(跨文档优先,run_resolver 去重)。``method`` 恒 rule。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select

from common.pg_models import Chunk, ClauseReference, DictAlias, DocVersion
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
    ref_type: str  # R1 | R2 | R3 | R4
    target_doc_version_id: str | None
    target_clause_path_norm: str | None
    resolution_status: str  # resolved | unresolved | ambiguous | pending_target


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


# ── R4 跨文档指代:《标题》(文号)?第N条? 提取(纯函数)─────────────────────────
_XREF = re.compile(
    rf"《(?P<title>[^》《]+)》"
    rf"(?:[（(](?P<docnum>[^）)]*[〔\[]\d{{4}}[〕\]][^）)]*)[）)])?"
    rf"(?:第(?P<art>[{_CN}\d]+)条(?:之(?P<ins>[{_CN}\d]+))?)?"
)


@dataclass(frozen=True)
class XRefCandidate:
    """正文里一处跨文档引用候选(R4):《标题》+ 可选文号 + 可选条号原文 + span。"""

    title: str
    doc_number: str | None
    clause_raw: str | None  # 「第十五条」/「第二十一条之一」/ None(只引文档不引条)
    span_start: int
    span_end: int
    surface_text: str


def extract_xrefs(text: str, body_offset: int) -> list[XRefCandidate]:
    """提取正文(``body_offset`` 起、跳面包屑)的跨文档引用「《标题》(文号)?第N条?」候选。

    纯提取不查表:文号/条号紧邻标题方绑定(非紧邻不绑,留作文档级)。条号归一在 align 阶段。
    """
    out: list[XRefCandidate] = []
    for m in _XREF.finditer(text):
        if m.start() < body_offset:  # 跳面包屑前缀(与 R1–R3 _in_body 同纪律)
            continue
        art, ins = m.group("art"), m.group("ins")
        clause_raw = None
        if art:
            clause_raw = f"第{art}条" + (f"之{ins}" if ins else "")
        out.append(
            XRefCandidate(
                title=m.group("title"),
                doc_number=m.group("docnum"),
                clause_raw=clause_raw,
                span_start=m.start(),
                span_end=m.end(),
                surface_text=m.group(0),
            )
        )
    return out


class XRefLookup(Protocol):
    """跨文档查询接口(R4):按文号 / 标题三级命中(生产 = PG,见 ``PgXRefLookup``)。"""

    def resolve(self, doc_number: str | None, title: str | None) -> XRefHit: ...


@dataclass(frozen=True)
class XRefHit:
    status: str  # single(唯一命中)| multiple(多命中→ambiguous)| none(未命中→pending_target)
    doc_version_id: str | None
    doc_number: str | None
    clause_norms: frozenset[str]  # 命中 doc 全 chunk 的 clause_path_norm(供超界校验)


def _xref_clause_norm(clause_raw: str) -> str | None:
    """「第十五条」/「第二十一条之一」→ 归一条号(复用 R3 正则 + normalize);无法归一 → None。"""
    m = _R3.match(clause_raw)
    if not m:
        return None
    base, ins = m.group(1), m.group(2)
    try:
        return normalize_clause_no(f"{base}之{ins}" if ins else base)
    except ValueError:
        return None


def align_xref(cand: XRefCandidate, lookup: XRefLookup) -> ParsedRef:
    """候选 → 四态 R4 ``ParsedRef``。

    multiple→ambiguous、none→pending_target(均 target 留 None,不臆测);single 时:只引文档→
    resolved(path None)、条号命中→resolved(回填 path)、条号超界/无法归一→unresolved。
    """
    hit = lookup.resolve(cand.doc_number, cand.title)

    def _ref(target: str | None, cpn: str | None, status: str) -> ParsedRef:
        return ParsedRef(
            cand.span_start, cand.span_end, cand.surface_text, "R4", target, cpn, status
        )

    if hit.status == "multiple":
        return _ref(None, None, "ambiguous")
    if hit.status == "none":
        return _ref(None, None, "pending_target")
    if not cand.clause_raw:  # 只引文档不引条 → 文档级命中
        return _ref(hit.doc_version_id, None, "resolved")
    cn = _xref_clause_norm(cand.clause_raw)
    if cn is None:  # 条号无法归一 → 未解析(目标 doc 在库)
        return _ref(hit.doc_version_id, None, "unresolved")
    match = next((n for n in sorted(hit.clause_norms) if _tail(n) == cn), None)
    return _ref(hit.doc_version_id, match, "resolved" if match else "unresolved")


class PgXRefLookup:
    """生产 R4 跨文档查询(``XRefLookup`` 实现):三级命中 effective 文档,排除 ``self_dvid``。

    ① 文号精确 ② 标题精确 ③ ``dict_aliases`` 别名(→canonical 文号/标题回查 ①/②)。
    **不限 corpus_type**(内规可引内规/外规,与案例侧限 P-EXT 有意不同);某级 ≥2 命中 → multiple。
    """

    def __init__(self, db, self_dvid: str) -> None:
        self._db = db
        self._self = self_dvid

    def _find(self, s, predicate) -> list:
        return list(
            s.scalars(
                select(DocVersion).where(
                    predicate,
                    DocVersion.version_status == "effective",
                    DocVersion.doc_version_id != self._self,
                )
            )
        )

    def _hit(self, s, rows) -> XRefHit | None:
        if not rows:
            return None
        if len(rows) >= 2:  # 多 doc 命中同文号/标题/别名 → ambiguous(不臆测)
            return XRefHit("multiple", None, None, frozenset())
        dv = rows[0]
        norms = frozenset(
            n
            for n in s.scalars(
                select(Chunk.clause_path_norm).where(
                    Chunk.doc_version_id == dv.doc_version_id,
                    Chunk.clause_path_norm.is_not(None),
                )
            )
        )
        return XRefHit("single", dv.doc_version_id, dv.doc_number, norms)

    def resolve(self, doc_number: str | None, title: str | None) -> XRefHit:
        with self._db.session() as s:
            if doc_number:
                h = self._hit(s, self._find(s, DocVersion.doc_number == doc_number))
                if h:
                    return h
            if title:
                h = self._hit(s, self._find(s, DocVersion.title == title))
                if h:
                    return h
                alias = s.get(DictAlias, title)  # 第三级:别名 → canonical 回查精确级
                if alias and alias.canonical_doc_number:
                    rows = self._find(s, DocVersion.doc_number == alias.canonical_doc_number)
                    h = self._hit(s, rows)
                    if h:
                        return h
                if alias and alias.canonical_title:
                    rows = self._find(s, DocVersion.title == alias.canonical_title)
                    h = self._hit(s, rows)
                    if h:
                        return h
            return XRefHit("none", None, None, frozenset())


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


def _to_row(r: ParsedRef, chunk_id: str, dvid: str) -> ClauseReference:
    """ParsedRef(R1–R4)→ clause_references 行(standoff;method 恒 rule;surface 截 256)。"""
    return ClauseReference(
        chunk_id=chunk_id,
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


def run_resolver(ctx: StageContext, dvid: str) -> ResolverResult:
    """对该 dvid 的条文 chunk 跑 R1–R4 解析,写 clause_references(先 clear 保幂等)。

    选块:非 parent 非 table(= 条文块)。``body_offset`` = 面包屑长度 + 1(跳过前缀里的条号)。
    R4 跨文档经 ``PgXRefLookup`` 三级查(全块共用),失败由上层 ``_safe_refs`` 非阻断包裹。
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
    lookup = PgXRefLookup(ctx.db, dvid)  # R4 跨文档:全块共用(每次 resolve 自开 session)
    for c in clause_chunks:
        offset = (len(c.breadcrumb) + 1) if c.breadcrumb else 0  # text = breadcrumb + "\n" + body
        body = c.text or ""
        xcands = extract_xrefs(body, offset)  # R4 跨文档候选(《X》第N条)
        xspans = [(x.span_start, x.span_end) for x in xcands]
        for r in resolve_refs(body, offset, c.clause_path_norm, norms, order, dvid):
            # R3「第X条」落在某 R4《X》第X条 span 内 → 归 R4(跨文档优先),不重复写文档内 ref
            if any(lo <= r.span_start and r.span_end <= hi for lo, hi in xspans):
                continue
            rows.append(_to_row(r, c.chunk_id, dvid))  # R1–R3 文档内
        for x in xcands:
            rows.append(_to_row(align_xref(x, lookup), c.chunk_id, dvid))  # R4 跨文档
    with ctx.db.session() as s:
        s.add_all(rows)
    return ResolverResult(dvid=dvid, refs=len(rows), chunks=len(clause_chunks))
