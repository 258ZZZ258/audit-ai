# 实现计划 PLAN_P0:文档处理管线 v1.6 — P0 缺口落地

> SDD 阶段 2(Plan)。依据 `SPEC_P0.md`。**本文件是计划级**(依赖图 / 阶段 / 任务标题 + 规模 + 依赖 + 并行性 / 检查点 / 风险);**每任务的验收/验证/文件清单见 `TASKS_P0.md`**(待 PLAN 批准后出)。
> 本阶段只规划,不写代码。各任务落地走 `incremental-implementation` + `test-driven-development`,交 Codex 复审。

## Overview

把 SPEC_P0 三工作流(**A 生产解析栈 / B LLM P0 四项 / C ref_resolver**)拆成 ~16 个 S/M 任务,挂在一个共享 Foundation 上。三流**高度独立**(可三路并行),仅靠 Phase 0 的迁移 `0009` 与 IR 契约改动汇合。全程不破现 **374 passed**;LLM 真链路按 D2 门控(有 key 真跑、无则 skip);真解析后端按 A4 门控(库/GPU 可用才跑)。

## Architecture Decisions(承 SPEC §0 + 规划补充)

- **AD-1 三流并行 + 共享 Foundation**:A/B/C 无交叉依赖,除 `0009` 迁移(B2/B3/C2 共用字典与列)与 IR 契约(A 内部)。→ 适合分 3 路并行推进。
- **AD-2 LLM 触点全镜像 `e2_tag.py`**:纯函数 + client 注入 + server-side `_enforce` 字典裁剪 + 不臆测 + 非阻断 + 默认关。新 LLM 模块(`case_l2` / `l2_llm`)复用同骨架,降一致性风险。
- **AD-3 fail-fast 真链路**:Phase 1 先做 **B4(E2 接真模型)**——它接缝最全、改动最小,**最先打通 D2 真模型门控路径**,为 B1b/B2/B3 验证模式。真 LLM 不可用即早暴露。
- **AD-4 纯逻辑与 LLM 解耦**:案例引用对齐拆 **B1a(`case_ref_align` 纯逻辑,零模型可全测)** 与 **B1b(LLM 抽取)**;ref_resolver R1–R3 纯规则(零外部依赖)与 R4(跨文档 + 字典)分离。先交付可全测的纯逻辑。
- **AD-5 业务域写权威字段(D4)**:`doc_versions.biz_domains`(JSONB 多值,add-only;原单值 `biz_domain` 保留)+ `biz_domain_source`;确认按 profile 分档(P-INT 逐件 / 外规案例 LLM 直落 + 抽样)。下游 chunks/Milvus `biz_domain` ARRAY 从 `biz_domains` 取。
- **AD-6 真解析后端门控交付**:A4 把 stub 换成门控 import 真后端 + 路由;CI 默认 `light` 不变;真验收在甲方信创/GPU 环境。`method`/契约红线不破。
- **AD-7 add-only 严守**:所有 schema 改动走 `0009`(+ 必要 `0010`),autogenerate → upgrade → `alembic check` 无漂移;IR 加字段不删字段,更新基线测试。

## 依赖图

```
Phase 0 (Foundation, 并行)
  T0.1 迁移0009 + seeds ──────┐ (B2/B3/C2 依赖)
  T0.2 IR ocr_conf + 表markdown ─┐ (A1/A3/A4 + QC指标6 依赖)
                                │ │
Phase 1 (纯逻辑 + 真链路 fail-fast, 高并行)
  T1.1 B4 E2 真模型打通 ────────┼─┼─→ (验证 D2 模式,供 B1b/B2/B3)
  T1.2 B1a case_ref_align 纯对齐 │ │
  T1.3 C1 ref_resolver R1–R3 ───┘ │
  T1.4 C3 ref_render 渲染原语      │
  T1.5 A1 xlsx 直读 ───────────────┘
                                │
Phase 2 (功能构建于 Foundation)
  T2.1 B1b 案例引用外规 LLM 抽取  (deps T1.1 模式, T1.2 align)
  T2.2 B2 违规事由分类 + dict     (deps T0.1, T1.1)
  T2.3a B3 业务域打标 + 写 biz_domains  (deps T0.1)
  T2.3b B3 profile 分档确认 + 下游取值  (deps T2.3a)
  T2.4 C2 R4 跨文档 + dict_aliases (deps T0.1, T1.3)
  T2.5 A3 白名单 jpg/png + 路由表  (deps T0.2, T1.5)
                                │
Phase 3 (门控真后端, 真验收甲方环境)
  T3.1 A4 DeepDoc 真后端 + golden F1=1.0  (deps T0.2, T2.5)
  T3.2 A4 PaddleOCR OCR + ocr_conf 回填   (deps T3.1)
  T3.3 A4 MinerU 兜底                      (deps T3.1)
```

## Task List

> 规模:XS/S/M/L(L 已尽量拆)。流:A/B/C/F(Foundation)。每任务详细验收见 TASKS_P0。

### Phase 0 — Foundation(并行,先建地基)
- [x] **T0.1 (F)** 迁移 `0009` + seeds —— `dict_violation_types`(+v0-draft 种子,样例聚类)、`dict_aliases`(+别名种子)、`doc_versions.biz_domains` JSONB + `biz_domain_source`。**M**。deps: 无。
- [x] **T0.2 (A)** IR add-only `Block.ocr_conf` + `Table` markdown 序列化辅助(合并单元格按 rowspan/colspan 展开);切块表格块改用它;QC 指标 6 接 `ocr_conf`(有值才参与)。**M**。deps: 无。

**Checkpoint 0(Foundation)**:`alembic upgrade head` + `alembic check` 无漂移;`ruff check` 净;`test_ir`/`test_v16_fidelity` 更新通过;现 374 不破。→ **人工 review 后进 Phase 1**。

### Phase 1 — 纯逻辑 + 真链路 fail-fast(高并行)
- [ ] **T1.1 (B/B4)** E2 接真模型打通 —— dict PG 加载在真 seed 验证 + `e2_enabled=true` 端到端 + **真模型门控集成测**(有 `OPENAI_API_KEY` 真跑 / 无则 skip)。**S–M**。deps: 无(dicts 已 seed)。→ 翻 RTM **E2-1**。
- [ ] **T1.2 (B/B1a)** `case_ref_align` 纯对齐 —— "《X》第N条" → 文号精确/标题精确/`clause_path_norm` 三级匹配;超界/未命中 → `ref_unresolved`。纯逻辑零模型。**M**。deps: 无。
- [ ] **T1.3 (C/C1)** `ref_resolver` R1–R3 —— 文档内确定性指代(本办法/前款/绝对条款)standoff 解析,写 `clause_references`(`method=rule`)。从 S3 后触发。**M**。deps: 无(表已建)。→ 翻 **S3-15(R1–R3)/DM-2**。
- [ ] **T1.4 (C/C3)** `ref_render` 窗口渲染原语 —— span 倒序插注释、gloss≤30、UNRESOLVED 不渲染。纯逻辑。**S**。deps: 无。
- [ ] **T1.5 (A/A1)** xlsx 直读(openpyxl)+ 白名单含 xlsx —— 每 sheet → `Table` block → IR。**M**。deps: T0.2(markdown 辅助)。→ 翻 **S1-4**。

**Checkpoint 1**:纯逻辑测全绿;B4 真链路有 key 真跑 / 无 key skip(不联网);`clause_references` 在 R1–R3 有 resolved 行;xlsx 可入库。→ **人工 review**。

### Phase 2 — 功能构建(依赖 Foundation)
- [ ] **T2.1 (B/B1b)** 案例引用外规 LLM 抽取 —— `case_l2.extract_cited`(JSON,不臆测)→ 接 T1.2 `align` → 写 `cases.cited_regulations`。**M**。deps: T1.1(模式)、T1.2(align)。→ 翻 **S4-12**(最高价值)。
- [ ] **T2.2 (B/B2)** 违规事由分类 —— `case_l2.classify_violation` 约束 `dict_violation_types` + `_enforce` → `cases.violation_category`;空/未命中留 None(consumed-when-present)。**M**。deps: T0.1、T1.1。→ 翻 **S4-11/DM-3**。
- [ ] **T2.3a (B/B3)** 业务域 L2 打标 —— `l2_llm.tag_biz_domain` 约束 `dict_biz_domains` + `_enforce` → 写 `doc_versions.biz_domains` + `biz_domain_source=llm` + `ai_label`。**M**。deps: T0.1。
- [ ] **T2.3b (B/B3)** 业务域 profile 分档确认 + 下游取值 —— P-INT 逐件入 META_REVIEW(转 `confirmed`)/ P-EXT·QA·CASE 直落 + 抽样;manifest 优先与冲突路径;chunks/Milvus `biz_domain` 从 `biz_domains` 取。**M**。deps: T2.3a。→ 翻 **S4-2**。
- [ ] **T2.4 (C/C2)** R4 跨文档 + `dict_aliases` + `pending_target` 夜间重试 —— 三级匹配(文号/标题/别名);未命中 pending_target;永久未解析导语料缺口清单(复用 T5)。**M**。deps: T0.1、T1.3。→ 翻 **DM-4**。
- [ ] **T2.5 (A/A3)** 白名单 jpg/png + 路由表 format→backend —— magic number 加 jpg/png/xlsx;路由(pdf-notext/jpg/png→paddleocr,失败→mineru);无 OCR 后端时 jpg/png → QUARANTINED(不静默丢)。**S–M**。deps: T0.2、T1.5。→ 翻 **S0-8/O-5**。

**Checkpoint 2**:B 全四项端到端(fake 单测 + 门控真测);业务域三档行为正确 + 下游取值;ref_resolver R1–R4 完整;路由覆盖全格式且 jpg/png 无 OCR 时隔离不崩。→ **人工 review**。

### Phase 3 — 门控真后端(真验收甲方信创/GPU 环境)
- [ ] **T3.1 (A/A4)** DeepDoc 真后端(门控 import)+ parser-swap 后 mini golden F1=1.0 准入。**L**。deps: T0.2、T2.5。→ RTM **S1-1/S1-2** 标 🟡(就位,CI skip,生产验收)。
- [ ] **T3.2 (A/A4)** PaddleOCR OCR 通道(门控)+ `ocr_conf` 真回填(供指标 6 / §18.2④)+ 扫描件 15min 超时。**L**。deps: T3.1。
- [ ] **T3.3 (A/A4)** MinerU 兜底(门控:DeepDoc 失败 → 重试一次 → 仍失败 PARSE_FAILED)。**M**。deps: T3.1。→ RTM **S1-3** 🟡。

**Checkpoint 3(完成)**:门控后端 import-guarded、默认 `light` 不变;golden F1=1.0 不回归;全量套件绿(无库/无 GPU/无 key 项 skip);所有 P0 SC 满足。→ **交 Codex 复审**。

## 并行化建议

- **三路并行**:A、B、C 可分配三 agent/session 并行(Phase 1 起)。
- **必须串行**:T0.1 迁移先于 B2/B3/C2;T0.2 IR 先于 A1/A3/A4;B4 先于 B1b/B2/B3(验证真链路模式);C1 先于 C2。
- **需先定契约再并行**:`doc_versions.biz_domains` 列形态(T0.1)定后 B3 才动;IR `ocr_conf`(T0.2)定后 A4 才回填。
- **门控隔离**:Phase 3(A4)依赖外部环境,与 B/C 完全解耦,可最后单独推进或移交甲方环境。

## Risks and Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| R1 网关轻量模型/配额未定(CP-005-①③) | 高 | D2 门控:fake 单测保覆盖,真测有 key 才跑;`*_enabled` 默认关;模型名走 env/config 可换 |
| R2 dict_violation_types v0-draft 质量低 | 中 | consumed-when-present 不阻塞;抽样核验入看板;字典版本化,评审后增量重打 |
| R3 A4 外部依赖(GPU/信创/RAGFlow)本地不可验 | 中 | 门控 import + golden F1=1.0 准入门;CI 默认 light;真验收甲方环境;交付"可门控真后端+路由" |
| R4 业务域多值 schema 改动影响下游取值 | 中 | add-only(原单值保留);T2.3b 集成测覆盖 chunks/Milvus 取 `biz_domains`;迁移 `alembic check` 守漂移 |
| R5 R4 pending_target 收敛依赖外规入库进度 | 低 | 夜间重试 + 缺口清单(设计已含);不阻塞案例/条款入库 |
| R6 IR `ocr_conf` 改动触基线契约测 | 低 | add-only;同步更新 `test_ir`/`test_v16_fidelity`;指标 6 仅有值才参与 |
| R7 LLM 直落污染 `clause_references.method` | 中 | 红线:`method` 恒 `rule`;ref_resolver 纯规则,禁混入 LLM(SPEC §11 Never) |
| R8 触现 374 回归 | 中 | 每任务只跑波及范围;Checkpoint + 合并前全量门控全跑一次 |

## Open Questions(不阻塞写代码,PLAN 标依赖)

- Q1 网关模型/配额(CP-005-①③)→ B 真测口径;先用 env/config 占位。
- Q2/Q3 dict_violation_types / dict_biz_domains / dict_entity_types 评审(§16-6/-7)→ 字典质量;v0-draft 先行。
- Q4 案例自然人姓名脱敏(§16-4)→ B1/B2 落库;按密级口径,待确认前不特殊处理(沿用现状)。
- Q6 DeepDoc/PaddleOCR/MinerU 信创+GPU 可部署性(§16-1)→ A4 真验收。
- Q7 §14 敏感词进出过滤 → 本轮 P2 **不做**(SEC-4);如验收口径要求再拉入。

## 下一步

PLAN 批准后 → 出 **`TASKS_P0.md`**(每任务:Description / Acceptance criteria / Verification / Dependencies / Files / Scope),按本依赖图排序,逐任务 TDD 落地。
