# TASKS_P0:文档处理管线 v1.6 — P0 缺口落地(可执行任务)

> SDD 阶段 3(Tasks)。依据 `SPEC_P0.md` + `PLAN_P0.md` 依赖图。每任务一焦点会话内可完成、≤~5 文件、带验收 + 验证。
> 落地走 `incremental-implementation` + `test-driven-development`(先写失败测试)。交 Codex 复审。
> 全局约定:测试文件基名**全仓唯一**;迁移 add-only(autogenerate→upgrade→`alembic check` 无漂移 + 纳 lint);LLM key 仅 env;CJK 注释独立行防超行宽 100;修复迭代只跑波及范围,合并前全量门控跑一次(无库/无 GPU/无 key 项 skip)。
> 图例:Scope S(1–2 文件)/ M(3–5)/ L(5–8)。流 A/B/C/F。

---

## Phase 0 — Foundation(并行)

### Task T0.1 (F):迁移 0009 + 字典/列 + seeds
**Description:** 为 B2/B3/C2 建共享 add-only schema:两张字典表 + 业务域多值列,并灌 v0-draft 种子。
**Acceptance criteria:**
- [ ] `pg_models.py` 新增 `DictViolationType(code PK, name, dict_version, AuditMixin)` 与 `DictAlias(id PK, alias, canonical_doc, dict_version, AuditMixin)`;`DocVersion` +`biz_domains`(JSONB,nullable)+`biz_domain_source`(String(16),nullable)。**原 `biz_domain` 单值列保留不删**。
- [ ] `seeds/dict_violation_types.csv`(样例聚类 v0-draft,`dict_version=v0-draft-2026-06`)+ `seeds/dict_aliases.csv`(别名起点)随 `demo up` seed 入库。
- [ ] 迁移 `0009_dict_violation_aliases_bizdomains.py`:autogenerate → `alembic upgrade head` → `alembic check` 无漂移。
**Verification:** `alembic upgrade head && alembic check`;`ruff check --fix alembic/versions && ruff format alembic/versions`;`pytest pipeline/tests/test_seeds_p0.py`(seed 行数/dict_version)。
**Dependencies:** None
**Files:** `libs/common/common/pg_models.py`、`alembic/versions/0009_*.py`、`seeds/dict_violation_types.csv`、`seeds/dict_aliases.csv`、`pipeline/tests/test_seeds_p0.py`
**Estimated scope:** M

### Task T0.2 (A):IR `ocr_conf` + 表格 markdown 序列化
**Description:** IR 契约 add-only 加块级 `ocr_conf`;`Table` 加 markdown 序列化(合并单元格按 rowspan/colspan 展开补值);切块表格块改用它;QC 指标 6 接 `ocr_conf`(有值才参与)。
**Acceptance criteria:**
- [ ] `ir.py` `Block` +`ocr_conf: float | None = None`(`extra="forbid"` 下 add-only,校验器不破);`Table` 加 `to_markdown()`(rowspan/colspan 展开补值)。
- [ ] `chunker._table_segments` 用 `to_markdown()` 替代当前简单行列化。
- [ ] `qc/indicators.py` 指标 6 在 block 带 `ocr_conf` 时计均值校验(≥0.85),None 不计入。
- [ ] `test_ir`/`test_v16_fidelity` 更新通过;新增 `test_table_markdown`(合并单元格展开)+ `test_ir_ocr_conf`(字段 add-only)。
**Verification:** `pytest libs/common/tests/test_ir.py libs/common/tests/test_v16_fidelity.py pipeline/tests/test_table_markdown.py pipeline/tests/test_ir_ocr_conf.py pipeline/tests/test_qc.py`
**Dependencies:** None
**Files:** `libs/common/common/ir.py`、`pipeline/pipeline/chunking/chunker.py`、`pipeline/pipeline/qc/indicators.py`、`pipeline/tests/test_table_markdown.py`、`pipeline/tests/test_ir_ocr_conf.py`
**Estimated scope:** M

> **Checkpoint 0:** `alembic check` 无漂移;`ruff` 净;IR/契约测全绿;现 374 不破。→ 人工 review 后进 Phase 1。

---

## Phase 1 — 纯逻辑 + 真链路 fail-fast(高并行)

### Task T1.1 (B/B4):E2 接真模型打通
**Description:** E2 接缝已完整;本任务打通 `e2_enabled=true` 端到端 + 真 seed 上 dict PG 加载验证 + 真模型门控集成测(验证 D2 模式,供后续 LLM 任务复用)。
**Acceptance criteria:**
- [ ] 干净栈 + `e2_enabled=true`:`run_e2` 产 `clause_tags` 的 entity_type/department/matter 行,且经 `_enforce` 字典裁剪(LLM 越界值被丢)。
- [ ] 真模型门控集成测:有 `OPENAI_API_KEY` → 真 LLM 跑通并落库;无 key → `skip`(绝不联网)。
- [ ] 现 `test_e2_tag` 单测保持;非阻断覆盖(LLMError 经 `_safe_e2` 不改 `pipeline_status`)。
**Verification:** `pytest pipeline/tests/test_e2_tag.py`;`OPENAI_API_KEY=<k> OPENAI_BASE_URL=<u> pytest pipeline/tests/test_e2_tag.py -k integration`
**Dependencies:** None(dicts 已 seed)
**Files:** `pipeline/pipeline/enrich/e2_tag.py`(校验/微调)、`pipeline/tests/test_e2_tag.py`、`config/settings.toml`(注释)
**Estimated scope:** S–M

### Task T1.2 (B/B1a):`case_ref_align` 纯对齐
**Description:** 纯逻辑把"《X》第N条"引用对齐到 `doc_no` + `clause_path_norm`;三级匹配(文号精确 → 标题精确 →〔别名留 T2.4〕)→ `clause_path_norm`(复用 `normalize`);超界/未命中 → unresolved。
**Acceptance criteria:**
- [ ] `case_ref_align.align(cited, lookup)` 纯函数:文号精确 → doc_version;标题精确兜底;条号经 `normalize` → `clause_path_norm`;超界/未命中标 `resolved=False`。
- [ ] 返回 `[{doc_no, clause_path_norm, resolved}]` + 聚合 `ref_unresolved`(任一未命中即 True)。
- [ ] `test_case_ref_align`:文号/标题/条号命中 + 超界→unresolved + 空输入,**纯逻辑无模型/无栈**。
**Verification:** `pytest pipeline/tests/test_case_ref_align.py`
**Dependencies:** None
**Files:** `pipeline/pipeline/meta/case_ref_align.py`、`pipeline/tests/test_case_ref_align.py`
**Estimated scope:** M

### Task T1.3 (C/C1):`ref_resolver` R1–R3 + 写 `clause_references`
**Description:** S3 后纯规则解析文档内指代(R1 自指 / R2 相对 / R3 绝对),standoff 写 `clause_references`(`method=rule`)。
**Acceptance criteria:**
- [ ] `ref_resolver.resolve(chunks, tree, doc_meta)`:四类最长匹配优先、复合("本办法第十五条第二款")整体匹配;R2 首款命中 → UNRESOLVED 计数;R3 复用 `normalize` 查 `clause_path_norm`。
- [ ] standoff:`chunks.text` 不改;结果写 `clause_references`(span/surface_text/ref_type/target_clause_path_norm/resolution_status/`method="rule"`)。
- [ ] 从 `s3_structure.run` 在 `replace_chunks` 后触发;非阻断(异常不改状态)。
- [ ] `test_ref_resolver`:R1/R2/R3 模式 + UNRESOLVED 计数(纯逻辑);栈集成验 `clause_references` 写入。
**Verification:** `pytest pipeline/tests/test_ref_resolver.py`;栈集成(栈起时)
**Dependencies:** None(表已建 0008)
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`、`pipeline/pipeline/stages/s3_structure.py`(hook)、`pipeline/tests/test_ref_resolver.py`
**Estimated scope:** M

### Task T1.4 (C/C3):`ref_render` 窗口渲染原语
**Description:** 窗口渲染:按 span **倒序**插注释(防偏移)、gloss≤30、UNRESOLVED/ambiguous 不渲染。
**Acceptance criteria:**
- [ ] `ref_render.render(text, refs)` 倒序插注释;gloss>30 截断;`resolution_status ∈ {unresolved, ambiguous}` 不渲染。
- [ ] 纯逻辑;`test_ref_render`:倒序不偏移 + UNRESOLVED 不渲染 + gloss 截断。
**Verification:** `pytest pipeline/tests/test_ref_render.py`
**Dependencies:** None
**Files:** `pipeline/pipeline/chunking/ref_render.py`、`pipeline/tests/test_ref_render.py`
**Estimated scope:** S

### Task T1.5 (A/A1):xlsx 直读 + 白名单含 xlsx
**Description:** light parser 加 xlsx 分支(openpyxl):每 sheet → `Table` block → IR;`SourceFormat` 加 xlsx(add-only);白名单含 xlsx。
**Acceptance criteria:**
- [ ] `ir.py` `SourceFormat` +`XLSX="xlsx"`(add-only);`light_parser` xlsx 分支用 openpyxl 产 `Table` block(cells row/col)。
- [ ] `WHITELIST_FORMATS` += xlsx;`detect_format` 识别 xlsx(zip/`xl/` 魔数)。
- [ ] `test_xlsx_parse`:简单 xlsx → `chunk_type=table` 块入库。
**Verification:** `pytest pipeline/tests/test_xlsx_parse.py pipeline/tests/test_s0_register.py`
**Dependencies:** T0.2(`to_markdown` 辅助)
**Files:** `pipeline/pipeline/parsing/light_parser.py`、`libs/common/common/ir.py`、`pipeline/pipeline/stages/s0_register.py`、`pipeline/tests/test_xlsx_parse.py`
**Estimated scope:** M

> **Checkpoint 1:** 纯逻辑测全绿;B4 真链路有 key 真跑 / 无 key skip;`clause_references` 在 R1–R3 有 resolved 行;xlsx 可入库。→ 人工 review。

---

## Phase 2 — 功能构建(依赖 Foundation)

### Task T2.1 (B/B1b):案例引用外规 LLM 抽取 + 接对齐(最高价值)
**Description:** `case_l2.extract_cited` LLM 抽"依据《X》第N条" → 接 T1.2 `align` → 写 `cases.cited_regulations`;miss → `ref_unresolved`。镜像 e2 纪律,默认关。
**Acceptance criteria:**
- [ ] `case_l2.extract_cited(client, case_text)` → `[{title, doc_no?, clause?}]`(`chat_json`,prompt 强制只输出 JSON、不臆测)。
- [ ] 装配:extract → `case_ref_align.align` → `cases.cited_regulations`(JSONB)+ `ref_unresolved`;align miss **不阻塞案例入库**。
- [ ] `test_case_l2` fake-LLM 抽取形态 + 真模型门控集成;`case_l2_enabled` 默认关;非阻断。
**Verification:** `pytest pipeline/tests/test_case_l2.py`;门控 `OPENAI_API_KEY=<k> pytest -k integration`
**Dependencies:** T1.1(模式)、T1.2(align)
**Files:** `pipeline/pipeline/meta/case_l2.py`、`pipeline/pipeline/stages/s4_meta.py`(装配)、`config/settings.toml`、`pipeline/tests/test_case_l2.py`
**Estimated scope:** M

### Task T2.2 (B/B2):违规事由分类 + dict_violation_types
**Description:** `case_l2.classify_violation` 约束 `dict_violation_types` + server-side `_enforce` → `cases.violation_category`;空/未命中留 None(consumed-when-present)。
**Acceptance criteria:**
- [ ] `classify_violation(client, case_text, allowed)`:LLM + `_enforce` 裁字典;字典空/未命中 → None。
- [ ] `dict_violation_types` 从 PG 加载;`dict_version` 记入(evidence/字段)。
- [ ] `test_case_l2`(违规事由分支)fake-LLM + `_enforce` 裁剪 + 空降级。
**Verification:** `pytest pipeline/tests/test_case_l2.py`
**Dependencies:** T0.1、T1.1
**Files:** `pipeline/pipeline/meta/case_l2.py`(classify)、`pipeline/tests/test_case_l2.py`
**Estimated scope:** M

### Task T2.3a (B/B3):业务域 L2 打标 + 写权威字段
**Description:** `l2_llm.tag_biz_domain` 约束 `dict_biz_domains` + `_enforce` → 写 `doc_versions.biz_domains` + `biz_domain_source=llm` + `ai_label`。
**Acceptance criteria:**
- [ ] `l2_llm.tag_biz_domain(client, doc_text, allowed_biz)`:LLM + `_enforce` → 多值。
- [ ] 写 `doc_versions.biz_domains`(JSONB)+ `biz_domain_source="llm"`;记 `dict_version`。
- [ ] `test_l2_llm` fake-LLM + 字典裁剪 + source 标志;`l2_enabled` 默认关。
**Verification:** `pytest pipeline/tests/test_l2_llm.py`
**Dependencies:** T0.1
**Files:** `pipeline/pipeline/meta/l2_llm.py`、`config/settings.toml`、`pipeline/tests/test_l2_llm.py`
**Estimated scope:** M

### Task T2.3b (B/B3):业务域 profile 分档确认 + 下游取值
**Description:** P-INT 逐件入 META_REVIEW(→`confirmed`);P-EXT/QA/CASE LLM 直落 + 抽样;manifest 优先/冲突路径;chunks/Milvus `biz_domain` ARRAY 从 `biz_domains` 取(向后兼容原单值)。
**Acceptance criteria:**
- [ ] `s4_meta`:P-INT 业务域候选入 META_REVIEW(`auto_confirm` 不放行);P-EXT/QA/CASE `source=llm` 直落生效;按 profile `sampling_rate` 抽样。
- [ ] manifest 已给业务域 → 优先;冲突 → META_REVIEW(§7.1 交叉校验)。
- [ ] `corpus_rows`/s5:Milvus `biz_domain` ARRAY 从 `doc_versions.biz_domains` 取;`biz_domains` 空则回落原单值 `biz_domain`。
- [ ] 集成测(栈):三档行为 + 下游取值。
**Verification:** `pytest pipeline/tests/test_s4_meta.py pipeline/tests/test_search_meta.py`;栈集成
**Dependencies:** T2.3a
**Files:** `pipeline/pipeline/stages/s4_meta.py`、`pipeline/pipeline/index/corpus_rows.py`、`pipeline/tests/test_s4_meta.py`
**Estimated scope:** M

### Task T2.4 (C/C2):R4 跨文档 + dict_aliases + pending_target
**Description:** R4`《…》(〔YYYY〕N号)?(第X条)?` 三级匹配(文号/标题/`dict_aliases`);miss → `pending_target`;夜间重试;永久未解析 → 语料缺口清单。
**Acceptance criteria:**
- [ ] `ref_resolver` R4:文号精确 → 标题精确 → `dict_aliases`;均未命中 → `resolution_status="pending_target"`。
- [ ] `dict_aliases` 从 PG 加载(T0.1);夜间重试任务/CLI hook 重解 pending_target。
- [ ] 永久未解析导出缺口清单(列表产物)。
- [ ] `test_ref_resolver`(R4 分支):三级匹配 + pending_target。
**Verification:** `pytest pipeline/tests/test_ref_resolver.py`
**Dependencies:** T0.1、T1.3
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`(R4)、夜间重试 hook、`pipeline/tests/test_ref_resolver.py`
**Estimated scope:** M

### Task T2.5 (A/A3):白名单 jpg/png + 路由表 format→backend
**Description:** magic number 加 jpg/png/xlsx;factory 路由 format→backend;jpg/png 无 OCR 后端时 → QUARANTINED(不静默丢)。
**Acceptance criteria:**
- [ ] `detect_format` 识别 jpg/png/xlsx;`WHITELIST` += jpg/png(xlsx 见 T1.5)。
- [ ] factory 路由:docx/pdf-text→light/deepdoc;pdf-notext/jpg/png→paddleocr;失败→mineru。
- [ ] jpg/png + 默认 light(无 OCR)→ E202/QUARANTINED,不崩。
- [ ] `test_s0_register` 扩格式 + `test_parser_routing`(format→backend 表)。
**Verification:** `pytest pipeline/tests/test_s0_register.py pipeline/tests/test_parser_routing.py`
**Dependencies:** T0.2、T1.5
**Files:** `pipeline/pipeline/parsing/factory.py`、`pipeline/pipeline/stages/s0_register.py`、`pipeline/tests/test_parser_routing.py`
**Estimated scope:** S–M

> **Checkpoint 2:** B 四项端到端(fake + 门控真);业务域三档 + 下游取值;ref_resolver R1–R4 完整;路由覆盖全格式且 jpg/png 无 OCR 时隔离不崩。→ 人工 review。

---

## Phase 3 — 门控真后端(真验收甲方信创/GPU 环境)

### Task T3.1 (A/A4):DeepDoc 真后端(门控)+ golden F1=1.0
**Description:** `DeepDocParser` stub → 门控 import 真后端;parse→IR(bbox/page/ocr_conf 真填);parser-swap 后 mini golden F1=1.0 准入。
**Acceptance criteria:**
- [ ] `DeepDocParser.parse` 真实现,门控 import(库缺 → 清晰 `RuntimeError` 引导装 extra)。
- [ ] `PIPELINE_PARSER_BACKEND=deepdoc` 集成测:库可用跑、否则 skip;mini golden `F1=1.0` 不回归。
- [ ] 默认 `light` 不变。
**Verification:** `PIPELINE_PARSER_BACKEND=deepdoc pytest pipeline/tests/test_golden_set.py`(门控);默认 `pytest` 不变
**Dependencies:** T0.2、T2.5
**Files:** `pipeline/pipeline/parsing/deepdoc_parser.py`、`pipeline/pipeline/parsing/factory.py`、`pipeline/tests/test_deepdoc_parse.py`
**Estimated scope:** L

### Task T3.2 (A/A4):PaddleOCR OCR 通道(门控)+ ocr_conf 回填
**Description:** `PaddleOCRParser` 真后端(门控);OCR 块回填 `ocr_conf`(供指标 6 / §18.2④);扫描件 15min 超时。
**Acceptance criteria:**
- [ ] `PaddleOCRParser.parse` 真实现,门控 import(库/GPU 缺 → `RuntimeError`)。
- [ ] OCR 块带 `ocr_conf` + bbox/page;指标 6 在 OCR 文档生效。
- [ ] 扫描件超时 15min → PARSE_FAILED(E203)。
- [ ] 门控集成测无 GPU/库时 skip。
**Verification:** 门控集成测;`pytest pipeline/tests/test_qc.py`(指标 6 带 ocr_conf)
**Dependencies:** T3.1
**Files:** `pipeline/pipeline/parsing/paddleocr_parser.py`、`pipeline/pipeline/parsing/factory.py`、`config/settings.toml`、`pipeline/tests/test_paddleocr_parse.py`
**Estimated scope:** L

### Task T3.3 (A/A4):MinerU 兜底(门控)
**Description:** `MinerUParser` 真后端(门控);路由:DeepDoc 失败 → MinerU 重试一次 → 仍失败 PARSE_FAILED(E204)。
**Acceptance criteria:**
- [ ] `MinerUParser.parse` 真实现,门控 import;DeepDoc 失败 → MinerU 一次 → 仍失败 → PARSE_FAILED(E204)。
- [ ] 门控集成测无库时 skip。
**Verification:** 门控集成测
**Dependencies:** T3.1
**Files:** `pipeline/pipeline/parsing/mineru_parser.py`、`pipeline/pipeline/parsing/factory.py`、`pipeline/tests/test_mineru_parse.py`
**Estimated scope:** M

> **Checkpoint 3(完成):** 门控后端 import-guarded、默认 light 不变;golden F1=1.0;全量套件绿(无库/GPU/key 项 skip);所有 P0 SC 满足 + RTM 对应行翻 ✅/🟡。→ 交 Codex 复审。

---

## 全局 Definition of Done

- [ ] 现 **374 passed** 不破;新增测试全绿;`ruff check` 净;`alembic check` 无漂移。
- [ ] LLM 触点:fake 单测覆盖 + 真模型门控集成(有 key 真跑、无则 skip);默认 `*_enabled` 关。
- [ ] RTM 翻动:**S1-4 / S2-6 / S1-7 / S1-8 / S0-8 / O-5 / S4-12 / S4-11 / DM-3 / S4-2 / E2-1 / S3-15 / DM-2 / DM-4** → ✅;**S1-1/2/3** → 🟡(门控就位,生产验收)。更新 `GAP.md` + `RTM.md` 并核对 ✅ 行确有通过测试。
- [ ] 交 Codex 复审(`code-review-and-quality` + `security-and-hardening`),发现写 `.review/findings.json`,作者侧逐条修复或带 `spec_ref` 反驳。

## 建议执行顺序(承 PLAN 依赖图)

1. **并行起步**:T0.1(F)∥ T0.2(A)→ Checkpoint 0。
2. **Phase 1 并行**:T1.1(B4 fail-fast)∥ T1.2 ∥ T1.3 ∥ T1.4 ∥ T1.5 → Checkpoint 1。
3. **Phase 2**:T2.1 → T2.2 →(T2.3a → T2.3b)∥ T2.4 ∥ T2.5 → Checkpoint 2。
4. **Phase 3(门控,可移交甲方环境)**:T3.1 →(T3.2 ∥ T3.3)→ Checkpoint 3。
