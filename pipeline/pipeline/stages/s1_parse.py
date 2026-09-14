"""S1 解析:渲染件生成(写一次,reprocess 复用)→ light 抽结构 → 文本对齐回填页码 → IR 落库。

两个 stage 入口(均经 orchestrator 按当前态调用):
- ``start``:REGISTERED → PARSING,登记后认领解析的薄 stage(纯状态翻转,见下方说明);
- ``run``:PARSING → QC_PENDING,实际解析。

docx:soffice 渲染为规范 PDF(页码权威)→ python-docx 抽结构 → page_align 回填;
渲染失败 → PARSE_FAILED(E204-DEMO)。
pdf:pdfplumber 直接抽(页码原生);扫描件(字符密度 <阈值)→ QUARANTINED(E202-DEMO)。
白名单外格式 → QUARANTINED(E101-DEMO,通常 s0 已先拦)。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from common.ir import Block, BlockType, IRDocument, SourceFormat
from common.pg_models import Document, DocVersion
from pipeline.parsing.adapter import ParseResult
from pipeline.parsing.factory import make_ocr_parser, make_parser
from pipeline.parsing.page_align import align_blocks
from pipeline.parsing.rendition import page_texts, render_pdf
from pipeline.stage_base import QueueItem, QueueType, StageContext, StageResult
from pipeline.states import ErrorCode, PipelineState


def start(ctx: StageContext, doc_version_id: str) -> StageResult:  # noqa: ARG001 (统一 stage 签名)
    """REGISTERED → PARSING:登记后认领解析的薄 stage,纯状态翻转,不读不写。

    ``run`` 建模 PARSING → QC_PENDING,故需要本 stage 先把 REGISTERED 推进到 PARSING
    (迁移表无 REGISTERED → QC_PENDING)。起始时间已由 orchestrator 写入 pipeline_events,
    无需再挂 DocVersion。PARSING 因此是落库的"解析中"态:worker 崩在 ``run`` 中途时文档停在
    PARSING,重启后被重新轮询并重跑 ``run``(渲染件写一次 + IR 覆盖,天然幂等)。
    """
    return StageResult(next_state=PipelineState.PARSING)


def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    dv = ctx.db.get(DocVersion, doc_version_id)
    data = ctx.object_store.get(dv.raw_object_key)
    if dv.source_format == "preseg":  # P-PRESEG:解析退化为装载(CP-010 T6)
        return _load_preseg(ctx, doc_version_id, dv, data)
    if dv.source_format == "docx":
        return _parse_docx(ctx, doc_version_id, data)
    if dv.source_format == "pdf":
        return _parse_pdf(ctx, doc_version_id, data)
    if dv.source_format in ("jpg", "png"):
        return _parse_image(ctx, doc_version_id, data, dv.source_format)
    return _quarantine(doc_version_id, ErrorCode.FORMAT_NOT_WHITELISTED.value,
                       f"白名单外格式 {dv.source_format}")


def _load_preseg(
    ctx: StageContext, dvid: str, dv: DocVersion, data: bytes
) -> StageResult:
    """P-PRESEG 装载:raw(blocks JSONL / 案例记录 JSON)→ 合成 IR → QC_PENDING。

    IR 契约保真(每源块一 paragraph Block,page=None),下游 S2 零感知;此 IR **只服务 QC**
    (⑥文本质量哨兵,D10)——S3 的 preseg_adapter 直接消费 raw 块流(clause_label 全保真,
    IR 不承载,T7)。案例虚拟文档(D4)以 case_name/问题汇总/案例描述合成文本块,使跨库
    charset 损坏同样被 ⑥ 拦住。契约违约本应 S0 已拦,此处兜底隔离。
    """
    import json as _json

    from pipeline.preseg.reader import PresegFormatError, parse_blocks

    doc = ctx.db.get(Document, dv.logical_id) if dv.logical_id else None
    try:
        if doc is not None and doc.corpus_type == "P-CASE":  # 案例记录 JSON(虚拟文档)
            rec = _json.loads(data.decode("utf-8"))
            texts = [t for t in (rec.get("case_name"), rec.get("problem_summary"),
                                 rec.get("description")) if t]
        else:  # blocks JSONL
            blocks = parse_blocks(data.decode("utf-8"), dv.source_filename or dvid)
            texts = [b.text for b in blocks]
    except (PresegFormatError, UnicodeDecodeError, ValueError) as e:
        return _quarantine(dvid, None, f"preseg 装载失败:{e}")

    ir = IRDocument(
        doc_version_id=dvid,
        source_format=SourceFormat.PRESEG,
        title=dv.title,
        blocks=[
            Block(index=i, type=BlockType.PARAGRAPH, text=t, page=None)
            for i, t in enumerate(texts)
        ],
    )
    ctx.object_store.put_ir(ir)
    return StageResult(next_state=PipelineState.QC_PENDING)


def _parse_docx(ctx: StageContext, dvid: str, data: bytes) -> StageResult:
    cfg, store = ctx.config, ctx.object_store
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        if store.exists_rendition(dvid):  # 写一次:已有渲染件则复用,不重渲
            rpdf = tmpd / "rend.pdf"
            rpdf.write_bytes(store.get_rendition(dvid))
        else:
            src = tmpd / "src.docx"
            src.write_bytes(data)
            try:
                rpdf = render_pdf(src, tmpd, timeout=cfg.parse.parse_timeout_sec)
            except Exception as e:  # soffice 失败/超时
                return _fail(dvid, ErrorCode.RENDITION_FAILED.value, f"渲染失败: {e}")
            store.put_rendition(dvid, rpdf.read_bytes())

        res = make_parser().parse(
            data, "docx", scanned_char_per_page_max=cfg.parse.scanned_char_per_page_max
        )
        if not res.ok:
            return _route_failure(dvid, res)
        pages = page_texts(
            rpdf,
            header_band_pct=cfg.align.header_band_pct,
            footer_band_pct=cfg.align.footer_band_pct,
        )
        blocks = align_blocks(res.blocks, pages, fuzzy_threshold=cfg.align.fuzzy_threshold)
        ir = IRDocument(
            doc_version_id=dvid, source_format=SourceFormat.DOCX,
            blocks=blocks, page_count=len(pages), title=res.title,
        )
    store.put_ir(ir)
    _record_artifacts(ctx, dvid, rendition=True)
    return StageResult(next_state=PipelineState.QC_PENDING, artifacts={"ir": store.ir_key(dvid)})


def _parse_pdf(ctx: StageContext, dvid: str, data: bytes) -> StageResult:
    smax = ctx.config.parse.scanned_char_per_page_max
    res = make_parser().parse(data, "pdf", scanned_char_per_page_max=smax)
    if res.ok:
        return _ir_to_qc(ctx, dvid, res, "pdf")
    # 扫描件(无文本层或整页图像附带旧文字层) → OCR;未启用时仍隔离。
    if res.error_code == ErrorCode.SCANNED_OCR_DISABLED.value:
        ocr = make_ocr_parser()
        if ocr is not None:
            ores = ocr.parse(data, "pdf", scanned_char_per_page_max=smax)
            return _ir_to_qc(ctx, dvid, ores, "pdf") if ores.ok else _route_failure(dvid, ores)
    return _route_failure(dvid, res)


def _parse_image(ctx: StageContext, dvid: str, data: bytes, source_format: str) -> StageResult:
    """图片(jpg/png)→ OCR 后端;OCR 关 → E202 隔离(与扫描 pdf 同口径)。"""
    smax = ctx.config.parse.scanned_char_per_page_max
    ocr = make_ocr_parser()
    if ocr is None:
        return _quarantine(
            dvid, ErrorCode.SCANNED_OCR_DISABLED.value,
            f"{source_format} 图片需 OCR,PIPELINE_OCR_BACKEND 未启用",
        )
    res = ocr.parse(data, source_format, scanned_char_per_page_max=smax)
    return _ir_to_qc(ctx, dvid, res, source_format) if res.ok else _route_failure(dvid, res)


def _ir_to_qc(ctx: StageContext, dvid: str, res: ParseResult, source_format: str) -> StageResult:
    """解析成功 → 构造 IR(无 docx 页码对齐)落库 → QC_PENDING(pdf / 图片共用)。"""
    store = ctx.object_store
    ir = IRDocument(
        doc_version_id=dvid, source_format=SourceFormat(source_format),
        blocks=res.blocks, page_count=res.page_count, title=res.title,
    )
    store.put_ir(ir)
    _record_artifacts(ctx, dvid, rendition=False)
    return StageResult(next_state=PipelineState.QC_PENDING, artifacts={"ir": store.ir_key(dvid)})


def _route_failure(dvid: str, res: ParseResult) -> StageResult:
    quarantine_codes = {
        ErrorCode.SCANNED_OCR_DISABLED.value,
        ErrorCode.FORMAT_NOT_WHITELISTED.value,
    }
    if res.error_code in quarantine_codes:
        return _quarantine(dvid, res.error_code, res.reason)
    return _fail(dvid, res.error_code or ErrorCode.PARSE_TIMEOUT.value, res.reason)


def _quarantine(dvid: str, ecode: str, reason: str) -> StageResult:
    return StageResult(
        next_state=PipelineState.QUARANTINED, error_code=ecode, evidence={"reason": reason},
        queue=QueueItem(QueueType.QUARANTINE, dvid, reason, {"error_code": ecode}),
    )


def _fail(dvid: str, ecode: str, reason: str) -> StageResult:
    return StageResult(
        next_state=PipelineState.PARSE_FAILED, error_code=ecode, evidence={"reason": reason},
        queue=QueueItem(QueueType.QC_FIX, dvid, reason, {"error_code": ecode}),
    )


def _record_artifacts(ctx: StageContext, dvid: str, *, rendition: bool) -> None:
    with ctx.db.session() as s:
        dv = s.get(DocVersion, dvid)
        dv.ir_object_key = ctx.object_store.ir_key(dvid)
        if rendition:
            dv.rendition_object_key = ctx.object_store.rendition_key(dvid)
