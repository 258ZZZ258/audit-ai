"""确定性指标:对单个 PDF 跑 解析(light)→IR → 切块 → QC → L1/案例 正则抽取。

全部调管线**纯函数**,零 PG / 零 ObjectStore / 零 manifest(绕过 S0 与 stage 包装层)。
产出可 JSON 序列化的 dict;LLM 裁判由 judge.py 另挂。
"""

# ruff: noqa: E501  (工具脚本:报告/prompt 文案 CJK 密集,放宽行宽)

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

from common.ir import Block, BlockType, IRDocument, SourceFormat
from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.chunking.profile_router import build_specs
from pipeline.meta.case_extract import extract_case
from pipeline.meta.l1_rules import extract as l1_extract
from pipeline.parsing.light_parser import LightParser
from pipeline.qc.gate import evaluate

# clause-tree 单块表头识别(目标① 的补充信号);导入失败则跳过该指标。
try:
    from pipeline.chunking.clause_tree import classify_heading
except Exception:  # pragma: no cover
    classify_heading = None

_CASE_FIELDS = ("penalty_org", "doc_number", "penalty_date", "respondent", "penalty_type", "amount_wan")


def _stable_dvid(path: Path) -> str:
    return "T" + hashlib.sha1(str(path).encode()).hexdigest()[:24]


def _garbled_ratio(text: str) -> float:
    """乱码率:替换符 � + 控制字符 占比(与 QC text_quality 同口径的近似)。"""
    if not text:
        return 0.0
    bad = sum(1 for c in text if c == "�" or (unicodedata.category(c) == "Cc" and c not in "\t\n\r"))
    return round(bad / len(text), 4)


def _heading_hit_rate(blocks: list[Block]) -> float | None:
    """正文段落里被条款树正则识别为 章/节/条/款/项 的比例(目标① 结构识别度)。"""
    if classify_heading is None:
        return None
    paras = [b for b in blocks if b.type == BlockType.PARAGRAPH and b.text.strip()]
    if not paras:
        return None
    hits = 0
    for b in paras:
        try:
            if classify_heading(strip_ws(to_halfwidth(b.text))) is not None:
                hits += 1
        except Exception:
            pass
    return round(hits / len(paras), 4)


def parse_pdf(path: Path, scanned_max: int):
    """PDF → (ParseResult, IRDocument|None)。res.ok=False(扫描件/白名单外)时 ir=None。"""
    res = LightParser().parse(path.read_bytes(), "pdf", scanned_char_per_page_max=scanned_max)
    if not res.ok:
        return res, None
    ir = IRDocument(
        doc_version_id=_stable_dvid(path),
        source_format=SourceFormat.PDF,
        blocks=res.blocks,
        page_count=res.page_count,
        title=res.title,
    )
    return res, ir


def compute(path: Path, corpus_type: str, scanned_max: int, chunk_cfg, qc_th) -> dict:
    """单 PDF 全部确定性指标 → dict。三大目标共用此结构。"""
    out: dict = {
        "path": str(path),
        "name": path.name,
        "corpus_type": corpus_type,
        "pipeline_failed": False,
        "failure_reasons": [],
    }
    res, ir = parse_pdf(path, scanned_max)
    out["parse_ok"] = bool(res.ok)
    out["parse_error"] = res.error_code
    out["page_count"] = res.page_count or 0

    if not res.ok:  # 解析即失败:多为扫描件(E202)→ 直接判管线失效 + 强烈建议 DeepDoc/OCR
        out["pipeline_failed"] = True
        out["failure_reasons"].append(f"解析失败 {res.error_code}:{res.reason}")
        out["chars_total"] = 0
        out["chars_per_page"] = 0.0
        out["likely_scanned"] = (res.error_code or "").startswith("E202")
        return out

    text = "\n".join(b.text for b in ir.blocks)
    out["_text"] = text  # 供 judge.py 用;report.py 落盘时剥离(_ 前缀)
    npages = ir.page_count or 1
    out["n_blocks"] = len(ir.blocks)
    out["chars_total"] = len(text)
    out["chars_per_page"] = round(len(text) / npages, 1)
    out["title"] = ir.title

    # ── 目标②:解析质量启发式 ──────────────────────────────────────────────
    out["garbled_ratio"] = _garbled_ratio(text)
    out["likely_scanned"] = out["chars_per_page"] < scanned_max  # 残余低密度(未触 E202 但偏低)

    # ── 目标①:结构化切块 + 正则识别度 ────────────────────────────────────
    try:
        specs = build_specs(ir, corpus_type, chunk_cfg)
    except Exception as e:
        specs = []
        out["failure_reasons"].append(f"切块异常:{type(e).__name__}: {e}")
    out["n_chunks"] = len(specs)
    out["n_with_clause_path"] = sum(1 for s in specs if getattr(s, "clause_path", None))
    out["n_article_chunks"] = sum(1 for s in specs if getattr(s, "chunk_type", None) == "clause")
    out["heading_hit_rate"] = _heading_hit_rate(ir.blocks)
    if not specs:
        out["pipeline_failed"] = True
        out["failure_reasons"].append("切块产物为空(0 chunk)")

    # ── 目标①:L1 / 案例 要素正则抽取(无 manifest → 不做 cross_check)──────────
    out["extracted"], out["extract_presence"] = _extract(ir, text, corpus_type)

    # ── 目标③:QC 指标数值(按 corpus_type profile)──────────────────────────
    try:
        report = evaluate(ir, qc_th, corpus_type=corpus_type)
        out["qc"] = [
            {"key": r.key, "index": r.index, "name": r.name, "value": round(float(r.value), 4),
             "threshold": float(r.threshold), "passed": bool(r.passed), "marginal": bool(r.marginal)}
            for r in report.indicators
        ]
        out["qc_failed"] = [r["name"] for r in out["qc"] if not r["passed"]]
        if out["qc_failed"]:
            out["failure_reasons"].append("QC 未过:" + "、".join(out["qc_failed"]))
    except Exception as e:
        out["qc"] = []
        out["qc_failed"] = []
        out["failure_reasons"].append(f"QC 异常:{type(e).__name__}: {e}")
    return out


def _extract(ir: IRDocument, text: str, corpus_type: str) -> tuple[dict, dict]:
    """按类型抽要素:案例 → case_extract;其它 → l1_rules(文号/日期/标题)。返回(值, 命中布尔)。"""
    if corpus_type == "P-CASE":
        case = extract_case(text, {})
        vals = {k: case.get(k) for k in _CASE_FIELDS}
        presence = {k: case.get(k) not in (None, "", []) for k in _CASE_FIELDS}
        return vals, presence
    meta = l1_extract(ir, [])
    vals = {
        "doc_numbers": list(meta.doc_numbers),
        "dates": [d.isoformat() for d in meta.dates],
        "title": meta.title,
    }
    presence = {"doc_number": bool(meta.doc_numbers), "date": bool(meta.dates), "title": bool(meta.title)}
    return vals, presence
