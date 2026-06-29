# Implementation Plan: 扫描件 OCR 入库路径(MinerU pipeline 后端)

> SDD 阶段 2(Plan)。依据 `SPEC_OCR.md`(已门控批准)+ **本轮 in-process API 验证结论**(§risk-first)。
> 本计划经人工批准 → `TASKS_OCR.md` → `incremental-implementation`+`test-driven-development` 逐任务 TDD → 交 Codex 复审。**本阶段只规划,不写生产代码。**

## Overview

实现既有 stub `MinerUParser`(`factory.py:43`)为 MinerU 3.4 pipeline 后端(**in-process `do_parse`**),把扫描件(无文本层 pdf + 图片 jpg/png)从 `E202` 隔离改为走 OCR 入库:MinerU `middle.json` → `IR` blocks(填真实 `ocr_conf`),挂 s1 路由(文本路径 light 不动),质检指标6 接真实置信度。**零 DB 迁移**。

## risk-first 验证结论(本轮已做,PLAN 地基)

`~/mineru-spike/verify_inproc.py`(独立 venv)实测:
- **in-process 可行**:`read_fn`(image → `images_bytes_to_pdf_bytes` → pdf bytes)→ `do_parse(output_dir, [name], pdf_bytes_list=[...], p_lang_list=['ch'], backend='pipeline', f_dump_middle_json=True, f_dump_*=False)` → 读 `*_middle.json`。拿到 27 spans + `score=0.999`,中文一致。
- **⚠️ multiprocessing 约束**:MinerU PDF 渲染用 multiprocessing(macOS spawn)。无 main guard 时子进程重跑顶层 → `_load_images_from_pdf_bytes_range` RuntimeError。**加 `if __name__=='__main__'` 守护后跑通。**

## Architecture Decisions(承 SPEC §0/§12)

- **D1**:OCR 专用后端 + 路由,light 文本路径零改动。
- **D2**:范围 = 扫描 pdf + 图片 jpg/png。
- **D3**:MinerU pipeline 后端;**in-process `do_parse`**(Q1 已验);先 `do_parse`+临时目录读 middle.json(已验证),**纯内存**(`doc_analyze`→`union_make`,免临时文件)留后续优化。
- **D4**:可选 extra `[ocr]`,默认不装;`MINERU_MODEL_SOURCE=modelscope`;集成测有 MinerU 真跑、无则 skip。
- **D5**:`ocr_conf` = `min(span scores)`;`PIPELINE_OCR_BACKEND` 默认 `none`(向后兼容)。
- **D6(新,来自验证)**:MinerU 调用须 **spawn 安全**(管线入口 / pytest 已是 `__main__` 守护或显式 set start method)。`MinerUParser` 不在 import 期触发 multiprocessing;集成测验证 pytest 进程内调用不崩。

## 依赖图(bottom-up)

```
spike middle.json fixture ──→ T1 _mineru_to_blocks(纯映射, 无 MinerU) ──→ T2 MinerUParser(in-process do_parse) ──→ T3 [ocr] extra + 门控集成测
                                                                              │
T4 make_ocr_parser + PIPELINE_OCR_BACKEND(接缝) ──────────────────────────────┼──→ T5 s1 路由 + 白名单 jpg/png ──→ T6 质检指标6 接 ocr_conf ──→ T7 端到端集成 ──→ T8 收口
```

实现顺序:**纯映射先**(spike fixture 可测,无需 MinerU)→ MinerUParser(接 in-process)→ 接缝/路由/格式 → 质检 → 集成 → 收口。

## Task List

### Phase 1:MinerU → IR 映射(纯逻辑,spike fixture 可测)

**T1 — `_mineru_to_blocks(middle: dict) -> list[Block]`**
纯映射:`pdf_info[page].para_blocks` → `Block`(type/text/page/bbox/`ocr_conf`/table)。block type→BlockType;span content 拼 text;**`ocr_conf=min(span scores)`**;bbox→BBox;page_idx+1;table HTML→`IR.Table`(TableCell rowspan/colspan,复用 `to_markdown`);`discarded_blocks` 丢弃;index 升序。
- 依赖:None(spike `middle.json` 作 fixture 入 `pipeline/tests/fixtures/`)。Size:M。
- 测试(先写失败,无 MinerU):目录页 + 表格页两 fixture → 断言 type/text/ocr_conf(min)/page/table HTML→Table/index 升序/discarded 不入。

### Phase 2:MinerUParser(in-process do_parse)

**T2 — `MinerUParser(ParserAdapter)`**
`parse(data, source_format, *, scanned_char_per_page_max)`:image(jpg/png)→`images_bytes_to_pdf_bytes(data)`,pdf→原样 → `do_parse(tmpdir, [name], [pdf_bytes], ['ch'], backend='pipeline', f_dump_middle_json=True, 其余 f_dump=False)` → 读 `*_middle.json` → `_mineru_to_blocks` → `ParseResult`。tempfile 用后清理;失败→`ParseResult(error_code)`。**D6 spawn 安全**:不在 import 期触发 mp。
- 依赖:T1。Size:M。
- 测试(集成门控,有 MinerU 真跑、无 skip):图片/扫描 pdf bytes → blocks + ocr_conf;**pytest 进程内调用不崩**(验 D6);坏 bytes → error_code。

**T3 — `[ocr]` extra + 门控基建**
`pyproject` 加 `[ocr]`(`mineru[core]`,不入默认);门控 helper(有 mineru import + 模型缓存 → 真跑,否则 skip,对齐 `PIPELINE_EMBEDDING_MODEL`);`MINERU_MODEL_SOURCE` 文档化。
- 依赖:T2。Size:S。
- 测试:无 MinerU 时集成测 skip 不报错;有则跑。

**Checkpoint A**:`_mineru_to_blocks` 纯单元全绿(无栈无 MinerU);有 MinerU 时 MinerUParser 集成绿 + pytest 内不崩;`ruff` 绿。

### Phase 3:接缝 / 路由 / 格式

**T4 — `make_ocr_parser()` + `PIPELINE_OCR_BACKEND`**
factory 加 `make_ocr_parser()`(读 `PIPELINE_OCR_BACKEND`,默认 `none`→ 不启 OCR;`mineru`→MinerUParser)。`none` 时维持现 E202 隔离(向后兼容)。
- 依赖:T2。Size:S。
- 测试:env 默认 none → OCR 关;mineru → 返回 MinerUParser;未知值报错。

**T5 — s1 路由 + 白名单 jpg/png + detect_format + SourceFormat**
s1:图片 jpg/png → OCR 后端;pdf 扫描件(light 密度<阈)+ OCR 启用 → 转 OCR 后端,否则 E202。`SourceFormat` +JPG/PNG(add-only);detect_format 识别图片 magic(`\x89PNG`/`\xff\xd8`);白名单加 jpg/png。
- 依赖:T4(+ PLAN 定位 detect_format/白名单位置)。Size:M。
- 测试:图片→OCR 路由(注入 fake OCR parser);OCR 关时扫描件仍 E202;detect_format 识别 png/jpg;白名单含 jpg/png。

**T6 — 质检指标6 接 ocr_conf**
`qc/indicators` 指标6 消费 `Block.ocr_conf`(OCR 文档 `ocr_conf≥0.85`;非 OCR None 不计)。验 OCR 件低 conf 块被指标6 反映。
- 依赖:T1/T5。Size:S。
- 测试:OCR blocks(含低 conf)→ 指标6 计算正确;非 OCR(ocr_conf=None)行为不变。

**Checkpoint B**:干净栈下扫描件/图片路由 + 白名单 + 指标6 单元绿;`light`/docx/pdf-text 路径零回归;`alembic check` 无漂移(零迁移)。

### Phase 4:集成 + 收口

**T7 — 端到端集成 + 零回归**
有 MinerU 时:ingest 一张图片 + 一份扫描 pdf → INDEXED + IR ocr_conf。无 MinerU skip。**golden 条款树 F1=1.0**(parser-swap 准入门,light 不动应保持)+ docx/pdf-text 既有集成零回归。
- 依赖:T1–T6。Size:M。
- 测试:端到端门控(skip-if-no-MinerU);golden 回归。

**T8 — 文档同步 + 全量门控**
`parsing_devlog` 加 OCR 段(in-process + multiprocessing 约束 + 映射决策);`GAP`/`RTM` §2/§4.1 翻 ✅/🟡→✅;`devlog` 阶段索引。合并前全仓 + 模型门控全量(干净栈,无 MinerU/BGE-M3 则相关 skip)。
- 依赖:T1–T7。Size:S。

**Checkpoint C(交付)**:SPEC §11 成功标准达成;commit→push→PR→交 Codex 复审。

## Risks and Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| **multiprocessing spawn 约束(D6)** | 高 | 已验证 main guard 修复;管线入口 CLI 有 `__main__`;`MinerUParser` 不在 import 期触发 mp;T2 集成测专验 pytest 进程内调用不崩;最坏回退 CLI subprocess(Q1 fallback) |
| MinerU 重依赖(torch/onnx + GB 模型) | 中 | 可选 extra `[ocr]` 不入默认;门控 skip-if-not;modelscope 源 |
| 临时文件 I/O(do_parse 写盘) | 低 | tempfile + 清理;纯内存(doc_analyze→union_make)留后续优化 |
| 表格 HTML→IR Table 解析 | 中 | 用 spike 真实表格 `middle.json` 作 fixture(T1)钉死 |
| detect_format/白名单位置未定位 | 低 | PLAN/T5 grep 定位(R4 经验:GAP 路径可能过时) |
| 真实扫描噪声(渲染图是 best-case) | 中 | 本轮验证链路 + ocr_conf;真实扫描样本鲁棒性另起一轮(SPEC Out) |
| 集成栈全局单例(query-n1 并行) | 中 | worktree 隔离;跑集成前对齐空闲 + `demo down -v && demo up`,串行 |

## Open Questions

- **纯内存 vs 临时目录**:本轮用 `do_parse`+临时目录(已验证);纯内存(`doc_analyze`→`union_make` 免写盘)留后续(标 Risk)。如门控要求本轮纯内存,T2 增 spike 验 `doc_analyze` API。
- **detect_format/白名单精确位置**:T5 前 grep 定位(未在 `s0_register.py` 命中)。

## Parallelization

- **可并行**:T1(映射,spike fixture)与 T4(make_ocr_parser 接缝)无依赖。
- **须串行**:T2 依赖 T1;T5 依赖 T4;T6/T7 依赖前序。
- 单会话按 Phase 顺序串行 TDD;**集成栈跑动须与 `feat/query-n1` 会话串行**。
