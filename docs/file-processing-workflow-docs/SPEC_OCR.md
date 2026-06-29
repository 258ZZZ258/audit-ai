# SPEC: 扫描件 OCR 入库路径(§4.1,MinerU pipeline 后端)

> SDD 阶段 1(Specify)。依据 `docs/文档处理与语料库构建_技术框架设计_v1.6.md` §4.1(生产解析栈)+ 本目录 `GAP.md` §2/P0-1 + **本轮 MinerU spike 实测结论**(见 §3)。
> 协作流程:本 SPEC 经人工批准 → `planning-and-task-breakdown`(PLAN/TASKS)→ `incremental-implementation`+`test-driven-development` 逐任务落地 → 交 Codex 复审。**本阶段只写规格,不写代码。**
> 产物落 `docs/file-processing-workflow-docs/`(`SPEC/PLAN/TASKS_OCR`)。工作树:`feat/ocr-mineru`(隔离;集成栈全局单例,跑前与并行会话串行)。

## 0. 决策记录(已与用户确认)

| # | 决策点 | 选定 | 理由 |
|---|---|---|---|
| D1 | OCR 路由架构 | **OCR 专用后端 + 路由**:default `light` 文本路径**零改动**(docx/pdf-text 走页码锚点 soffice 渲染 + page_align + golden F1=1.0 准入门);扫描件/图片 → OCR 后端 | 聚焦扫描件缺口,不动已验证的文本路径;不破 golden 准入门 |
| D2 | 本轮范围 | **扫描 pdf(无文本层)+ 图片 jpg/png** | 二者同属「扫描件 OCR」目标;图片仅需白名单/detect_format/SourceFormat 小增量 |
| D3 | OCR 后端选型 | **MinerU 3.4 pipeline 后端**(ONNX OCR) | **spike 实测**:中文零错字 + **原生 per-span `score`=ocr_conf** + 表格 HTML + 版面分类。vlm-mlx 端到端 VLM 可能丢 per-block conf(质检指标6 硬依赖),故选 pipeline |
| D4 | MinerU 依赖形态 | **可选 extra `[ocr]`**(不入默认依赖,同 `[embed]` torch 纪律);模型源 `MINERU_MODEL_SOURCE=modelscope` | 默认路径零 OCR 依赖;集成测有 MinerU 时跑、无则 skip(对齐 BGE-M3 门控,绝不联网) |
| D5 | 契约影响 | **零 DB 迁移**:`IR.ocr_conf`/`Table.to_markdown` 已就位;`SourceFormat` enum + `ErrorCode` 加成员(代码非 DB);`doc_versions.source_format` `String(8)` 存 jpg/png(加值非改型) | spike + 代码核实;add-only |

---

## 1. Objective

把扫描件(无文本层 pdf + 图片 jpg/png)从**现在的 `E202` 隔离**改为**走 OCR 入库**:实现既有 stub `MinerUParser`(`factory.py:43`)为 MinerU pipeline 后端,经 `ParserAdapter` 接缝产出 `IR` blocks(含**真实 `ocr_conf`**),挂到 s1 路由;质检指标6(`ocr_conf≥0.85`,§5.1)首次接真实置信度。

**成功 = 扫描件/图片端到端入库(REGISTERED→…→INDEXED),IR 带 ocr_conf,且 docx/pdf-text light 路径 + golden 零回归**(详见 §11)。

## 2. 范围边界(In / Out)

**In(本轮交付)**
- `MinerUParser`(实现 `factory.py:43` stub):MinerU pipeline 后端 → `IR` blocks。
- **MinerU → IR 映射**(纯函数):`middle.json`(para_blocks/spans.score/bbox/page_idx/table-HTML)→ `Block`(type/text/page/bbox/`ocr_conf`/table)。
- **s1 路由**:扫描件(pdf 密度<阈)/ 图片(jpg/png)→ OCR 后端(替换 E202 隔离);文本件仍 light。
- **白名单 + detect_format + SourceFormat** add-only:jpg/png 识别 + 入库。
- MinerU 可选 extra `[ocr]` + modelscope 源配置;门控集成测(有 MinerU 真跑、无则 skip)。
- 质检指标6 接真实 ocr_conf。

**Out(本轮不做)**
- DeepDoc(office/pdf 全要素)/ PaddleOCR / MinerU vlm-mlx 后端 —— stub 留(接缝在位)。
- docx/pdf-text 文本路径(light 不动,D1)。
- MinerU 高级要素(公式 LaTeX / 印章 / 阅读顺序重排微调)。
- 真实扫描噪声/倾斜件鲁棒性调优(本轮用项目渲染图验证链路,真实扫描样本另起)。
- `chunks.internal_refs` / 图谱 / 其它解析栈缺口。

## 3. MinerU spike 实测结论(本 SPEC 的事实地基)

本轮已做 risk-first spike(独立 venv,`mineru[core]` 3.4.0,M2 Max):
- **跑通**:pipeline 后端 ONNX/CPU,modelscope 源;模型首装 ~520s 一次性,缓存后 ~13s/页。
- **中文质量**:目录页 + 复杂中文表格页(7×11)**零错字**(score 0.97–1.0)。
- **ocr_conf ✅**:`middle.json` 每 span 带 `score`;`model.json` 每 det 带 `score` → 直接喂质检指标6。
- **版面 → IR**:`pdf_info[page].para_blocks{type:title/text/table, bbox, lines.spans{content,score,bbox}}` + `discarded_blocks`(页眉页脚)+ `page_size/page_idx`。
- **表格**:HTML `<table>`(rowspan/colspan)→ 可解析为 `IR.Table.TableCell`。

## 4. 架构 / 路由

```
s0 detect_format(magic)→ source_format ∈ {docx,pdf,xlsx,jpg,png}
   ▼
s1: make_parser()=light(默认)              图片 jpg/png ─┐
   docx → light(_docx_blocks)                            │
   pdf  → light._pdf_result                              ▼
          ├─ 有文本层 → IR blocks               OCR 后端(make_ocr_parser, PIPELINE_OCR_BACKEND)
          └─ 密度<阈(扫描件)─[OCR 启用]──────→ MinerUParser.parse → IR blocks(+ocr_conf)
                              └─[OCR 关]→ E202 隔离(现行为,向后兼容)
```

- **OCR 后端可配** `PIPELINE_OCR_BACKEND=mineru|none`,**默认 `none`**(向后兼容:扫描件仍 E202;显式开 OCR 才走 MinerU,同 LLM/E2 默认关纪律)。→ §12 Q3
- 图片(jpg/png):s1 直接路由 OCR 后端(light 不处理图片)。
- pdf 扫描件:复用 light 既有密度检测点(`light_parser.py:83`),命中且 OCR 启用 → 转 OCR 后端,否则 E202。
- 接缝:新增 `make_ocr_parser()`(对齐 `make_parser()`),`MinerUParser` 实现 `ParserAdapter`(签名不变)。

## 5. MinerU → IR 映射(核心技术)

| MinerU(middle.json) | IR `Block` | 说明 |
|---|---|---|
| `para_blocks[].type` | `BlockType` | title→HEADING / text→PARAGRAPH / table→TABLE / list→LIST_ITEM |
| `spans[].content` 聚合 | `text` | 块内 span 文本拼接 |
| `spans[].score` 聚合 | **`ocr_conf`** | 块级 = **min(span scores)** 保守(§12 Q2) |
| `bbox` | `BBox` | MinerU 坐标 → x0/y0/x1/y1 |
| `page_idx`(0-based) | `page`(1-based) | +1 |
| table HTML | `Table`(TableCell rowspan/colspan) | 解析 `<table>` → 既有 `Table`,复用 `to_markdown()` |
| `discarded_blocks` | (丢弃) | 页眉页脚不入 IR |

- 块 `index` 按 MinerU 阅读顺序严格升序(满足 `IRDocument._check_order`)。
- 映射是**纯函数**(`middle.json dict → list[Block]`),用 spike 产出的真实 `middle.json` 作单测 fixture,**无需真跑 MinerU 即可测映射**。

## 6. 调用方式 / 依赖

- **MinerU 调用**:in-process Python API vs CLI subprocess —— §12 Q1(spike 用 CLI;in-process 更适合管线但需验 API 接 bytes/路径)。
- extra `[ocr]`(pyproject):`mineru[core]`;**不入默认**。env:`PIPELINE_OCR_BACKEND`、`MINERU_MODEL_SOURCE=modelscope`、模型缓存目录。
- 集成测:有 MinerU + 模型缓存时真跑,否则 `pytest.skip`(对齐 `PIPELINE_EMBEDDING_MODEL` 门控,绝不联网下载)。

## 7. Code Style(镜像 `light_parser.py`)

- `MinerUParser(ParserAdapter)`:`parse(data, source_format, *, scanned_char_per_page_max) -> ParseResult`,与 light 同签名。
- 映射纯函数(`_mineru_to_blocks(middle: dict) -> list[Block]`)无栈可单测;OCR 调用与映射分离。
- 失败 → `ParseResult(error_code=...)`(非阻断走 s1 `_route_failure`);CJK 注释 ≤100。

## 8. Testing Strategy

- **纯单元(无 MinerU,必跑)**:`_mineru_to_blocks` 用 spike `middle.json` fixture → 断言 block type/text/`ocr_conf`(min 聚合)/page/table HTML→Table;空 discarded 不入;阅读顺序 index 升序。
- **s1 路由单元**:扫描件/图片 → OCR 后端(注入 fake OCR parser);OCR 关时扫描件仍 E202;白名单 jpg/png + detect_format 识别。
- **集成门控(有 MinerU 真跑、无则 skip)**:扫描件样本 → MinerUParser → IR + ocr_conf;端到端 ingest 一张图片/扫描 pdf → INDEXED。
- **回归**:docx/pdf-text light 路径零回归;`tests/golden` 条款树 F1=1.0(parser-swap 准入门,light 不动应保持)。
- 门控:波及范围 + 合并前全仓 + 模型门控全量(干净栈);ruff 绿。

## 9. Boundaries

- **Always**:TDD;映射/路由纯函数可单测;MinerU 可选 extra;**OCR 默认关**(向后兼容);add-only;改 `parsing/` 前已读 `parsing_devlog`;ruff;集成测按 batch_id 清理。
- **Ask first**:**任何 DB 迁移**(本轮目标零迁移);改 light 文本路径 / `make_parser` 签名;新增默认依赖;新错误码进 DB。
- **Never**:破 docx/pdf-text light 路径 + golden F1=1.0;MinerU 入默认依赖;联网下载模型(无缓存则 skip);并发跑集成栈(worktree 隔离 + 串行,跑前 `demo down -v && demo up`)。

## 10. 契约与依赖(全部已就位,预期零 DB 迁移)

| 依赖 | 位置 | 状态 |
|---|---|---|
| `ParserAdapter` ABC + `ParseResult`(error_code/ok) | `parsing/adapter.py` | ✅ 接缝在位 |
| `MinerUParser` stub | `parsing/factory.py:43` | ✅ 待实现 |
| `IR.Block.ocr_conf` / `Table.to_markdown()` | `common/ir.py:101,83` | ✅ 已就位(零 IR 迁移) |
| `SourceFormat` enum(DOCX/PDF/XLSX) | `common/ir.py:18` | 🟡 加 JPG/PNG(代码 add-only) |
| `doc_versions.source_format` `String(8)` | `pg_models.py:75` | ✅ 存 jpg/png(加值非改型,零迁移) |
| `ErrorCode`(E101/E202/E203…) | `states.py:88` | 🟡 视需加 OCR 失败码(代码非 DB) |
| s1 路由 + `_route_failure` | `stages/s1_parse.py` | ✅ 已有 E202 隔离点,改为可路由 OCR |
| detect_format / 白名单 | (PLAN 定位,grep 未命中 s0_register) | ⏳ PLAN 确认位置后加 jpg/png |

## 11. Success Criteria(具体可测)

1. `MinerUParser` 实现,扫描件/图片 → IR blocks + 真实 `ocr_conf`。
2. `_mineru_to_blocks` 映射单测(spike `middle.json` fixture)逐项绿。
3. s1 路由单测:扫描件/图片 → OCR(启用时)/ E202(关时);白名单 jpg/png 识别。
4. 集成(有 MinerU):扫描件样本端到端 → INDEXED + IR ocr_conf≥阈;无 MinerU skip。
5. **docx/pdf-text light 路径零回归 + golden 条款树 F1=1.0**。
6. 质检指标6 接真实 ocr_conf。
7. `alembic check` 无漂移(**零迁移**);`ruff` 绿;合并前全仓 + 模型门控全量通过。

## 12. 门控决策(已与用户确认 2026-06-29)

- **Q1(MinerU 调用方式)→ 定案:in-process Python API**。PLAN 第一步验 MinerU API 是否接 bytes/路径;**不行回退 CLI subprocess**。
- **Q2(ocr_conf 块级聚合)→ 定案:`min(span scores)`**。质检宁严:块内一个低分 span 即拉低块 ocr_conf,更易被指标6(`≥0.85`)拦。
- **Q3(OCR 默认开关)→ 定案:`PIPELINE_OCR_BACKEND` 默认 `none`**。向后兼容(扫描件仍 E202),显式设 `mineru` 才走 OCR,同 LLM/E2 默认关纪律。

## 13. 假设(ASSUMPTIONS — 不批即按此推进)

1. IR/PG schema 足够承载 OCR 产物,**无需 DB 迁移**(§10 已核对)。
2. 不动 docx/pdf-text light 路径、`make_parser` 签名、页码锚点机制。
3. MinerU pipeline 后端(非 vlm-mlx);modelscope 源;可选 extra 默认不装。
4. 映射单测用 spike 真实 `middle.json` fixture(不需 CI 真跑 MinerU)。
