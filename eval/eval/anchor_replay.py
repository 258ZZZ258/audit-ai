"""T4 锚点回放(V3):逐 chunk 验其文本可在**原件页**(窗口内)定位,证明四级锚点可回放。

每非 parent chunk:取原件页文本(docx→rendition,pdf→raw;**复用 `rendition.page_texts`**,
与 page_align 同一份文本、同样剥页眉页脚)→ 窗口 `[page_start-W .. page_end+W]`(W=config
`t4_page_window`)→ 剥面包屑得 body → 归一后精确子串,未中走 rapidfuzz `partial_ratio ≥
t4_fuzzy_threshold`(config,同 page_align 兜底)。

**is_table / degraded 豁免**:表格在 rendition 里重排、逐位匹配无意义(完整性由 QC 指标5 另管);
degraded 仅全文检索可见。**对终态无阻断权**——结果入报告(V0.1 §21.2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from common.pg_models import Chunk, DocVersion
from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.parsing.rendition import page_texts
from pipeline.stage_base import StageContext


def _norm(s: str | None) -> str:
    return strip_ws(to_halfwidth(s or ""))


def _strip_breadcrumb(c: Chunk) -> str:
    """剥去 chunk.text 的面包屑前缀,得条文 body(text = "{breadcrumb}\\n{body}")。"""
    t = c.text or ""
    return t[len(c.breadcrumb):] if c.breadcrumb and t.startswith(c.breadcrumb) else t


def _window_text(
    norm_pages: list[str], page_start: int | None, page_end: int | None, w: int
) -> str:
    """拼接 `[page_start-1-w .. page_end-1+w]`(1-based 页号 → 0-based 索引)的归一页文本。"""
    ps = page_start or 1
    pe = page_end or ps
    lo = max(0, ps - 1 - w)
    hi = min(len(norm_pages), pe + w)  # pe(1-based)→ 索引 pe-1,+w → 上界 pe+w(切片右开)
    return "".join(norm_pages[lo:hi])


def _matches(norm_body: str, window_text: str, fuzzy_threshold: int) -> bool:
    """归一 body 在窗口文本内:精确子串,或 rapidfuzz partial_ratio ≥ 阈值。空 body 不判失败。"""
    if not norm_body:
        return True
    if norm_body in window_text:
        return True
    return fuzz.partial_ratio(norm_body, window_text) >= fuzzy_threshold


@dataclass
class ReplayResult:
    passed: bool
    pass_rate: float | None  # matched / total(非豁免);total=0 → None
    total: int  # 参与回放的非豁免 chunk 数
    matched: int
    exempt: int  # is_table + degraded 豁免数
    fails: list[dict] = field(default_factory=list)  # {chunk_id, clause_path, page_start, page_end}


def _source_pages(ctx: StageContext, dv: DocVersion) -> list[str]:
    """原件页文本(归一):docx 用 rendition,pdf 用 raw;复用 page_align 同款 page_texts。"""
    key = (
        dv.rendition_object_key
        if (dv.source_format == "docx" and dv.rendition_object_key)
        else dv.raw_object_key
    )
    a = ctx.config.align
    pages = page_texts(
        ctx.object_store.root / key,
        header_band_pct=a.header_band_pct,
        footer_band_pct=a.footer_band_pct,
    )
    return [_norm(p) for p in pages]


def run_replay(ctx: StageContext, doc_version_ids: list[str]) -> ReplayResult:
    """逐 doc 逐 chunk 回放;is_table/degraded 豁免。返回通过率 + 失败明细(不阻断终态)。"""
    w = ctx.config.verify.t4_page_window
    thr = ctx.config.verify.t4_fuzzy_threshold
    total = matched = exempt = 0
    fails: list[dict] = []
    for dvid in doc_version_ids:
        dv = ctx.db.get(DocVersion, dvid)
        chunks = [c for c in ctx.db.get_chunks(dvid) if not c.is_parent]
        pages: list[str] | None = None
        for c in chunks:
            if c.is_table or c.degraded:  # T4 豁免
                exempt += 1
                continue
            total += 1
            if pages is None:  # 懒加载:仅该 doc 有非豁免块时取页
                pages = _source_pages(ctx, dv)
            body = _norm(_strip_breadcrumb(c))
            if _matches(body, _window_text(pages, c.page_start, c.page_end, w), thr):
                matched += 1
            else:
                fails.append(
                    {
                        "chunk_id": c.chunk_id, "clause_path": c.clause_path,
                        "page_start": c.page_start, "page_end": c.page_end,
                    }
                )
    return ReplayResult(
        passed=(not fails), pass_rate=(matched / total if total else None),
        total=total, matched=matched, exempt=exempt, fails=fails,
    )
