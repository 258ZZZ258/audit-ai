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
