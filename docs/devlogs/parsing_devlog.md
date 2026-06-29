# 解析层 devlog(pipeline/pipeline/parsing)

**职责**:原件 → IR blocks(下游不感知后端);页码锚点机制;parser 接缝。`adapter.py`(ABC)· `light_parser.py` · `rendition.py` · `page_align.py` · `factory.py`(接缝)。

## 页码锚点 —— 唯一的真架构机制(见 SPEC《页码锚点机制》)
docx **无原生页码**,页码**不从 docx 猜**:s1 用 soffice 渲染一份 canonical PDF(页码权威),结构仍从 docx XML 抽,`page_align` 用**单调两指针**对渲染件逐页文本做精确匹配回填(rapidfuzz 兜底;miss → `page=None`,被 QC 指标 4 抓)。rendition **写一次**(`reprocess` 复用)。pdf 输入用原生页、无渲染。

## 关键决策 / 踩坑
- **`page_align` bug(L4)**:`idx = _fuzzy_find(...) or -1` 在命中偏移 0 时 `0 or -1 == -1` 误判未中 → 改**显式 None 判断**。
- **`light_parser` + `adapter`(B3)**:`ParserAdapter` 是可替换边界;docx(python-docx 按序段落+表格,page=None 待对齐)、pdf(pdfplumber 逐页 + 字符密度 <阈值判扫描件 → E202-DEMO 隔离)。
- **rendition(SP1)**:soffice 未装 → `brew install --cask libreoffice`;`soffice_bin()` 经 env `PIPELINE_SOFFICE` > PATH > mac `.app` 定位。"二进制找得到 ≠ 能渲染"→ conftest session 级探测 fixture(真渲一次,broken 则 skip 非 flaky fail)。

- **案例语料 pdfplumber 字体伪影(V16 调优)**:某些 CID 字体输出**康熙部首字形**(⽉⽇⾏⼈,U+2F00 区)致日期/正则失配 → light_parser 加**康熙部首→CJK 归一**;另当事人无前缀回退抬头行、文号跳过被引外规令号、新增「警示函/监管谈话」类型。

## 接缝(升格 Step 3b)
`ParserAdapter` ABC + `factory.make_parser()` 读 `PIPELINE_PARSER_BACKEND`(默认 `light`)→ demo 默认;`DeepDocParser`/`MinerUParser`/`PaddleOCRParser` 为 stub(`NotImplementedError` + 再集成触发:DeepDoc=parser-swap 后 golden F1=1.0;MinerU=复杂版式兜底;PaddleOCR=扫描件 OCR+GPU)。s1 两处 `LightParser()` 改走 `make_parser()`。

> 时间轴:`docs/devlog.md` 并行流 SP1、阶段 B(B3/B4)、并行流 L(L4)、升格 Step 3b。

## P0 续:扫描件 OCR 入库(MinerU pipeline 后端,2026-06-29;feat/ocr-mineru)

**背景**:扫描件(无文本层 pdf + 图片 jpg/png)从 E202 隔离改为走 OCR 入库——实现既有 stub `MinerUParser`(MinerU 3.4 pipeline 后端,in-process `do_parse` → `middle.json` → IR)。**零 DB 迁移**(`IR.ocr_conf`/`Table.to_markdown` 早就位、`source_format` String 加值、`SourceFormat`/`ErrorCode` 代码枚举)。SDD 四件 `SPEC/PLAN/TASKS_OCR` + 本段。

**risk-first spike(独立 venv `~/mineru-spike`)**:
- MinerU pipeline 后端 M2 Max 跑通(ONNX/CPU,`MINERU_MODEL_SOURCE=modelscope`);中文目录 + 复杂表格零错字;**ocr_conf 原生**(`middle.json` span `score`);表格 HTML(rowspan/colspan)。
- **PaddleOCR-GPU(GAP 原选型)在 Mac 不可行**(PaddlePaddle 仅 CPU 无 MPS);MinerU 有 MLX 后端,本轮用 pipeline(vlm-mlx 端到端 VLM 可能丢 per-block conf,质检指标6 硬依赖)。

**主要决策(why)**:
- **OCR 专用后端 + 路由,light 文本路径零改动**:扫描件/图片 → `make_ocr_parser`(`PIPELINE_OCR_BACKEND`,**默认 none 向后兼容**:扫描件仍 E202,显式 mineru 才走 OCR);docx/pdf-text 仍 light(页码锚点 + golden F1=1.0 准入门不动)。
- **in-process `do_parse`(非 CLI subprocess)**:接 `list[bytes]`,写临时目录读 `middle.json`;纯内存(`doc_analyze`→`union_make` 免写盘)留后续优化。
- **`ocr_conf` 块级 = `min(span scores)`**(质检宁严);文档级 = 块均值(`indicators.py:146` 既有,本轮零改,自动接上)。

**非显然踩坑**:
- **multiprocessing spawn 约束(D6,头号风险)**:MinerU PDF 渲染用 multiprocessing(macOS spawn)。**脚本顶层直接 `do_parse` → 子进程重跑顶层 → `_load_images_from_pdf_bytes_range` RuntimeError**(spike 实测崩,`pdf_bytes` 打印两次暴露)。修:调用栈入口须 spawn 安全(`if __name__=='__main__'`)。**pytest 进程内实测不崩**(test 函数不在模块顶层,spawn re-import 只触发 import);管线 worker 经 CLI `__main__` 守护。`MinerUParser` 的 `mineru` import 延迟到 `parse` 内(避免 import 期触发 mp + 默认装载)。
- **table block 嵌套多一层**:html 在 `block.blocks[].lines[].spans[].html`(普通块是 `block.lines[].spans[].content`);table conf 在**块级** `score`(html span 无 score)。
- **三处 GAP/PLAN 假设其实已实现**:`IR.ocr_conf` 字段、`Table.to_markdown`、指标6 ocr_conf 逻辑+阈值+单测(`test_qc.py:65`)——同 R4 的 dict_aliases/seed,实现前核实省返工。

**测试**:`test_mineru_parser`(映射 7 + parse monkeypatch 2 + 真跑门控 1)、`test_ocr_routing`(make_ocr_parser 3 + detect/whitelist/SourceFormat 5 + s1 路由 4)、`test_s1_parse`(图片 OCR 门控 1 + OCR 关 E202 真跑 1);波及范围 67 passed;golden/light 零回归;alembic 零漂移。MinerU 可选 extra `[ocr]`,默认 none,门控 skip-if-no-MinerU。**端到端真跑(图片→INDEXED + BGE-M3)需装 MinerU 的环境,留交付前(spike 已验 OCR→IR 核心,下游走统一 IR 契约)**。
