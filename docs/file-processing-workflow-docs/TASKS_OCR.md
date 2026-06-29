# Tasks: 扫描件 OCR 入库路径(MinerU pipeline 后端)

> SDD 阶段 3(Tasks)。依据 `PLAN_OCR.md`(已门控批准)。
> 每任务 TDD:**先写失败测试 → 实现 → 验证**。修复迭代只跑波及范围;合并前模型门控全量一次(干净栈)。
> **调研修订**(写 TASKS 前核实):① `s0_register.py:38 WHITELIST_FORMATS` + `:63 detect_format`(T5 落点);② **质检指标6 ocr_conf 消费逻辑(`indicators.py:146`)+ 阈值(`qc_thresholds.yaml:8 ocr_conf_min=0.85`)已就位** → T6 缩小;③ `[ocr]` extra 入 `pipeline/pyproject.toml`(embed 同位)。
> 测试文件基名全仓唯一:`test_mineru_parser` / `test_ocr_routing` / `test_ocr_e2e`。

---

## Task 1 — `_mineru_to_blocks` 映射 + spike fixture

**Description:** 纯函数把 MinerU `middle.json` 的 `pdf_info[page].para_blocks` 映射为 `IR.Block` 列表。新建 `parsing/mineru_parser.py`(映射纯函数 + 后续 T2 的 Parser 类同文件)。spike 的 page-3(目录)+ page-15(表格)`middle.json` 落 `pipeline/tests/fixtures/` 作单测 fixture。

**Acceptance criteria:**
- [ ] block type→`BlockType`(title→HEADING/text→PARAGRAPH/table→TABLE/list→LIST_ITEM);span content 拼 `text`;**`ocr_conf=min(span scores)`**;bbox→`BBox`;`page_idx`+1→`page`;`discarded_blocks` 丢弃;`index` 严格升序。
- [ ] table HTML → `IR.Table`(TableCell rowspan/colspan),`expanded_rows`/`to_markdown` 可用。
- [ ] 产物可构造 `IRDocument`(过 `_check_order` 升序校验)。

**Verification:**
- [ ] `pytest pipeline/tests/test_mineru_parser.py -q -k map`(先红后绿,**无 MinerU**):目录 fixture(27 span)+ 表格 fixture → 断言 type/text/ocr_conf(min)/page/table→Table/index 升序/discarded 不入。
- [ ] `ruff` 绿。

**Dependencies:** None(spike `middle.json` 作 fixture)
**Files:** `pipeline/pipeline/parsing/mineru_parser.py`、`pipeline/tests/test_mineru_parser.py`、`pipeline/tests/fixtures/mineru_middle_toc.json`、`.../mineru_middle_table.json`
**Scope:** M

---

## Task 2 — `MinerUParser(ParserAdapter)`(in-process do_parse)

**Description:** `parse(data, source_format, *, scanned_char_per_page_max)`:image(jpg/png)→`images_bytes_to_pdf_bytes(data)`,pdf→原样 → `do_parse(tmpdir, [name], [pdf_bytes], ['ch'], backend='pipeline', f_dump_middle_json=True, 其余 f_dump=False)` → 读 `*_middle.json` → `_mineru_to_blocks` → `ParseResult`。tempfile 用后清理;异常→`ParseResult(error_code)`。`factory.py` 的 `MinerUParser` stub 替换为本实现(import mineru 延迟到 parse 内,避免默认装载)。

**Acceptance criteria:**
- [ ] image/pdf bytes → `ParseResult(blocks=…, ok=True)`,blocks 带 `ocr_conf`。
- [ ] **D6 spawn 安全**:import 期不触发 multiprocessing;mineru import 延迟到 `parse()` 内。
- [ ] 坏 bytes / 解析失败 → `ParseResult(error_code=…)`(非阻断,走 s1 `_route_failure`)。

**Verification:**
- [ ] `pytest pipeline/tests/test_mineru_parser.py -q -k parse`(集成门控,有 MinerU+模型缓存真跑、否则 skip):图片 + 扫描 pdf bytes → blocks + ocr_conf;**pytest 进程内调用不崩**(验 D6);坏 bytes → error_code。
- [ ] `ruff` 绿。

**Dependencies:** Task 1
**Files:** `pipeline/pipeline/parsing/mineru_parser.py`、`pipeline/pipeline/parsing/factory.py`、`pipeline/tests/test_mineru_parser.py`
**Scope:** M

---

## Task 3 — `[ocr]` extra + 门控基建

**Description:** `pipeline/pyproject.toml` 加 `ocr = ["mineru[core]>=3.4"]`(不入默认,同 `[embed]` 纪律);门控 helper(mineru 可 import + 模型缓存存在 → 真跑,否则 `pytest.skip`,对齐 `PIPELINE_EMBEDDING_MODEL`);`MINERU_MODEL_SOURCE=modelscope` 文档化(README/settings 注释)。

**Acceptance criteria:**
- [ ] `[ocr]` extra 就位;默认 `pip install` 不拉 mineru。
- [ ] 门控 helper:无 MinerU 时 T2/T7 集成测 skip 不报错。

**Verification:**
- [ ] 无 MinerU 环境 `pytest pipeline/tests/test_mineru_parser.py -q` → 集成用例 skip、映射用例(T1)仍跑。
- [ ] `ruff` 绿。

**Dependencies:** Task 2
**Files:** `pipeline/pyproject.toml`、`conftest.py`(或 test helper)、`config/settings.toml`(注释)
**Scope:** S

### ✅ Checkpoint A
- [ ] T1 映射纯单元全绿(无栈无 MinerU);有 MinerU 时 T2 集成绿 + pytest 内不崩;`ruff` 绿。

---

## Task 4 — `make_ocr_parser()` + `PIPELINE_OCR_BACKEND`

**Description:** `factory.py` 加 `make_ocr_parser()`:读 `PIPELINE_OCR_BACKEND`(默认 `none`→ 返回 None/不启 OCR;`mineru`→`MinerUParser()`)。`none` 维持现 E202 隔离(向后兼容)。

**Acceptance criteria:**
- [ ] 默认(未设/`none`)→ OCR 关;`mineru` → `MinerUParser`;未知值 → 明确报错(对齐 `make_parser`)。

**Verification:**
- [ ] `pytest pipeline/tests/test_ocr_routing.py -q -k factory`:默认 none / mineru / 未知值三态。
- [ ] `ruff` 绿。

**Dependencies:** Task 2
**Files:** `pipeline/pipeline/parsing/factory.py`、`pipeline/tests/test_ocr_routing.py`
**Scope:** S

---

## Task 5 — s1 路由 + 白名单 jpg/png + detect_format + SourceFormat

**Description:** `SourceFormat` +JPG/PNG(add-only,`ir.py:18`);`detect_format` 识别图片 magic(`\x89PNG`/`\xff\xd8\xff`,`s0_register.py:63`);`WHITELIST_FORMATS` +jpg/png(`:38`)。s1 路由(`stages/s1_parse.py`):图片→OCR 后端;pdf 扫描件(light 返回 E202)+ OCR 启用 → 转 OCR 后端,否则维持 E202。

**Acceptance criteria:**
- [ ] detect_format 识别 png/jpg;`WHITELIST_FORMATS ⊇ {jpg,png}`;`SourceFormat` 含 JPG/PNG;`doc_versions.source_format` 存 jpg/png(String(8))。
- [ ] s1:图片 → OCR 后端(启用时);pdf 扫描件 + OCR 启用 → OCR,**OCR 关时仍 E202**(向后兼容)。

**Verification:**
- [ ] `pytest pipeline/tests/test_ocr_routing.py -q -k "route or whitelist or detect"`(注入 fake OCR parser,免 MinerU):图片路由 OCR / 扫描件 OCR(启用)/ E202(关)/ detect png·jpg / 白名单含 jpg·png。
- [ ] `ruff` 绿。

**Dependencies:** Task 4(+ 已定位 `s0_register.py:38/63`)
**Files:** `pipeline/pipeline/stages/s0_register.py`、`libs/common/common/ir.py`、`pipeline/pipeline/stages/s1_parse.py`、`pipeline/tests/test_ocr_routing.py`
**Scope:** M

---

## Task 6 — 质检指标6 接 ocr_conf(缩小:逻辑+阈值已就位)

**Description:** 指标6 `text_quality`(`indicators.py:146`)**已消费** `b.ocr_conf`(`ocr_conf_mean < th.ocr_conf_min=0.85 → 不通过`)。本任务仅**补强单测**(确认 OCR 文档 ocr_conf → 指标6 行为)+ 确保 OCR blocks 经 IR 进指标6(端到端在 T7)。

**Acceptance criteria:**
- [ ] 单测:带 `ocr_conf` 的 `IRDocument`(含低 conf 块,均值<0.85)→ 指标6 不通过;非 OCR(ocr_conf=None)→ 跳过 OCR 维度(现行为不变)。

**Verification:**
- [ ] `pytest pipeline/tests/test_indicators.py -q -k "text_quality or ocr"`(无栈):OCR 低 conf 不过 / 非 OCR 跳过。
- [ ] `ruff` 绿。

**Dependencies:** Task 1
**Files:** `pipeline/tests/test_indicators.py`(若覆盖不足才动 `indicators.py`,预期不动)
**Scope:** XS

### ✅ Checkpoint B
- [ ] 干净栈下 T4/T5/T6 单元绿;`light`/docx/pdf-text 路径零回归;`alembic check` 无漂移(**零迁移**)。

---

## Task 7 — 端到端集成 + 零回归

**Description:** 有 MinerU 时:`demo ingest` 一张图片 + 一份扫描 pdf(`PIPELINE_OCR_BACKEND=mineru`)→ REGISTERED…→INDEXED,IR 带 ocr_conf,指标6 用真实 ocr_conf。无 MinerU skip。**golden 条款树 F1=1.0**(parser-swap 准入门,light 不动)+ docx/pdf-text 既有集成零回归。

**Acceptance criteria:**
- [ ] 图片/扫描 pdf 端到端入库 INDEXED(OCR 启用);ocr_conf 落 IR + 指标6 消费。
- [ ] golden F1=1.0;docx/pdf-text light 集成零回归。

**Verification:**
- [ ] `pytest pipeline/tests/test_ocr_e2e.py -q`(skip-if-no-MinerU,连真栈);`pytest -k golden`。
- [ ] 干净栈与 `feat/query-n1` 串行。

**Dependencies:** Task 1–6
**Files:** `pipeline/tests/test_ocr_e2e.py`、(fixtures 复用渲染图/扫描 pdf)
**Scope:** M

---

## Task 8 — 文档同步 + 全量门控

**Description:** `parsing_devlog` 加 OCR 段(in-process do_parse + **multiprocessing spawn 约束** + min 聚合 + 映射决策);`GAP`/`RTM` §2/§4.1 扫描件 OCR ❌→✅、IR ocr_conf 纠正;`devlog` 阶段索引。合并前全仓 + 模型门控全量(干净栈;无 MinerU/BGE-M3 则相关 skip)。

**Acceptance criteria:**
- [ ] devlog/GAP/RTM 同步;`spike` 关键约束(main guard / modelscope 源)入 devlog。

**Verification:**
- [ ] 合并前全仓 `pytest -q` + 模型门控全量;`ruff check .`;`alembic check` 零漂移。

**Dependencies:** Task 1–7
**Files:** `docs/devlogs/parsing_devlog.md`、`docs/file-processing-workflow-docs/GAP.md`、`.../RTM.md`、`docs/devlog.md`
**Scope:** S

### ✅ Checkpoint C(交付)
- [ ] SPEC §11 成功标准达成;`commit → push → PR → 交 Codex 复审`。

---

## 任务依赖与并行小结

```
T1 映射 ──→ T2 Parser ──→ T3 extra ──┐
                                      ├──→(CP-A)
T4 make_ocr_parser ───────────────────┘
   └──→ T5 s1路由+白名单 ──→(CP-B)
T1 ──→ T6 指标6(缩小)
T1–T6 ──→ T7 端到端 ──→ T8 收口(CP-C)
```
- 单会话按 T1→T8 串行 TDD;T4 可与 T1/T2 并行(接缝)。
- **集成栈跑动须与 `feat/query-n1` 串行**;全程零迁移目标(一旦需迁移 → 停,Ask first)。
